#!/usr/bin/env python3
"""
RailCall community & support bot — the DISCORD adapter over the shared support brain.

What it does:
  • Answers in support channels (every message) and elsewhere on an @mention, a question, OR a greeting
    (so a newcomer who just says "hi" gets a warm reply instead of silence).
  • Generates GROUNDED replies through railcall_support_brain (Groq cascade, never Anthropic), so answers
    come from RailCall's facts + the editable KB — and say "not sure, a human will confirm" when unsure.
  • Opens a TICKET THREAD and pings the Community-Manager role on anything that needs a human (billing,
    refunds, account, bugs, security, "talk to a human") — with a one-line handoff summary so the CM
    never starts cold. Tickets are tracked, not lost in the channel scroll.
  • Welcomes new members.

Local-first: runs on your own machine, talks only to Discord + Groq. No data sink.

────────────────────────────────────────────────────────────────────────────
SETUP: see bot/OMNICHANNEL.md . TL;DR — Developer Portal → enable MESSAGE CONTENT + SERVER MEMBERS
intents; drop DISCORD_BOT_TOKEN + GROQ_API_KEY (env or ~/.railcall/{bot_token,groq_key}); run under launchd.
Optional: CM_ROLE_MENTION="<@&ROLE_ID>" (who gets pinged on escalations) and TICKETS_CHANNEL="tickets".
────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
import signal
import asyncio

try:
    import discord
except ImportError:
    sys.exit("Missing dependency. Run: python3 -m pip install -U discord.py aiohttp")

# Shared, channel-agnostic brain (grounding, intent, Groq cascade, handoff summary).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_support_brain as brain

TOKEN = brain._secret("DISCORD_BOT_TOKEN", "bot_token")

# Channels the bot will NOT auto-answer in (one-way / noise). It still answers @mentions everywhere.
DENY_CHANNELS = set(c.strip().lower() for c in os.environ.get(
    "DENY_CHANNELS", "announcements,mod-log,changelog,welcome").split(",") if c.strip())
# Channels where the bot answers EVERY message (support-style). Others: only mentions/questions/greetings.
SUPPORT_CHANNELS = set(c.strip().lower() for c in os.environ.get(
    "SUPPORT_CHANNELS", "support,bot-lab").split(",") if c.strip())
WELCOME_CHANNEL = os.environ.get("WELCOME_CHANNEL", "welcome").strip().lower()
# Who gets pinged when a ticket opens. A role mention "<@&ID>" is best; falls back to a user "<@ID>".
CM_MENTION = os.environ.get("CM_ROLE_MENTION", os.environ.get("ESCALATE_MENTION", "")).strip()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# Per-channel cooldown so the bot can't get into a tight loop or flood a channel.
_last_reply = {}  # channel_id -> monotonic seconds
COOLDOWN_S = float(os.environ.get("COOLDOWN_S", "3"))


async def _brain_answer(history, user_text):
    """Run the (sync, stdlib) brain in a thread so we never block the Discord event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: brain.answer(history, user_text))


async def _brain_summary(history):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: brain.handoff_summary(history))


async def build_history(channel, limit=6):
    """A little recent context so answers are coherent across a thread of messages."""
    history = []
    async for m in channel.history(limit=limit):
        if not m.content:
            continue
        role = "assistant" if m.author.id == client.user.id else "user"
        history.append({"role": role, "content": m.content[:1500]})
    history.reverse()
    return history


async def send_chunked(target, text):
    """Discord caps messages at 2000 chars — split safely on line boundaries."""
    while text:
        if len(text) <= 1900:
            await target.send(text)
            return
        cut = text.rfind("\n", 0, 1900)
        cut = cut if cut > 800 else 1900
        await target.send(text[:cut])
        text = text[cut:].lstrip()


async def open_ticket(msg, answer_text, history):
    """Escalation path: open a tracked TICKET THREAD off the user's message, post the assistant's answer +
    a one-line handoff summary, and ping the Community-Manager role so a human picks it up with full context."""
    summary = await _brain_summary(history)
    try:
        thread = await msg.create_thread(name=("ticket · " + (msg.content[:40] or "support"))[:90],
                                         auto_archive_duration=1440)
    except Exception:
        thread = msg.channel  # threads unavailable (perms/DM) — fall back to the channel, still escalate
    await send_chunked(thread, answer_text)
    ping = (CM_MENTION + " ") if CM_MENTION else ""
    await thread.send(
        f"{ping}🎫 **Ticket opened** for {msg.author.mention}\n"
        f"**Summary:** {summary}\n"
        f"A teammate will follow up here. (Assistant already replied above.)")
    ch = getattr(msg.channel, "name", "?")
    print(f"🎫 ticket opened for {msg.author} in #{ch}: {summary[:120]!r}", flush=True)
    brain.log_event("ticket", user=str(msg.author), channel=ch, summary=summary[:240])


@client.event
async def on_ready():
    print(f"✅ RailCall bot online as {client.user} | cascade={brain.GROQ_MODELS} | "
          f"support={sorted(SUPPORT_CHANNELS)} | deny={sorted(DENY_CHANNELS)} | "
          f"cm={CM_MENTION or 'off'} | kb={'loaded' if brain.load_kb().strip() else 'empty'}", flush=True)
    if not client.guilds:
        print("   ⚠ in NO servers yet — open the OAuth invite URL and Authorize me into the RailCall server.", flush=True)
    for g in client.guilds:
        chans = [c.name for c in g.text_channels]
        watched = [c for c in chans if c.lower() in SUPPORT_CHANNELS]
        print(f"   • server '{g.name}' ({g.member_count} members) · answers-everywhere: {watched or 'NONE'}", flush=True)


@client.event
async def on_member_join(member):
    ch = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL)
    if not ch:
        return
    try:
        await ch.send(
            f"Welcome aboard, {member.mention}! 👋 This is the RailCall community **and** our support desk. "
            f"Ask anything here — install, BYOK, webhooks, receipts, billing — and the assistant (plus the "
            f"team) will help. New? `curl -fsSL https://railcall.ai/install.sh | bash` and the docs at "
            f"railcall.ai/docs.html.")
    except Exception as e:
        print("welcome error:", e, flush=True)


@client.event
async def on_message(msg):
    if msg.author.bot or not msg.guild or not msg.content:
        return
    ch_name = (getattr(msg.channel, "name", "") or "").lower()
    mentioned = client.user in msg.mentions
    text = msg.content

    # Decide whether to answer: always on @mention; always in support channels; elsewhere if it looks like
    # a question OR a greeting (so "hi" gets a warm reply). Never in deny channels unless mentioned.
    if not mentioned:
        if ch_name in DENY_CHANNELS:
            return
        if ch_name not in SUPPORT_CHANNELS and not brain.is_question(text) and not brain.is_greeting(text):
            return

    loop = asyncio.get_event_loop()
    now = loop.time()
    if now - _last_reply.get(msg.channel.id, 0) < COOLDOWN_S:
        return
    _last_reply[msg.channel.id] = now

    history = await build_history(msg.channel)
    async with msg.channel.typing():
        answer = await _brain_answer(history, text)
    if not answer:
        answer = brain.FALLBACK

    # Needs a human? Open a tracked ticket thread with a handoff summary + CM ping (greetings never escalate).
    if brain.wants_human(text) and not brain.is_greeting(text):
        try:
            await open_ticket(msg, answer, history)
        except Exception as e:
            print("ticket error:", e, flush=True)
            brain.log_event("error", where="ticket", channel=ch_name, err=str(e))
            try:
                await send_chunked(msg.channel, answer)
            except Exception:
                pass
        return

    try:
        await send_chunked(msg.channel, answer)
        print(f"💬 answered {msg.author} in #{ch_name}: {text[:80]!r}", flush=True)
        brain.log_event("answered", user=str(msg.author), channel=ch_name, chars=len(answer))
    except Exception as e:
        print("send error:", e, flush=True)
        brain.log_event("error", where="send", channel=ch_name, err=str(e))


def main():
    if not TOKEN:
        sys.exit("Set DISCORD_BOT_TOKEN (env or ~/.railcall/bot_token). See bot/OMNICHANNEL.md.")
    if not brain.GROQ_API_KEY:
        sys.exit("Set GROQ_API_KEY (env or ~/.railcall/groq_key). See bot/OMNICHANNEL.md.")

    async def runner():
        loop = asyncio.get_running_loop()
        for _sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(_sig, lambda: asyncio.create_task(client.close()))
            except (NotImplementedError, RuntimeError):
                pass
        async with client:
            await client.start(TOKEN)

    try:
        asyncio.run(runner())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    print("RailCall bot shut down cleanly.", flush=True)


if __name__ == "__main__":
    main()
