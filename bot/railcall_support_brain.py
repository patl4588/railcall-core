#!/usr/bin/env python3
"""
RailCall support BRAIN — the channel-agnostic core shared by every surface
(Discord, Telegram, and later a web widget). One brain, many doors.

Why it's built this way (matches the product's own ethos):
  • LOCAL + Groq only — stdlib `urllib` for the Groq cascade, never Anthropic [[project_kai]].
    No third-party helpdesk, no cloud data-sink ingesting customer messages.
  • GROUNDED — answers come from RailCall's canonical facts + an editable KB (railcall_kb.md).
    If a question isn't covered, it says so and hands off to a human — it never guesses or
    fakes a confident answer. Same honesty bar as the product: UNKNOWN ≠ PASS.
  • ESCALATION-AWARE — flags when a human should take over and writes a one-line handoff
    summary so the teammate never starts cold (the one feature every SOTA support stack sells).

No Discord/Telegram imports live here on purpose — both adapters import this module verbatim.
"""
import os
import re
import json
import time
import urllib.request


def _secret(env_name, file_name):
    """Read a secret from the env, else from a 0600 file in ~/.railcall/. Lets a token be dropped in
    with one command; nothing secret is ever hard-coded or logged."""
    v = os.environ.get(env_name, "").strip()
    if v:
        return v
    try:
        with open(os.path.expanduser("~/.railcall/" + file_name)) as f:
            return f.read().strip()
    except Exception:
        return ""


GROQ_API_KEY = _secret("GROQ_API_KEY", "groq_key")
GROQ_MODELS = [m.strip() for m in os.environ.get(
    "GROQ_MODELS", "llama-3.3-70b-versatile,llama-3.1-8b-instant").split(",") if m.strip()]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# A named User-Agent: the default "Python-urllib/x" signature trips Cloudflare bot-blocking (err 1010)
# on some networks. A real UA sails through and is friendlier to log on the provider side.
USER_AGENT = os.environ.get("RAILCALL_UA", "RailCall-Support/1.0 (+https://railcall.ai)")

# Structured, queryable observability: one JSON object per event (vs. grepping free-text logs). The
# analytics + watchdog read this. Best-effort — logging must NEVER raise into the bot's message loop.
EVENTS_LOG = os.environ.get("RAILCALL_EVENTS", os.path.expanduser("~/.railcall/support_events.jsonl"))


def log_event(kind, **fields):
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind}
        rec.update(fields)
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

# ── Grounding: canonical facts (never invented) + a hot-reloaded KB file ──────
BASE_FACTS = (
    "RailCall is a local-first AI-agent governance platform — a Layer-2 Terminal for agentic "
    "development. Canonical facts (never contradict; never invent beyond these):\n"
    "- Users own 100% of the code RailCall helps them generate; cancel and they keep every line.\n"
    "- Keys, files, workflow data, and generated code NEVER leave the user's machine. RailCall runs "
    "locally in dry-run/proof mode by default — nothing executes until the user approves it.\n"
    "- Billing is blind-metered: a flat $0.01 per governed flow. The client sends only a hashed key + a "
    "one-time nonce to check balance — never the raw key, files, or data. A transaction register, not a data sink.\n"
    "- Every governed flow mints an Ed25519-signed receipt on the user's machine; verify it offline with `railcall verify`.\n"
    "- Free tier = 100 flows, no card. Flows are prepaid; balance never expires; no per-seat fees. The unit is a 'flow' (not a 'run').\n"
    "- Install: curl -fsSL https://railcall.ai/install.sh | bash . Studio opens locally at 127.0.0.1 . Docs: railcall.ai/docs.html .\n"
    "- Honest stance: RailCall does NOT auto-grant SOC2/HIPAA/GDPR; UNKNOWN means unverified, never a pass.\n"
)

KB_PATH = os.environ.get(
    "RAILCALL_KB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "railcall_kb.md"))
_kb_cache = {"mtime": -1.0, "text": ""}


def load_kb():
    """Read the editable KB (FAQ / grounding). Hot-reloads when the file's mtime changes, so a CM can
    add an answer and the bot uses it on the next message — no restart. Missing file = base facts only."""
    try:
        m = os.path.getmtime(KB_PATH)
        if m != _kb_cache["mtime"]:
            with open(KB_PATH, encoding="utf-8") as f:
                _kb_cache["text"] = f.read()
            _kb_cache["mtime"] = m
    except Exception:
        _kb_cache["text"] = ""
    return _kb_cache["text"]


def system_prompt():
    kb = load_kb().strip()
    kb_block = ("\n\nKNOWLEDGE BASE (authoritative — prefer these answers where they fit):\n" + kb) if kb else ""
    return (
        "You are the RailCall community & support assistant in the official RailCall community "
        "(Discord/Telegram). Be concise, friendly, and accurate — answer in under ~1000 characters.\n\n"
        + BASE_FACTS + kb_block +
        "\n\nRULES:\n"
        "- Answer ONLY from the facts + knowledge base above. If the question is not covered, say you are "
        "not certain and that you'll loop in a human — do NOT guess, invent features/prices, or fake a "
        "confident answer. \"I'm not sure yet — a teammate will confirm\" is a correct, good answer.\n"
        "- Never give legal or financial advice. Never claim a compliance certification RailCall doesn't hold.\n"
        "- Speak as RailCall (the system), not as \"an AI language model\". No filler, no padding."
    )


# ── Intent detection ─────────────────────────────────────────────────────────
GREETING = re.compile(r"^\s*(hi+|hey+|hello+|yo+|sup|gm|good (morning|evening|afternoon)|howdy)\b[\s!.,]*$", re.I)
ESCALATE_PATTERNS = re.compile(
    r"\b(refund|charged twice|double char+ed|chargeback|billing (issue|problem|error)|"
    r"can'?t log ?in|locked out|account (issue|problem|deleted)|talk to (a )?(human|person|someone|team)|"
    r"speak to (a )?(human|person)|this is a bug|not working|broken|urgent|lawsuit|legal|"
    r"data (leak|breach)|security (issue|hole|bug))\b", re.I)


def is_greeting(text):
    return bool(GREETING.match(text or ""))


def wants_human(text):
    return bool(ESCALATE_PATTERNS.search(text or ""))


def is_question(text):
    t = (text or "").strip().lower()
    if "?" in t:
        return True
    return bool(re.match(
        r"^(how|what|why|when|where|who|can|does|do|is|are|should|could|would|help|"
        r"any(one|body)|is there|i can'?t|it (won'?t|doesn'?t)|error|stuck|install|set ?up|"
        r"unable|fail(ed|s)?|won'?t|doesn'?t|not able)\b", t))


# ── Groq cascade (sync, stdlib — reused by every adapter) ─────────────────────
def groq_chat(messages, max_tokens=700, temperature=0.3, timeout=30):
    """Sync Groq cascade over GROQ_MODELS via stdlib urllib. Returns the first good reply, else None.
    Sync on purpose: the Telegram poll loop calls this directly; the async Discord bot wraps it in an
    executor. One code path, zero extra dependencies, never Anthropic."""
    if not GROQ_API_KEY:
        return None
    for model in GROQ_MODELS:
        body = json.dumps({"model": model, "messages": messages,
                           "temperature": temperature, "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(GROQ_URL, data=body, method="POST", headers={
            "Authorization": "Bearer " + GROQ_API_KEY, "Content-Type": "application/json",
            "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if getattr(r, "status", 200) != 200:
                    continue  # cascade to the next model
                data = json.loads(r.read().decode())
                txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                if txt:
                    return txt
        except Exception:
            continue  # network / model error -> try the next model, else fall through to None
    return None


GREETING_REPLY = (
    "\U0001f44b Hey! I'm the RailCall assistant. Ask me anything — install, BYOK, webhooks, receipts, "
    "billing — or tell us what you're building. Stuck on something specific? Paste the command you ran + "
    "what you saw and I'll dig in."
)

FALLBACK = (
    "I couldn't reach the assistant just now — a teammate will follow up. Meanwhile, the docs at "
    "railcall.ai/docs.html cover most setup questions."
)


def answer(history, user_text=""):
    """Grounded reply for the latest turn. `history` = list of {role, content} (oldest first).
    Greetings get an instant canned welcome (no model call, no cost). Everything else runs the
    grounded cascade. Returns a string, or None if every model failed (caller uses FALLBACK)."""
    if is_greeting(user_text):
        return GREETING_REPLY
    msgs = [{"role": "system", "content": system_prompt()}] + list(history)
    return groq_chat(msgs)


def handoff_summary(history):
    """A one-line issue summary for the human CM, so escalations never start cold."""
    convo = "\n".join("%s: %s" % (m.get("role"), m.get("content", "")) for m in history[-8:])
    msgs = [
        {"role": "system", "content": "Summarize this support conversation for a human teammate in ONE "
         "short line: what the user needs + any command/error/receipt ID they mentioned. No preamble."},
        {"role": "user", "content": convo[:3000]},
    ]
    return groq_chat(msgs, max_tokens=120, temperature=0.2) or "User needs a hand — see the thread above."
