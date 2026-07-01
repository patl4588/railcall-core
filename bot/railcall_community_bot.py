#!/usr/bin/env python3
"""
RailCall community & support bot — runs the Discord automatically.

What it does:
  • Answers questions in any/all text channels (always in support-style channels; elsewhere on an
    @mention or a question-shaped message — so it helps without spamming casual chat).
  • Generates replies through the GROQ CASCADE (capable model first, fast model as fallback) —
    never Anthropic. Grounded in a RailCall system prompt so answers are accurate, not generic.
  • Welcomes new members in the welcome channel.
  • Escalates to a human (pings ESCALATE_MENTION) when the user asks for billing/refund/account/human
    help or the model flags uncertainty — so nobody falls through the cracks.

It is local-first: runs on your own machine/server, talks only to Discord + Groq. No data sink.

────────────────────────────────────────────────────────────────────────────
SETUP (one-time):
  1. Create the bot + token:
       https://discord.com/developers/applications → New Application "RailCall" → Bot →
       Reset Token → copy it (this is a SECRET — keep it; never commit it).
       Under "Privileged Gateway Intents", enable MESSAGE CONTENT INTENT and SERVER MEMBERS INTENT.
  2. Invite it to the server (OAuth2 → URL Generator):
       scopes: bot   |   bot permissions: View Channels, Send Messages, Read Message History
       open the generated URL and add it to the RailCall server.
  3. Install + run (on your 128GB server):
       python3 -m pip install -U discord.py aiohttp
       export DISCORD_BOT_TOKEN="•••"      # from step 1
       export GROQ_API_KEY="•••"           # your existing Groq key
       export ESCALATE_MENTION="<@YOUR_DISCORD_USER_ID>"   # optional: who gets pinged on escalation
       python3 bot/railcall_community_bot.py
     Keep it alive with the launchd plist in bot/README.md.
────────────────────────────────────────────────────────────────────────────
"""
import os
import re
import sys
import signal
import asyncio

try:
    import discord
except ImportError:
    sys.exit("Missing dependency. Run: python3 -m pip install -U discord.py aiohttp")
import aiohttp

# ── Config (all via env or a 0600 file; nothing secret is hard-coded) ────────
def _secret(env_name, file_name):
    """Read a secret from the env, else from ~/.railcall/<file_name>. The file path lets you drop a
    token/key in with one Terminal command — the bot reads it itself, so it never has to be pasted in
    chat or handled by anyone else. Keep the file chmod 600."""
    v = os.environ.get(env_name, "").strip()
    if v:
        return v
    try:
        with open(os.path.expanduser("~/.railcall/" + file_name)) as f:
            return f.read().strip()
    except Exception:
        return ""

TOKEN = _secret("DISCORD_BOT_TOKEN", "bot_token")
GROQ_API_KEY = _secret("GROQ_API_KEY", "groq_key")
# Cascade: capable model first, fast model as fallback. Comma-separated, tried in order.
GROQ_MODELS = [m.strip() for m in os.environ.get(
    "GROQ_MODELS", "llama-3.3-70b-versatile,llama-3.1-8b-instant").split(",") if m.strip()]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Channels the bot will NOT auto-answer in (one-way / noise). It still answers @mentions everywhere.
DENY_CHANNELS = set(c.strip().lower() for c in os.environ.get(
    "DENY_CHANNELS", "announcements,mod-log,changelog,welcome").split(",") if c.strip())
# Channels where the bot answers EVERY message (support-style). Others: only mentions/questions.
SUPPORT_CHANNELS = set(c.strip().lower() for c in os.environ.get(
    "SUPPORT_CHANNELS", "support,bot-lab").split(",") if c.strip())
WELCOME_CHANNEL = os.environ.get("WELCOME_CHANNEL", "welcome").strip().lower()
ESCALATE_MENTION = os.environ.get("ESCALATE_MENTION", "").strip()  # e.g. "<@123>" or "<@&roleid>"

# Phrases that should always loop in a human (the bot answers, then pings the team).
ESCALATE_PATTERNS = re.compile(
    r"\b(refund|charged twice|double char+ed|chargeback|billing (issue|problem|error)|"
    r"can'?t log ?in|locked out|account (issue|problem|deleted)|talk to (a )?(human|person|someone)|"
    r"this is a bug|broken|urgent|lawsuit|legal)\b", re.I)

SYSTEM_PROMPT = (
    "You are the RailCall community & support assistant in the official RailCall Discord. "
    "Be concise, friendly, and accurate — answer in under ~1200 characters.\n\n"
    "RailCall is a local-first AI-agent governance platform — a Layer-2 Terminal for agentic "
    "development. Hard facts you must stay true to:\n"
    "• Users own 100% of the code RailCall helps them generate; cancel and they keep every line.\n"
    "• Their keys, files, workflow data, and generated code NEVER leave their machine. RailCall runs "
    "locally in dry-run/proof mode by default.\n"
    "• Billing is blind-metered: a flat $0.01 per governed flow. The client sends only a hashed key + a "
    "one-time nonce to check balance — never the raw key, files, or data. It's a transaction register, "
    "not a data sink.\n"
    "• Every governed flow mints an Ed25519-signed receipt on the user's machine — they can verify it "
    "offline with `railcall verify` (tamper-evident; no trust required).\n"
    "• Free tier = 100 flows, no card. Flows are prepaid; balance never expires; no per-seat fees. The "
    "customer-facing unit is a 'flow' (not a 'run').\n"
    "• Install: curl -fsSL https://railcall.ai/install.sh | bash . Studio opens locally at 127.0.0.1. "
    "Docs: railcall.ai/docs.html . Community + support is this Discord.\n"
    "• Honest stance: RailCall does NOT auto-grant SOC2/HIPAA/GDPR; UNKNOWN means unverified, never a pass.\n\n"
    "Rules: Never invent features, prices, or guarantees. Never give legal or financial advice. "
    "If something needs a human (billing disputes, refunds, account access, an unconfirmed bug), say so "
    "plainly and tell them a team member will follow up. If you are unsure, say you're not certain rather "
    "than guessing."
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# Per-channel cooldown so the bot can't get into a tight loop or flood a channel.
_last_reply = {}  # channel_id -> monotonic seconds
COOLDOWN_S = float(os.environ.get("COOLDOWN_S", "3"))


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if "?" in t:
        return True
    return bool(re.match(r"^(how|what|why|when|where|who|can|does|do|is|are|should|could|would|help|"
                         r"any(one|body)|is there|i can'?t|it (won'?t|doesn'?t)|error|stuck)\b", t))


async def groq_answer(session: aiohttp.ClientSession, history):
    """Run the Groq cascade: try each model in order, return the first good reply (or None)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    for model in GROQ_MODELS:
        try:
            async with session.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 700},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status != 200:
                    continue  # cascade down to the next model
                data = await r.json()
                txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                if txt:
                    return txt
        except Exception:
            continue
    return None


async def build_history(channel, limit=6):
    """A little recent context so answers are coherent in a thread of messages."""
    history = []
    async for m in channel.history(limit=limit):
        if not m.content:
            continue
        role = "assistant" if m.author.id == client.user.id else "user"
        history.append({"role": role, "content": m.content[:1500]})
    history.reverse()
    return history


async def send_chunked(channel, text):
    """Discord caps messages at 2000 chars — split safely on paragraph/line boundaries."""
    while text:
        if len(text) <= 1900:
            await channel.send(text); return
        cut = text.rfind("\n", 0, 1900)
        cut = cut if cut > 800 else 1900
        await channel.send(text[:cut]); text = text[cut:].lstrip()


@client.event
async def on_ready():
    print(f"✅ RailCall bot online as {client.user} | cascade={GROQ_MODELS} | "
          f"support={sorted(SUPPORT_CHANNELS)} | deny={sorted(DENY_CHANNELS)}", flush=True)
    # Startup diagnostics: which servers am I in, and what channels can I answer in?
    if not client.guilds:
        print("   ⚠ in NO servers yet — open the OAuth invite URL and Authorize me into the RailCall server.", flush=True)
    for g in client.guilds:
        chans = [c.name for c in g.text_channels]
        watched = [c for c in chans if c.lower() in SUPPORT_CHANNELS]
        print(f"   • server '{g.name}' ({g.member_count} members) · text channels: {chans}", flush=True)
        print(f"     answers-everywhere channels present here: {watched or 'NONE (rename one to support/bot-lab, or tell me your channel name)'}", flush=True)


@client.event
async def on_member_join(member):
    ch = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL)
    if not ch:
        return
    try:
        await ch.send(
            f"Welcome aboard, {member.mention}! 👋 This is the RailCall community **and** our support "
            f"desk. Ask anything here — install, BYOK, webhooks, receipts, billing — and our assistant "
            f"(plus the team) will help. New? Start with `curl -fsSL https://railcall.ai/install.sh | bash` "
            f"and the docs at railcall.ai/docs.html."
        )
    except Exception as e:
        print("welcome error:", e, flush=True)


@client.event
async def on_message(msg):
    if msg.author.bot or not msg.guild or not msg.content:
        return
    ch_name = (getattr(msg.channel, "name", "") or "").lower()
    mentioned = client.user in msg.mentions

    # Decide whether to answer: always on @mention; always in support channels; elsewhere only if it
    # looks like a question and the channel isn't on the deny list.
    if not mentioned:
        if ch_name in DENY_CHANNELS:
            return
        if ch_name not in SUPPORT_CHANNELS and not _looks_like_question(msg.content):
            return

    loop = asyncio.get_event_loop()
    now = loop.time()
    if now - _last_reply.get(msg.channel.id, 0) < COOLDOWN_S:
        return
    _last_reply[msg.channel.id] = now

    history = await build_history(msg.channel)
    async with aiohttp.ClientSession() as session:
        async with msg.channel.typing():
            answer = await groq_answer(session, history)

    if not answer:
        answer = ("I couldn't reach the assistant just now — a team member will follow up. "
                  "Meanwhile, the docs at railcall.ai/docs.html cover most setup questions.")

    # Loop in a human when the user clearly needs one (or asked for it).
    if ESCALATE_MENTION and ESCALATE_PATTERNS.search(msg.content):
        answer += f"\n\n— flagging {ESCALATE_MENTION} so a human can jump in on this. 🛟"

    try:
        await send_chunked(msg.channel, answer)
        print(f"💬 answered {msg.author} in #{ch_name}: {msg.content[:80]!r}", flush=True)
    except Exception as e:
        print("send error:", e, flush=True)


def main():
    missing = [n for n, v in (("DISCORD_BOT_TOKEN", TOKEN), ("GROQ_API_KEY", GROQ_API_KEY)) if not v]
    if missing:
        sys.exit("Set these env vars first: " + ", ".join(missing) + "  (see the header of this file).")

    async def runner():
        # Render (and most container hosts) send SIGTERM on deploy/restart. Trap it (and SIGINT for local)
        # so we close the Discord gateway cleanly — logging out without dropping a reply mid-send.
        loop = asyncio.get_running_loop()
        for _sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(_sig, lambda: asyncio.create_task(client.close()))
            except (NotImplementedError, RuntimeError):
                pass  # not all platforms support signal handlers (e.g. Windows) — degrade gracefully
        async with client:                 # `async with` guarantees client.close() runs on any exit
            await client.start(TOKEN)

    try:
        asyncio.run(runner())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    print("RailCall bot shut down cleanly.", flush=True)


if __name__ == "__main__":
    main()
