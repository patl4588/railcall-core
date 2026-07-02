#!/usr/bin/env python3
"""
RailCall support WATCHDOG — enterprise reliability for the Discord bot.

launchd already restarts the process if it *crashes*, but it can't tell you the bot is down, and it
won't catch the nastier failure: process alive but the Discord gateway dropped (answers silently stop).
This watchdog checks BOTH — process present AND at least one established TCP connection — and if the bot
is unhealthy it (1) alerts the team via the Discord webhook and (2) force-restarts the launchd job.

Run it on a timer (com.railcall.support-watchdog, every 5 min). Stdlib only. Success is quiet (a
heartbeat event only) so it never spams the channel.

Manual run:  python3 bot/railcall_watchdog.py
"""
import os
import json
import time
import subprocess
import urllib.request

JOB = "com.railcall.discord-bot"
PROC = "railcall_community_bot"
WEBHOOK_FILE = os.path.expanduser("~/.railcall/discord_webhook_general.url")
EVENTS = os.environ.get("RAILCALL_EVENTS", os.path.expanduser("~/.railcall/support_events.jsonl"))


def _run(args, timeout=12):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def pids():
    return [p for p in _run(["pgrep", "-f", PROC]).split() if p]


def established(pid):
    """Count established outbound TCP connections for a pid (the Discord gateway is one of them)."""
    out = _run(["lsof", "-p", pid, "-a", "-iTCP", "-sTCP:ESTABLISHED"])
    return sum(1 for ln in out.splitlines() if "ESTABLISHED" in ln)


def event(kind, **fields):
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind}
        rec.update(fields)
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def alert(msg):
    try:
        url = open(WEBHOOK_FILE).read().strip()
    except Exception:
        return
    body = json.dumps({"username": "RailCall · Watchdog", "content": "⚠️ " + msg}).encode()
    try:
        req = urllib.request.Request(
            url + "?wait=true", data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "RailCallWatchdog/1.0 (+https://railcall.ai)"})
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def restart():
    _run(["launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), JOB)], timeout=25)


def main():
    ps = pids()
    healthy = bool(ps) and any(established(p) > 0 for p in ps)
    if healthy:
        event("watchdog_ok", pids=ps)
        print("OK: support bot alive + connected", ps)
        return
    reason = "no process" if not ps else "process up but no Discord connection"
    print("DOWN:", reason)
    event("watchdog_down", reason=reason, pids=ps)
    alert("Support bot is DOWN (%s) — auto-restarting via launchd." % reason)
    restart()


if __name__ == "__main__":
    main()
