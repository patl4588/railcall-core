#!/usr/bin/env python3
"""
Test suite for the RailCall support brain — the CI gate so a bad deploy can never silently take down
live support (this is exactly how the Cloudflare-1010 regression would have been caught automatically).

Hermetic: the network is mocked and the Groq key is forced, so it runs anywhere with zero secrets and
zero external calls. Run either way:
    python3 -m unittest bot/test_support.py -v
    pytest bot/test_support.py
"""
import os
import sys
import json
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_support_brain as brain


def setUpModule():
    # Force a dummy key so the cascade runs against the mock regardless of the CI environment.
    # NB: deliberately NOT in real Groq-key shape so it never trips a secret scanner or push-protection.
    brain.GROQ_API_KEY = "DUMMY-TEST-KEY-not-a-real-secret"


class FakeResp:
    """Stand-in for the urlopen context manager: has .status and .read()."""
    def __init__(self, status=200, payload=None):
        self.status = status
        self._b = json.dumps(payload or {}).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def groq_ok(text):
    return {"choices": [{"message": {"content": text}}]}


class Intent(unittest.TestCase):
    def test_greeting_matches(self):
        for t in ["hi", "hey", "hello", "yo", "gm", "Good morning", "howdy!"]:
            self.assertTrue(brain.is_greeting(t), t)

    def test_greeting_rejects_non_greetings(self):
        for t in ["hey there what's up", "how do i install", "hix", "hire"]:
            self.assertFalse(brain.is_greeting(t), t)

    def test_questions(self):
        for t in ["how do i install", "what is a flow", "is there a free tier?",
                  "install failed", "stuck on setup", "unable to connect"]:
            self.assertTrue(brain.is_question(t), t)

    def test_non_questions(self):
        for t in ["cool", "nice product", "thanks", "lgtm"]:
            self.assertFalse(brain.is_question(t), t)

    def test_escalation_triggers(self):
        for t in ["i want a refund", "i was charged twice", "can't log in",
                  "please talk to a human", "this is a bug", "security issue", "data breach"]:
            self.assertTrue(brain.wants_human(t), t)

    def test_escalation_ignores_normal(self):
        for t in ["how much is it", "what is railcall", "hi"]:
            self.assertFalse(brain.wants_human(t), t)


class Grounding(unittest.TestCase):
    def test_kb_loads(self):
        self.assertIn("flow", brain.load_kb().lower())

    def test_system_prompt_has_facts_and_honesty_rule(self):
        sp = brain.system_prompt()
        self.assertIn("$0.01", sp)              # canonical fact present
        self.assertIn("UNKNOWN", sp)            # honesty stance present
        self.assertIn("not certain", sp)        # the "don't guess, escalate" rule present


class Cascade(unittest.TestCase):
    def test_first_model_ok(self):
        with mock.patch("railcall_support_brain.urllib.request.urlopen",
                        return_value=FakeResp(200, groq_ok("hello world"))):
            self.assertEqual(brain.groq_chat([{"role": "user", "content": "hi"}]), "hello world")

    def test_cascades_past_a_failing_model(self):
        calls = {"n": 0}

        def fake(req, timeout=0):
            calls["n"] += 1
            return FakeResp(500 if calls["n"] == 1 else 200, groq_ok("second model answered"))

        with mock.patch("railcall_support_brain.urllib.request.urlopen", side_effect=fake):
            self.assertEqual(brain.groq_chat([{"role": "user", "content": "hi"}]), "second model answered")
            self.assertGreaterEqual(calls["n"], 2)  # proved it fell through to the 2nd model

    def test_all_models_down_returns_none(self):
        with mock.patch("railcall_support_brain.urllib.request.urlopen", side_effect=OSError("net down")):
            self.assertIsNone(brain.groq_chat([{"role": "user", "content": "hi"}]))

    def test_user_agent_header_set(self):
        """Regression guard for the Cloudflare-1010 bug: every Groq request MUST carry a real UA."""
        seen = {}

        def cap(req, timeout=0):
            seen["ua"] = {k.lower(): v for k, v in req.header_items()}.get("user-agent")
            return FakeResp(200, groq_ok("ok"))

        with mock.patch("railcall_support_brain.urllib.request.urlopen", side_effect=cap):
            brain.groq_chat([{"role": "user", "content": "hi"}])
        self.assertTrue(seen["ua"], "no User-Agent set — Cloudflare would 1010-block this")
        self.assertNotIn("python-urllib", (seen["ua"] or "").lower())

    def test_no_key_returns_none_without_calling_network(self):
        with mock.patch.object(brain, "GROQ_API_KEY", ""):
            with mock.patch("railcall_support_brain.urllib.request.urlopen",
                            side_effect=AssertionError("must not hit network with no key")):
                self.assertIsNone(brain.groq_chat([{"role": "user", "content": "hi"}]))


class AnswerFlow(unittest.TestCase):
    def test_greeting_short_circuits_with_no_network(self):
        # If it tried the network here it would fail; a greeting must return the canned welcome instead.
        with mock.patch("railcall_support_brain.urllib.request.urlopen",
                        side_effect=AssertionError("greeting must not hit the model")):
            r = brain.answer([{"role": "user", "content": "hi"}], "hi")
        self.assertIn("RailCall assistant", r)

    def test_question_uses_groq(self):
        with mock.patch("railcall_support_brain.urllib.request.urlopen",
                        return_value=FakeResp(200, groq_ok("a grounded answer"))):
            r = brain.answer([{"role": "user", "content": "what is a flow"}], "what is a flow")
        self.assertEqual(r, "a grounded answer")

    def test_handoff_summary_never_empty_even_when_down(self):
        with mock.patch("railcall_support_brain.urllib.request.urlopen", side_effect=OSError()):
            s = brain.handoff_summary([{"role": "user", "content": "refund pls"}])
        self.assertTrue(s and s.strip())  # a human always gets *something* to act on


class Observability(unittest.TestCase):
    def test_log_event_writes_json_line(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "events.jsonl")
        with mock.patch.object(brain, "EVENTS_LOG", path):
            brain.log_event("answered", user="tester", channel="support", chars=42)
        with open(path) as f:
            rec = json.loads(f.read().strip())
        self.assertEqual(rec["kind"], "answered")
        self.assertEqual(rec["channel"], "support")
        self.assertIn("ts", rec)

    def test_log_event_never_raises(self):
        # Pointed at an unwritable path, it must swallow the error (never crash the bot loop).
        with mock.patch.object(brain, "EVENTS_LOG", "/proc/nonexistent/nope.jsonl"):
            brain.log_event("answered", user="x")  # should not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
