# RailCall Community & Support — the omnichannel engine

The whole support system runs on **your own machine, on Groq, local-first** — no third-party helpdesk,
no cloud data-sink ingesting customer messages. That's the opposite of Fin/Zendesk/Intercom, and it's
the point: even our support runs on the same governed, local rails as the product.

## Architecture (one brain, many doors)
```
  Acquisition (AI reply bots + content)  ──►  Discord (community + support hub)
                                                 │
                railcall_support_brain.py  ◄──────┤  (grounding + intent + Groq cascade + handoff)
                 │            │                    │
        Discord adapter   Telegram adapter    web widget (later)
  railcall_community_bot  railcall_telegram_bot
                 │
        Human community managers  ◄── tickets (threads) + full-context handoff
```

- **`railcall_support_brain.py`** — the shared, channel-agnostic core. Grounded answers (from
  `railcall_kb.md` + canonical facts), intent detection (greeting / question / needs-human), the Groq
  cascade (stdlib, never Anthropic), and one-line handoff summaries. Both adapters import it verbatim.
- **`railcall_community_bot.py`** — Discord. Answers in support channels + on @mention/question/greeting.
  Escalations open a **ticket thread**, ping the CM, and post a handoff summary. **LIVE** (launchd
  `com.railcall.discord-bot`, logs to `~/.railcall/bot.log`).
- **`railcall_telegram_bot.py`** — Telegram, same brain. **DORMANT until you add a token** (below).
- **`railcall_kb.md`** — the editable knowledge base. The bot hot-reloads it on save (no restart). This
  is where CMs add answers as new questions come up. UNKNOWN ≠ PASS — if it's not in here, the bot says
  "not sure, a human will confirm" instead of guessing.
- **`railcall_support_stats.py`** — local analytics: `python3 bot/railcall_support_stats.py` prints
  deflection rate, ticket count, busiest channels, and the top topics to add to the KB.

## Who does what (the AI-run model)
- **AI (the brain):** tier-1 answers, routing, greeting, drafting the ticket summary — 24/7, instant.
- **Human community managers:** own the ticket threads, billing/refund/account/security escalations, the
  vibe, events, and spotlighting members. The AI hands them a summarized thread so they never start cold.

---

## ✅ Your provisioning checklist (the only steps I can't do — accounts/credentials/legal clicks)

**1. Telegram — bring the bot online (~2 min).** *Only you can create the bot account.*
   - In Telegram, message **@BotFather** → `/newbot` → name it `RailCall` → copy the token it gives you.
   - Drop the token in a 0600 file (paste it in *your* terminal — never in chat):
     ```
     umask 177 && printf '%s' 'PASTE_YOUR_TELEGRAM_TOKEN' > ~/.railcall/telegram_token
     ```
   - (optional) get your admin chat id for escalations: message @userinfobot, then
     `export TELEGRAM_ESCALATE_CHAT="<that id>"`.
   - Start it: `python3 ~/railcall-core-clean/bot/railcall_telegram_bot.py`  (or add a launchd plist — copy
     `com.railcall.discord-bot.plist`, swap the script path to `railcall_telegram_bot.py`, `launchctl load` it).
   - Verify: message your bot on Telegram — it should answer from the same brain as Discord.

**2. Discord "Community" mode — the real front door (~3 min).** *Requires accepting Discord's community
   agreement, which is yours to click.* Server Settings → **Enable Community** → walk the wizard:
   - Rules channel = **#welcome**; updates channel = **#announcements**.
   - Turn on **Onboarding** → add 2–3 questions (e.g. "What are you building?") → auto-assign a role.
   - Set **Verification Level = Medium** and enable **AutoMod** (spam + raid protection) — do this before
     you drive traffic; bot-raids are the real risk once the reply bots start working.

**3. Appoint your human CM(s).** Create a **Community Manager** role, assign Kyle/Nick, then point the bot
   at it so tickets ping the role instead of you personally:
   ```
   # add to the launchd plist's EnvironmentVariables, then relaunch:
   CM_ROLE_MENTION = "<@&THE_CM_ROLE_ID>"   # right-click the role → Copy ID (needs Developer Mode on)
   ```

**4. (recommended) Consolidate channels 12 → ~7.** A 4-member server with 12 channels reads as a ghost
   town. Keep welcome/announcements/general/support/showcase/feedback (+changelog as a webhook feed); make
   command-center/mod-log/bot-lab **private** (admin-only). This one's destructive (deletes/hides), so it's
   your call — say the word and I'll do it.

---

## Config reference (env or launchd plist)
| Var | Default | Meaning |
|---|---|---|
| `DISCORD_BOT_TOKEN` / `~/.railcall/bot_token` | — | Discord bot token |
| `GROQ_API_KEY` / `~/.railcall/groq_key` | — | Groq key (shared by all adapters) |
| `TELEGRAM_BOT_TOKEN` / `~/.railcall/telegram_token` | — | Telegram token (dormant until set) |
| `SUPPORT_CHANNELS` | `support,bot-lab` | channels the bot answers *every* message in |
| `DENY_CHANNELS` | `announcements,mod-log,changelog,welcome` | channels it stays out of |
| `CM_ROLE_MENTION` | (falls back to `ESCALATE_MENTION`) | who gets pinged on a ticket |
| `RAILCALL_KB` | `bot/railcall_kb.md` | knowledge-base file (hot-reloaded) |
| `GROQ_MODELS` | `llama-3.3-70b-versatile,llama-3.1-8b-instant` | cascade order |

## Deploy / restart the Discord bot after any change
```
launchctl kickstart -k gui/$(id -u)/com.railcall.discord-bot
tail -f ~/.railcall/bot.log          # watch it come online (look for "kb=loaded")
```
