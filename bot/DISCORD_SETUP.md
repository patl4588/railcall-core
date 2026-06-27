# RailCall Discord — Community + Support Hub setup (for Nick)

Zero-overhead, self-cleaning technical support. Customers help themselves via searchable threads;
the AI bot answers the rest. Support is **100% Discord — no email queue.**

- **Live invite:** https://discord.gg/D2EYGjFBD  (the site routes `railcall.ai/discord` → this)
- **AI responder bot:** `bot/railcall_community_bot.py` (Groq cascade, never Anthropic). Built — needs
  Pat's bot token to run (`~/.railcall/bot_token` or `DISCORD_BOT_TOKEN` env; Groq key likewise).

---

## 1 · Channel architecture

| Channel | Type | Purpose |
|---------|------|---------|
| `#📢│announcements` | Announcement | Releases + system status. Read-only for members. |
| `#📖│docs-updates` | Text | Auto-log when a solved thread is promoted into the master docs. |
| `#🔧│support-forum` | **Forum** | The core hub. Members can't post open chat — they open a unique, searchable **thread** per issue. |
| `#💬│general` | Text | Community chatter (optional). |

Keep `#support-forum` a **Forum Channel** specifically — it forces one searchable thread per problem
and makes the whole server a self-serve technical database.

## 2 · `#support-forum` thread tags (mandatory, pre-configured)

Every new thread must pick exactly one:

- `[CLI]` — install/`curl` errors, terminal/syntax, `railcall login`/`balance`.
- `[Studio-UI]` — local Studio (127.0.0.1:8799) rendering / workspace issues.
- `[Airlock-Halt]` — the engine blocked a stray socket or off-schema payload; help adjusting the input contract.
- `[Billing-Ledger]` — Stripe top-ups, balance/flow-count sync, receipts.
- `[Connectors]` — wiring a BYOK connector / env var / adapter.

## 3 · Onboarding gate (members agree before write access)

> **Before you post:**
> 1. **Search first.** Check solved/closed threads (filter by tag) before opening a new one.
> 2. **Never paste keys or data.** RailCall is local-first — we *can't* see your code and we don't want to.
>    No live keys, client schemas, or raw PII in this server.
> 3. **Keep it technical.** Paste the structural receipt (`sha256:…`) and the terminal error. No fluff.

## 4 · The AI responder bot

`bot/railcall_community_bot.py` watches the channels and answers common questions from the Groq cascade,
grounded in the docs. To run it:

```bash
# Pat: drop your Discord bot token + a Groq key, then:
echo "YOUR_DISCORD_BOT_TOKEN" > ~/.railcall/bot_token
echo "YOUR_GROQ_KEY"          > ~/.railcall/groq_key
python3 bot/railcall_community_bot.py
```

It only reads/answers — it never asks for or handles customer keys (reinforces rule #2 above).

---

_Support model: Discord-only, AI-first, thread-based. The `#support-forum` becomes the searchable
knowledge base; good answers get promoted into the docs (logged in `#docs-updates`)._
