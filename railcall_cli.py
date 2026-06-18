#!/usr/bin/env python3
"""railcall — unified local CLI/TUI over the verified companion daemon.

A thin terminal front-end that REUSES the verified logic in railcall_companion_daemon.py.
Importing that module only loads its functions (its main() is guarded by __main__), so
nothing starts on import. This CLI does NOT touch mcp_server.py — that stays a pure stdio
JSON-RPC MCP server for Claude Desktop / Cursor.

No fake wallets, balances, or tolls. Every number printed here is measured: real CSV
compile, recursive child-PID socket audits (lsof), local Ollama (loopback), real receipts.

  railcall                         dashboard: workspace + daemon/model status + commands
  railcall build [path/to.csv]     local CSV compile + recursive socket audit + receipt
  railcall interpret "<prompt>"    local NL pass via Ollama, airlock-proven
  railcall daemon                  start the loopback companion daemon (127.0.0.1:8555)
  railcall health                  daemon reachability + a socket audit of this process
"""
import sys
import os
import json
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_companion_daemon as d  # loads functions only; main() is __main__-guarded

# --- Day-1 free tier: client-side only, no network call ---
# install.sh writes ~/.config/railcall/token.json with 100 free runs.
# cmd_build reads + decrements it atomically; hard-blocks at 0.
TOKEN_PATH = os.path.join(os.path.expanduser("~"), ".config", "railcall", "token.json")
TRIAL_EXHAUSTED_MSG = "Trial exhausted. Live billing portal launching soon."


def read_token():
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def write_token(token):
    """Atomic write: temp file + rename so a crash mid-write can't corrupt token.json."""
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)
        f.write("\n")
    os.replace(tmp, TOKEN_PATH)


_COL = {
    "cyan": "\033[38;5;81m", "green": "\033[38;5;84m", "amber": "\033[38;5;215m",
    "red": "\033[38;5;196m", "slate": "\033[38;5;244m", "purple": "\033[38;5;141m",
    "bold": "\033[1m", "reset": "\033[0m",
}
_TTY = sys.stdout.isatty()
def c(s, col):
    return f"{_COL[col]}{s}{_COL['reset']}" if _TTY else str(s)


def _probe(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode() == 200
    except Exception:
        return False

def daemon_online():
    return _probe(f"http://{d.HOST}:{d.PORT}/health")

def ollama_online():
    return _probe(d.OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags")


def load_contract():
    p = os.path.join(d.ROOT, "library", "input_contract.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return dict(d.DEFAULT_CONTRACT)


def print_table(records):
    if not records:
        print(c("  (no rows passed compilation)", "slate")); return
    cols = ["metric_id", "component", "load_value", "status"]
    w = {k: max(len(k), *(len(str(r.get(k, ""))) for r in records)) for k in cols}
    print("  " + "  ".join(c(k.ljust(w[k]), "slate") for k in cols))
    for r in records:
        print("  " + "  ".join(str(r.get(k, "")).ljust(w[k]) for k in cols))


def cmd_dashboard(_=None):
    don, oon = daemon_online(), ollama_online()
    print(c("┌────────────────────────────────────────────────────────────┐", "purple"))
    print(c("│   RAILCALL — local companion CLI                             │", "purple"))
    print(c("└────────────────────────────────────────────────────────────┘", "purple"))
    print(f"  {c('workspace', 'bold')}: {d.ROOT}")
    print(f"  {c('daemon', 'bold')}:    " + (c(f"online ({d.HOST}:{d.PORT})", "green") if don
                                             else c("offline — start with: railcall daemon", "amber")))
    print(f"  {c('model', 'bold')}:     " + (c(f"{d.OLLAMA_MODEL} (local Ollama)", "green") if oon
                                             else c("Ollama not reachable on :11434", "amber")))
    print(c("  ────────────────────────────────────────────────────────────", "slate"))
    print(c("  commands:", "green"))
    print('    railcall build [csv]            local compile + socket audit + receipt')
    print('    railcall interpret "<prompt>"   local NL pass (Ollama), airlock-proven')
    print('    railcall daemon                 start loopback daemon on 127.0.0.1:8555')
    print('    railcall health                 daemon + socket-audit status')
    print(c("  no fake balances or wallets — every number here is measured.", "slate"))
    return 0


def cmd_build(args):
    # Free-tier guard: read ~/.config/railcall/token.json BEFORE running a compile.
    # Hard-block at 0 runs; install.sh re-runs only refresh an EXISTING token, never reset it.
    token = read_token()
    if token is None:
        print(c("Free-tier token not found at " + TOKEN_PATH, "amber"))
        print(c("Run the installer to enroll:  curl -sL https://railcall.ai/install.sh | bash", "slate"))
        return 1
    runs_left = token.get("runs_remaining")
    if not isinstance(runs_left, int) or runs_left <= 0:
        print(c(TRIAL_EXHAUSTED_MSG, "red"))
        return 1

    csv_path = args[0] if args else os.path.join(d.ROOT, "fixtures", "metrics.csv")
    if os.path.exists(csv_path):
        csv_data, src = open(csv_path, encoding="utf-8").read(), csv_path
    else:
        csv_data = ("metric_id,component,load_value,status\n"
                    "M-101,generator-alpha,87.4,active\n"
                    "M-102,turbine-beta,12.1,idle\n"
                    "M-103,coolant-main,55.2,active\n")
        src = f"built-in sample (no file at {csv_path})"
    contract = load_contract()
    print(c("RAILCALL — local compile", "cyan"))
    print(f"  source:  {src}")
    result = d.compile_csv(csv_data, contract, strict=True)
    receipt = d.write_receipt(csv_data, result, strict=True)
    if not result.get("ok"):
        print(c(f"  ✗ BLOCKED: {result.get('error')} {result.get('violations') or ''}", "red"))
    else:
        print(c(f"  ✓ compiled {len(result['records'])} rows -> tables/power-grid", "green"))
        print_table(result["records"])
    audit = receipt["network_audit"]
    ext = audit.get("external_sockets_open")
    print(c(f"  airlock: {ext} external sockets (lsof over pids {audit.get('audited_pids')})",
            "green" if ext == 0 else "red"))
    print(c(f"  receipt: {d.RECEIPT_PATH}", "slate"))

    # Decrement free tier only on a successful compile.
    if result.get("ok"):
        token["runs_remaining"] = runs_left - 1
        write_token(token)
        new_left = token["runs_remaining"]
        msg = f"  free tier: {new_left} run{'s' if new_left != 1 else ''} remaining"
        print(c(msg, "green" if new_left > 10 else "amber"))

    return 0 if result.get("ok") else 1


def cmd_interpret(args):
    if not args:
        print(c('usage: railcall interpret "<prompt>"', "amber")); return 1
    if not ollama_online():
        print(c("  Ollama not reachable on localhost:11434 — start it first.", "amber")); return 1
    prompt = " ".join(args)
    print(c("RAILCALL — local NL interpret", "cyan"))
    print(f"  model:   {d.OLLAMA_MODEL}  ({d.OLLAMA_URL})")
    res = d.interpret_nl(prompt, None, num_predict=256)
    a = res["airlock"]
    ext = a.get("during_call_external_sockets")
    print(c(f"  airlock: {ext} external sockets during call · ollama socket {a.get('ollama_loopback_socket_observed')}",
            "green" if ext == 0 else "red"))
    if res.get("ollama_error"):
        print(c(f"  ollama error: {res['ollama_error']}", "red")); return 1
    print(c("  model response:", "bold"))
    print("  " + (res.get("response") or "(empty)").replace("\n", "\n  "))
    print(c(f"  receipt: {d.INTERPRET_RECEIPT_PATH}", "slate"))
    return 0


def cmd_daemon(_=None):
    if daemon_online():
        print(c(f"  daemon already running on {d.HOST}:{d.PORT}", "amber")); return 0
    try:
        d.main()  # this IS the verified daemon — starts its loopback server (blocks)
    except OSError as e:
        print(c(f"  could not bind {d.HOST}:{d.PORT}: {e}", "red")); return 1
    return 0


def cmd_health(_=None):
    print("  daemon: " + (c(f"online ({d.HOST}:{d.PORT})", "green") if daemon_online()
                          else c("offline", "amber")))
    audit = d.lsof_socket_audit()
    ext = audit.get("external_sockets_open")
    print(c(f"  this CLI process: {ext} external sockets · audited pids {audit.get('audited_pids')}",
            "green" if ext == 0 else "red"))
    return 0


COMMANDS = {"build": cmd_build, "interpret": cmd_interpret, "daemon": cmd_daemon,
            "start-daemon": cmd_daemon, "health": cmd_health, "dashboard": cmd_dashboard}


def main():
    if len(sys.argv) < 2:
        return cmd_dashboard()
    fn = COMMANDS.get(sys.argv[1])
    if not fn:
        print(c(f"unknown command: {sys.argv[1]}", "red"))
        return cmd_dashboard() or 1
    return fn(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)
