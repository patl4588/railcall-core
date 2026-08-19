"""Hosted /v1/compose must survive one bad model, and its 502 must be triageable.

INCIDENT (2026-08-19)
---------------------
`POST /v1/compose` returned 502 "hosted engine call failed — flow refunded, try
again" for a key with 465 flows remaining. That is the hosted Builder down for
EVERY user without their own Groq/OpenAI key — not one user's glitch.

Two defects turned one upstream problem into a day-long outage:

 1. NO FALLBACK. The route asked for _COMPOSE_MODELS[0] and gave up. The
    allowlist has a second model that was never tried.

 2. NO DIAGNOSABILITY. The 502 detail was a fixed string, so a decommissioned
    model, a revoked key, and a transient blip were indistinguishable from the
    client. Root-causing required Render log access.

The fix must not leak: upstream exception text routinely embeds the request,
including an Authorization header or a `?key=` query param. It is scrubbed
before it leaves the process, and the user's prompt is never echoed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compose_fallback as cf  # noqa: E402

MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")


class _Deliberate(Exception):
    """Stands in for fastapi.HTTPException — the contract is `status_code`."""

    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


class ComposeFallbackTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def test_falls_through_to_second_model(self):
        """THE OUTAGE: the first model fails, a healthy second one exists, and
        the pre-fix code still 502'd the entire hosted tier."""
        def complete(clean, model):
            self.calls.append(model)
            if model == MODELS[0]:
                raise RuntimeError("model_decommissioned")
            return "composed-ok"

        reply, used, tried = cf.compose_with_fallback(
            complete, [], MODELS[0], MODELS)

        self.assertEqual(reply, "composed-ok")
        self.assertEqual(used, MODELS[1],
                         "must report the model that ACTUALLY answered, not "
                         "the one that was asked for")
        self.assertEqual(self.calls, list(MODELS), "primary first, then fallback")
        self.assertEqual(tried, list(MODELS))

    def test_primary_success_does_not_call_fallback(self):
        """No wasted upstream spend when the first choice works."""
        def complete(clean, model):
            self.calls.append(model)
            return "ok"

        reply, used, _ = cf.compose_with_fallback(complete, [], MODELS[0], MODELS)
        self.assertEqual((reply, used), ("ok", MODELS[0]))
        self.assertEqual(self.calls, [MODELS[0]], "must stop at the first success")

    def test_deliberate_http_signal_is_not_retried(self):
        """503-key-unset is our own signal. Retrying cannot fix an unset key —
        it would only delay the honest error."""
        def complete(clean, model):
            self.calls.append(model)
            raise _Deliberate(503, "compose key not set")

        with self.assertRaises(_Deliberate) as ctx:
            cf.compose_with_fallback(complete, [], MODELS[0], MODELS)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(len(self.calls), 1,
                         "a status_code-bearing error must short-circuit")

    def test_all_models_failing_raises_last_error(self):
        """When everything is down it must still fail — carrying the real
        upstream error so the route can surface something diagnosable."""
        def complete(clean, model):
            self.calls.append(model)
            raise RuntimeError("upstream 429 rate_limit_exceeded")

        with self.assertRaises(RuntimeError) as ctx:
            cf.compose_with_fallback(complete, [], MODELS[0], MODELS)

        self.assertIn("rate_limit_exceeded", str(ctx.exception))
        self.assertEqual(self.calls, list(MODELS),
                         "every allowlisted model must be attempted")

    def test_requested_model_is_never_tried_twice(self):
        def complete(clean, model):
            self.calls.append(model)
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            cf.compose_with_fallback(complete, [], MODELS[1], MODELS)
        self.assertEqual(len(self.calls), len(set(self.calls)), "no duplicates")
        self.assertEqual(self.calls[0], MODELS[1], "requested model goes first")


class ErrorScrubTest(unittest.TestCase):
    """The 502 now carries upstream text, so the scrubber is a security control:
    a leaked platform key would compromise the hosted tier for every user."""

    def test_scrubs_credentials(self):
        for raw, secret in [
            ("Bearer gsk_liveKeyABC123456789", "gsk_liveKeyABC123456789"),
            ("401 from https://api.groq.com/v1/c?key=gsk_secret999", "gsk_secret999"),
            ("openai rejected sk-proj-AAAAbbbbCCCC1234", "sk-proj-AAAAbbbbCCCC1234"),
        ]:
            with self.subTest(raw=raw):
                out = cf.scrub(raw)
                self.assertNotIn(secret, out)
                self.assertIn("***", out)

    def test_keeps_the_diagnostic_value(self):
        """Scrubbing must not destroy the signal — surfacing it was the point."""
        out = cf.scrub("HTTPError: 429 rate_limit_exceeded for llama-3.3-70b-versatile")
        for keep in ("429", "rate_limit_exceeded", "llama-3.3-70b-versatile"):
            self.assertIn(keep, out)

    def test_describe_failure_names_models_and_omits_prompt(self):
        detail = cf.describe_failure(
            RuntimeError("503 upstream unavailable"), list(MODELS))
        self.assertIn("flow refunded", detail, "keep the user-actionable part")
        self.assertIn("RuntimeError", detail, "name the failure class")
        self.assertIn(MODELS[0], detail)
        self.assertIn(MODELS[1], detail)

    def test_describe_failure_never_echoes_user_content(self):
        """A prompt can hold anything the operator typed; it must not ride out
        in an error string that gets logged and screenshotted."""
        detail = cf.describe_failure(RuntimeError("boom"), list(MODELS))
        self.assertNotIn("patient", detail.lower())
        self.assertLess(len(detail), 400, "bounded, not a transcript dump")

    def test_scrub_bounds_length(self):
        self.assertLessEqual(len(cf.scrub("x" * 5000)), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
