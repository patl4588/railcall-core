#!/usr/bin/env python3
"""
RailCall support analytics — LOCAL. Parses ~/.railcall/bot.log and prints a plain-text dashboard:
answers, tickets/escalations, deflection rate, and the busiest topics. No third-party analytics SaaS —
your community data stays on your machine, same as the product promises.

Usage:  python3 bot/railcall_support_stats.py [path/to/bot.log]
Wire it to a cron/launchd to post a weekly digest into #command-center if you like.
"""
import os
import re
import sys
from collections import Counter

LOG = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.railcall/bot.log")

ANSWERED = re.compile(r"answered .*? in #(?P<ch>[\w-]+): '(?P<q>.*)'")
TICKET = re.compile(r"ticket opened for .*?: '(?P<s>.*)'")
ONLINE = re.compile(r"bot online as")

STOP = set("the a an is are do does how what why can i to in of my me you it and or for on with your this "
           "railcall help me? use using not get do i can you".split())


def main():
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        sys.exit(f"No log at {LOG}. Is the bot running? (launchctl list | grep railcall)")

    answered, tickets, restarts = 0, 0, 0
    channels, words, questions = Counter(), Counter(), []
    for ln in lines:
        if ONLINE.search(ln):
            restarts += 1
        mt = TICKET.search(ln)
        if mt:
            tickets += 1
            continue
        ma = ANSWERED.search(ln)
        if ma:
            answered += 1
            channels[ma.group("ch")] += 1
            q = ma.group("q")
            questions.append(q)
            for w in re.findall(r"[a-z][a-z'-]{2,}", q.lower()):
                if w not in STOP:
                    words[w] += 1

    total = answered + tickets
    deflection = (answered / total * 100) if total else 0.0

    print("─" * 56)
    print("  RailCall support — local dashboard")
    print("─" * 56)
    print(f"  Answered by AI ....... {answered}")
    print(f"  Tickets (→ human) .... {tickets}")
    print(f"  AI deflection rate ... {deflection:4.1f}%   (answered / all handled)")
    print(f"  Bot (re)connects ..... {restarts}")
    print()
    print("  Busiest channels:")
    for ch, n in channels.most_common(6):
        print(f"    #{ch:<16} {n}")
    print()
    print("  Top topics (feed these into railcall_kb.md):")
    for w, n in words.most_common(12):
        print(f"    {w:<18} {n}")
    print("─" * 56)


if __name__ == "__main__":
    main()
