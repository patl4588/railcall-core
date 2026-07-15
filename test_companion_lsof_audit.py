#!/usr/bin/env python3
"""Regression proof for the companion daemon's network-isolation audit.

The stabilize sweep (2026-07-04) found a fake-green in lsof_socket_audit(): it called
any socket line CONTAINING '127.0.0.1' loopback, so an ESTABLISHED connection whose
LOCAL bind is 127.0.0.1 but whose FOREIGN peer is a real off-machine host read as
external_sockets_open == 0. That silently defeated the daemon's central "zero external
sockets" proof.

This feeds representative lsof NAME lines to the (now pure) parser and asserts the
external connection is COUNTED — the loopback local bind must not launder it. Pure,
deterministic, zero network, no lsof subprocess.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_companion_daemon as d  # __main__-guarded main(); import loads functions only

failures = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else "   :: " + str(detail)))
    if not cond:
        failures.append(name)


# A realistic `lsof -nP -a -p <pid> -iTCP -iUDP` blob for the daemon's own PID:
#   1) the loopback LISTEN socket
#   2) the loopback->loopback Ollama connection (127.0.0.1:11434)
#   3) the poison line: loopback LOCAL bind, but the FOREIGN peer is off-machine
LSOF_SAMPLE = """\
COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Python  12345  pat    5u  IPv4 0x1111111111111111      0t0  TCP 127.0.0.1:8555 (LISTEN)
Python  12345  pat    6u  IPv4 0x2222222222222222      0t0  TCP 127.0.0.1:54321->127.0.0.1:11434 (ESTABLISHED)
Python  12345  pat    7u  IPv4 0x3333333333333333      0t0  TCP 127.0.0.1:60123->1.2.3.4:443 (ESTABLISHED)
"""

parsed = d._parse_lsof_sockets(LSOF_SAMPLE)

# The whole point: the external peer is counted despite the 127.0.0.1 local bind.
check("external connection to non-loopback peer is COUNTED (was the fake-green)",
      parsed["external"] == 1, parsed)
check("both loopback sockets (LISTEN + loopback->loopback) are loopback",
      parsed["loopback"] == 2, parsed)
check("the external sample fingers the real off-machine peer 1.2.3.4",
      any("1.2.3.4:443" in s for s in parsed["ext_sample"]), parsed["ext_sample"])
check("the LISTEN + ollama endpoints land in the loopback sample",
      any("8555" in s for s in parsed["loop_sample"])
      and any("11434" in s for s in parsed["loop_sample"]), parsed["loop_sample"])

# Line-level classification, the three required cases stated explicitly.
lk, _ = d._classify_socket_line("Python 1 p 5u IPv4 0x0 0t0 TCP 127.0.0.1:8555 (LISTEN)")
check("LISTEN on 127.0.0.1 -> loopback", lk == "loopback", lk)
lk, _ = d._classify_socket_line("Python 1 p 6u IPv4 0x0 0t0 TCP 127.0.0.1:5->127.0.0.1:11434 (ESTABLISHED)")
check("ESTABLISHED 127.0.0.1->127.0.0.1 -> loopback", lk == "loopback", lk)
lk, _ = d._classify_socket_line("Python 1 p 7u IPv4 0x0 0t0 TCP 127.0.0.1:5->1.2.3.4:443 (ESTABLISHED)")
check("ESTABLISHED 127.0.0.1->1.2.3.4 -> external", lk == "external", lk)

# IPv6 loopback/external must classify the same way (bracketed host form).
lk, _ = d._classify_socket_line("Python 1 p 8u IPv6 0x0 0t0 TCP [::1]:5->[::1]:11434 (ESTABLISHED)")
check("ESTABLISHED [::1]->[::1] -> loopback", lk == "loopback", lk)
lk, _ = d._classify_socket_line("Python 1 p 9u IPv6 0x0 0t0 TCP [::1]:5->[2606:4700::1]:443 (ESTABLISHED)")
check("ESTABLISHED [::1]->public-v6 -> external", lk == "external", lk)

# A wildcard/all-interfaces LISTEN is reachable off-machine — must NOT be waved through.
lk, _ = d._classify_socket_line("node 1 p 3u IPv4 0x0 0t0 TCP *:8080 (LISTEN)")
check("LISTEN on *:8080 (all interfaces) -> external", lk == "external", lk)

# 127.0.0.0/8 is entirely loopback (not just 127.0.0.1).
check("127.0.0.53 is loopback", d._is_loopback_host("127.0.0.53") is True)
check("192.168.1.10 is NOT loopback", d._is_loopback_host("192.168.1.10") is False)

# Headers/blank lines are ignored, not miscounted.
kind, _ = d._classify_socket_line("COMMAND   PID USER   FD   TYPE   DEVICE SIZE/OFF NODE NAME")
check("header line ignored", kind is None, kind)
kind, _ = d._classify_socket_line("   ")
check("blank line ignored", kind is None, kind)

print()
if failures:
    print("COMPANION LSOF AUDIT: FAIL (%d) — %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("COMPANION LSOF AUDIT: PASS — external peer counted despite 127.0.0.1 local bind; "
      "loopback/IPv6/wildcard classified correctly; fake-green closed")
