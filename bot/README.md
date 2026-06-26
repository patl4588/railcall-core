# RailCall community & support bot

Runs the RailCall Discord automatically: answers questions in any/all channels through the **Groq
cascade** (never Anthropic), welcomes new members, and pings a human when someone needs one. Local-first
— it runs on your own machine/server and talks only to Discord + Groq.

## 1. Create the bot + token (you — needs your Discord login)
1. https://discord.com/developers/applications → **New Application** → name it `RailCall`.
2. **Bot** tab → **Reset Token** → copy it. This is a SECRET — keep it, never commit it.
3. Same page → **Privileged Gateway Intents** → turn **ON**: `MESSAGE CONTENT INTENT` and `SERVER MEMBERS INTENT` → Save.

## 2. Invite it to the server
1. **OAuth2 → URL Generator** → scopes: **`bot`**.
2. Bot permissions: **View Channels**, **Send Messages**, **Read Message History**.
3. Open the generated URL → add it to the **RailCall** server.

## 3. Run it (on your 128GB server)
```bash
python3 -m pip install -U -r bot/requirements.txt
export DISCORD_BOT_TOKEN="paste-the-token-from-step-1"
export GROQ_API_KEY="your-existing-groq-key"
export ESCALATE_MENTION="<@YOUR_DISCORD_USER_ID>"     # optional — who gets pinged on escalation
python3 bot/railcall_community_bot.py
```
You should see `✅ RailCall bot online as RailCall#1234`. Post a question in **#support** to test.

## 4. Keep it alive (macOS launchd)
Save as `~/Library/LaunchAgents/ai.railcall.bot.plist`, then `launchctl load` it. Put your secrets in the
`EnvironmentVariables` block (this plist is private to your machine — don't commit it):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.railcall.bot</string>
  <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/python3</string>
      <string>/Users/patricklinden/railcall-core-clean/bot/railcall_community_bot.py</string>
    </array>
  <key>EnvironmentVariables</key><dict>
    <key>DISCORD_BOT_TOKEN</key><string>•••</string>
    <key>GROQ_API_KEY</key><string>•••</string>
    <key>ESCALATE_MENTION</key><string>&lt;@YOUR_DISCORD_USER_ID&gt;</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/railcall-bot.log</string>
  <key>StandardErrorPath</key><string>/tmp/railcall-bot.err</string>
</dict></plist>
```
```bash
launchctl load  ~/Library/LaunchAgents/ai.railcall.bot.plist     # start (and on every login)
launchctl unload ~/Library/LaunchAgents/ai.railcall.bot.plist    # stop
tail -f /tmp/railcall-bot.log                                    # watch it
```
(On a Linux server, run it under `systemd` with the same env vars in the unit's `[Service] Environment=`.)

## Behavior / tuning (env vars)
| Var | Default | What it does |
|-----|---------|--------------|
| `DISCORD_BOT_TOKEN` | — (required) | Bot token from step 1 |
| `GROQ_API_KEY` | — (required) | Your Groq key (the cascade's inference) |
| `GROQ_MODELS` | `llama-3.3-70b-versatile,llama-3.1-8b-instant` | Cascade order: capable first, fast fallback |
| `SUPPORT_CHANNELS` | `support,bot-lab` | Channels where it answers **every** message |
| `DENY_CHANNELS` | `announcements,mod-log,changelog,welcome` | One-way channels it won't auto-answer (still replies to @mentions) |
| `WELCOME_CHANNEL` | `welcome` | Where new-member welcomes post |
| `ESCALATE_MENTION` | (none) | Who to ping on billing/refund/account/"talk to a human" |
| `COOLDOWN_S` | `3` | Min seconds between replies per channel (anti-flood) |

Elsewhere (non-support channels) it only chimes in on an **@mention** or a question-shaped message, so it
helps without spamming casual chat. Nothing secret is hard-coded — all secrets come from the environment.
