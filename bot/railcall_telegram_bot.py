#!/usr/bin/env python3
"""
RailCall support — the TELEGRAM adapter over the same shared brain as Discord.

One brain, another door. Grounded answers, greeting handling, and human escalation, identical to
Discord — because it imports railcall_support_brain verbatim. Stdlib only (urllib long-polling of the
Telegram Bot API); no python-telegram-bot dependency, on-brand with the local/deterministic ethos.

DORMANT until you provision a token (this is the one step only you can do — creating the bot account):
  1. In Telegram, message @BotFather → /newbot → name it "RailCall" → copy the token it gives you.
  2. Drop the token in a 0600 file (nothing secret is pasted into chat or handled by anyone else):
       umask 177 && printf '%s' 'PASTE_TOKEN_HERE' > ~/.railcall/telegram_token
  3. (optional) Set an admin chat to receive escalations: export TELEGRAM_ESCALATE_CHAT="<your_chat_id>"
  4. Run it (launchd plist alongside the Discord bot):  python3 bot/railcall_telegram_bot.py
Until step 2 exists, this process prints a notice and exits 0 — the Discord bot is unaffected.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_support_brain as brain

TOKEN = brain._secret("TELEGRAM_BOT_TOKEN", "telegram_token")
API = "https://api.telegram.org/bot%s/%s"
ESCALATE_CHAT = os.environ.get("TELEGRAM_ESCALATE_CHAT", "").strip()
POLL_TIMEOUT = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "50"))

# Tiny per-chat rolling history so answers stay coherent in a back-and-forth.
_history = {}   # chat_id -> [ {role, content}, ... ] (kept short)
_HIST_MAX = 6


def _api(method, params, timeout=60):
    url = API % (TOKEN, method)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(chat_id, text):
    # Telegram caps at 4096 chars; chunk on newline boundaries.
    while text:
        chunk = text if len(text) <= 3800 else text[:text.rfind("\n", 0, 3800) or 3800]
        try:
            _api("sendMessage", {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"})
        except Exception as e:
            print("send error:", e, flush=True)
            return
        text = text[len(chunk):].lstrip()


def handle(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return
    user = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name") or chat_id

    hist = _history.setdefault(chat_id, [])
    hist.append({"role": "user", "content": text[:1500]})
    del hist[:-_HIST_MAX]

    reply = brain.answer(hist, text) or brain.FALLBACK
    hist.append({"role": "assistant", "content": reply[:1500]})
    del hist[:-_HIST_MAX]

    # Human escalation: notify the admin chat with a one-line summary; tell the user a teammate will follow up.
    if brain.wants_human(text) and not brain.is_greeting(text):
        summary = brain.handoff_summary(hist)
        if ESCALATE_CHAT:
            try:
                send(ESCALATE_CHAT, f"🎫 Telegram ticket from @{user} (chat {chat_id}):\n{summary}")
            except Exception:
                pass
        reply += "\n\n— I've flagged this for a human teammate; they'll follow up here. 🛟"
        print(f"🎫 telegram ticket from {user}: {summary[:120]!r}", flush=True)
    else:
        print(f"💬 telegram answered {user}: {text[:80]!r}", flush=True)

    send(chat_id, reply)


def main():
    if not TOKEN:
        print("Telegram adapter DORMANT — no token yet. Add ~/.railcall/telegram_token (see this file's header). "
              "Exiting cleanly; the Discord bot is unaffected.", flush=True)
        return
    if not brain.GROQ_API_KEY:
        sys.exit("Set GROQ_API_KEY (env or ~/.railcall/groq_key).")
    me = _api("getMe", {}).get("result", {})
    print(f"✅ RailCall Telegram bot online as @{me.get('username','?')} | cascade={brain.GROQ_MODELS} | "
          f"escalate_chat={ESCALATE_CHAT or 'off'}", flush=True)

    offset = 0
    while True:
        try:
            resp = _api("getUpdates", {"offset": offset, "timeout": POLL_TIMEOUT},
                        timeout=POLL_TIMEOUT + 15)
        except Exception as e:
            print("poll error:", e, flush=True)
            time.sleep(3)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            m = upd.get("message") or upd.get("edited_message")
            if m and m.get("text"):
                try:
                    handle(m)
                except Exception as e:
                    print("handle error:", e, flush=True)


if __name__ == "__main__":
    main()
