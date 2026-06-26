#!/usr/bin/env python3
"""railcall — unified local CLI/TUI over the verified companion daemon.

A thin terminal front-end that REUSES the verified logic in railcall_companion_daemon.py.
Importing that module only loads its functions (its main() is guarded by __main__), so
nothing starts on import. This CLI does NOT touch mcp_server.py — that stays a pure stdio
JSON-RPC MCP server for Claude Desktop / Cursor.

No fake wallets, balances, or tolls. Every number printed here is measured: real CSV
compile, recursive child-PID socket audits (lsof), local Ollama (loopback), real receipts.

Premium TUI: pure-stdlib box-drawing + ANSI — ZERO third-party deps (no rich), so the
install stays a 2-file curl|bash and the airlock metering is never touched by rendering.

  railcall                         dashboard: workspace + daemon/model status + commands
  railcall build [path/to.csv]     local CSV compile + recursive socket audit + receipt
  railcall interpret "<prompt>"    local NL pass via Ollama, airlock-proven
  railcall daemon                  start the loopback companion daemon (127.0.0.1:8555)
  railcall health                  daemon reachability + a socket audit of this process
  railcall balance                 live run balance from the gateway
  railcall login <key>             save your rc_live_ key, then verify balance

Paid runs (a saved rc_live_ key) are booked against the server-side prepaid balance via the
gateway's /meter after each successful build/interpret; free-trial runs stay fully local.
"""
import sys
import os
import re
import json
import time
import threading
import urllib.request
import uuid
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_companion_daemon as d  # loads functions only; main() is __main__-guarded

TOKEN_PATH = os.path.join(os.path.expanduser("~"), ".config", "railcall", "token.json")
UPGRADE_URL = "https://railcall.ai/#pricing"


def read_token():
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def write_token(token):
    """Atomic write: temp file + rename so a crash mid-write can't corrupt token.json."""
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    try:
        os.chmod(os.path.dirname(TOKEN_PATH), 0o700)
    except OSError:
        pass
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)            # final file is never even briefly world-readable
    os.replace(tmp, TOKEN_PATH)
    os.chmod(TOKEN_PATH, 0o600)     # belt-and-suspenders: BYOK key file is 0600


# ----------------------------------------------------------------- TUI (stdlib only)
_COL = {
    "cyan": "\033[38;5;45m", "green": "\033[38;5;84m", "amber": "\033[38;5;215m",
    "red": "\033[38;5;203m", "slate": "\033[38;5;245m", "purple": "\033[38;5;141m",
    "dim": "\033[38;5;239m", "bold": "\033[1m", "reset": "\033[0m",
}
_TTY = sys.stdout.isatty() or os.environ.get("RAILCALL_FORCE_COLOR") == "1"
_ANSI = re.compile(r"\033\[[0-9;]*m")


def c(s, col):
    return f"{_COL[col]}{s}{_COL['reset']}" if _TTY else str(s)


def vlen(s):
    """Visible length — ANSI escape codes have zero display width."""
    return len(_ANSI.sub("", s))


def _termwidth(cap=80):
    try:
        w = os.get_terminal_size().columns
    except OSError:
        w = cap
    return max(46, min(w, cap))


def _fit(s, width):
    """Truncate a possibly-ANSI string to `width` visible chars, preserving color codes."""
    if vlen(s) <= width:
        return s
    out, vis, i = [], 0, 0
    while i < len(s) and vis < width - 1:
        m = _ANSI.match(s, i)
        if m:
            out.append(m.group()); i = m.end(); continue
        out.append(s[i]); vis += 1; i += 1
    return "".join(out) + "…" + (_COL["reset"] if _TTY else "")


def panel(lines, title="", color="cyan", width=None):
    """Rounded box (╭─╮│╰╯) around already-styled lines; title embedded in the top edge."""
    w = width or _termwidth()
    cw = w - 4
    if title:
        lbl = f"─ {title} "
        top = "╭" + lbl + "─" * max(0, w - 2 - vlen(lbl)) + "╮"
    else:
        top = "╭" + "─" * (w - 2) + "╮"
    rows = [c(top, color)]
    for ln in lines:
        ln = _fit(ln, cw)
        rows.append(c("│", color) + " " + ln + " " * max(0, cw - vlen(ln)) + " " + c("│", color))
    rows.append(c("╰" + "─" * (w - 2) + "╯", color))
    return "\n".join(rows)


def footer(ok=True, runs=None, label=None):
    """Right-aligned status bar:  [ ✓ Success │ Runs Remaining: N ]"""
    w = _termwidth()
    mark = c("✓", "green") if ok else c("✗", "red")
    state = c(label or ("Success" if ok else "Failed"), "green" if ok else "red")
    tail = ""
    if runs is not None:
        rc = "green" if (isinstance(runs, int) and runs > 10) else ("red" if runs == 0 else "amber")
        tail = c(" │ ", "dim") + c(f"Runs Remaining: {runs}", rc)
    content = c("[ ", "dim") + mark + " " + state + tail + c(" ]", "dim")
    return " " * max(0, w - vlen(content)) + content


def meter_depleted_box():
    lines = [
        c("⚠  METER DEPLETED", "red") + c("   ·   0 runs remaining", "slate"),
        "",
        c("Your free runs are used up. Top up to keep metering:", "slate"),
        c("  → " + UPGRADE_URL, "cyan"),
        c("  or restore an existing key:  railcall login <rc_live_…>", "dim"),
    ]
    return panel(lines, title="BILLING", color="red")


class Spinner:
    """Braille spinner during network/compute. Animates only on a real TTY; otherwise
    prints one static line. Pure threading — opens no sockets, so the airlock is untouched."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label):
        self.label = label
        self._stop = threading.Event()
        self._t = None

    def __enter__(self):
        if _TTY and sys.stdout.isatty():
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        else:
            sys.stdout.write("  " + self.label + "\n")
            sys.stdout.flush()
        return self

    def _run(self):
        i = 0
        while not self._stop.is_set():
            fr = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write("\r  " + _COL["cyan"] + fr + _COL["reset"] + " " + self.label + "   ")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.3)
        if _TTY and sys.stdout.isatty():
            sys.stdout.write("\r" + " " * (vlen(self.label) + 8) + "\r")
            sys.stdout.flush()


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


def _gateway():
    return os.environ.get("RAILCALL_GATEWAY_URL", "https://railcall-core.onrender.com").rstrip("/")


def _is_paid_key(api_key):
    """True only for a REAL provisioned key. The Stripe webhook mints rc_live_<uuid>; the free
    trial token carries the local sentinel rc_local_trial_100, which must NEVER touch the gateway
    (it would 401 every run and break the trial's zero-external-sockets guarantee)."""
    return isinstance(api_key, str) and api_key.startswith("rc_live_")


def _meter_run(api_key, run_count=1):
    """Book a completed metered run against the SERVER-side prepaid balance (the source of truth
    for a paid rc_live_ key). This is the ONLY thing the client sends to the gateway during work,
    and it is deliberately decoupled from the airlock-pure compile above: it runs AFTER the work
    and FAILS OPEN — a billing hiccup never fails a run the user already completed; the server
    reconciles on the next `railcall balance`. BLIND + idempotent: it sends only the key's SHA-256, a
    one-time nonce, and the action — never the raw key, never any run data — and a repeat nonce can't
    double-charge. Honors RAILCALL_METER_DRYRUN=1 (log the intent, send nothing).
    Returns (ok: bool, detail: str)."""
    nonce = uuid.uuid4().hex
    if os.environ.get("RAILCALL_METER_DRYRUN") == "1":
        return True, f"dry-run — would meter {run_count} run (nonce {nonce[:8]})"
    # BLIND meter: the gateway matches this SHA-256 against api_key_hash; the raw key never leaves here.
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    payload = json.dumps({"key_hash": key_hash, "nonce": nonce, "run_count": run_count,
                          "action": "decrement_run"}).encode("utf-8")
    req = urllib.request.Request(f"{_gateway()}/meter", data=payload, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "railcall-cli"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, f"metered {data.get('runs_recorded', run_count)} run → gateway"
    except Exception as e:  # noqa: BLE001 — billing must never crash a completed run
        code = getattr(e, "code", None)
        if code == 401:
            return False, "gateway did not recognize key (401) — run still completed"
        return False, f"meter ping failed ({code or type(e).__name__}) — run still completed"


def _server_runs(api_key):
    """The SERVER-authoritative remaining balance for a paid key — the source of truth, not the local
    accumulator. Returns an int (>= 0) on a clean read, or None if it can't be determined (not a paid
    key, a network error, or an unrecognized key). Callers gate + display on this; None means fall back
    to the local count (fail-open) so a transient blip never blocks a paying user."""
    if not _is_paid_key(api_key):
        return None
    try:
        with urllib.request.urlopen(f"{_gateway()}/v1/balance?api_key={api_key}", timeout=8) as r:
            v = json.loads(r.read().decode("utf-8")).get("runs_remaining")
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    except Exception:
        return None


def load_contract():
    p = os.path.join(d.ROOT, "library", "input_contract.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return dict(d.DEFAULT_CONTRACT)


def _table_lines(records):
    if not records:
        return [c("(no rows passed compilation)", "slate")]
    cols = ["metric_id", "component", "load_value", "status"]
    w = {k: max(len(k), *(len(str(r.get(k, ""))) for r in records)) for k in cols}
    out = [c("  ".join(k.ljust(w[k]) for k in cols), "dim")]
    for r in records:
        badge = c("active", "green") if str(r.get("status")) == "active" else c(str(r.get("status", "")), "amber")
        row = "  ".join(str(r.get(k, "")).ljust(w[k]) for k in cols[:-1])
        out.append(row + "  " + badge)
    return out


def cmd_dashboard(_=None):
    don, oon = daemon_online(), ollama_online()
    tok = read_token() or {}
    runs = tok.get("runs_remaining")
    head = [
        c("RAILCALL", "bold") + c("  ·  local companion CLI", "slate"),
        "",
        c("workspace", "dim") + "  " + str(d.ROOT),
        c("daemon   ", "dim") + "  " + (c(f"online ({d.HOST}:{d.PORT})", "green") if don
                                        else c("offline — railcall daemon", "amber")),
        c("model    ", "dim") + "  " + (c(f"{d.OLLAMA_MODEL} (local Ollama)", "green") if oon
                                        else c("Ollama not reachable on :11434", "amber")),
    ]
    print(panel(head, title="RAILCALL", color="purple"))
    cmds = [
        c("studio", "cyan") + "             open the visual Studio in your browser (127.0.0.1:8799)",
        c("build", "cyan") + c(" [csv]", "dim") + "        local compile + socket audit + receipt",
        c("interpret", "cyan") + c(' "<prompt>"', "dim") + "  local NL pass (Ollama), airlock-proven",
        c("daemon", "cyan") + "             start loopback daemon on 127.0.0.1:8555",
        c("health", "cyan") + "             daemon + socket-audit status",
        c("balance", "cyan") + "            live run balance from the gateway",
        c("login", "cyan") + c(" <key>", "dim") + "        save your rc_live_ key, then verify",
        "",
        c("no fake balances — every number here is measured.", "dim"),
    ]
    print(panel(cmds, title="commands", color="cyan"))
    print(footer(ok=True, runs=runs if isinstance(runs, int) else None, label="Ready"))
    return 0


def cmd_build(args):
    token = read_token()
    if token is None:
        print(panel([c("Free-tier token not found at", "amber"), c("  " + TOKEN_PATH, "slate"), "",
                     c("Enroll:  curl -sL https://railcall.ai/install.sh | bash", "cyan")],
                    title="RAILCALL · build", color="amber"))
        print(footer(ok=False, runs=None))
        return 1
    runs_left = token.get("runs_remaining")
    api_key = token.get("api_key")
    # Server-authoritative balance gate for PAID keys: the gateway is the source of truth, not the local
    # accumulator. Fetch the REAL balance before any compute, gate + DISPLAY on it (fixes the local
    # counter that drifts from the server), and HARD-STOP if depleted. A transient fetch failure returns
    # None -> fall through to the local count (fail-open) so a network blip never blocks a paying user.
    # Free-trial keys never hit the gateway: they stay fully local and offline-friendly.
    server_runs = _server_runs(api_key)
    if server_runs is not None:
        runs_left = server_runs
        token["runs_remaining"] = server_runs
        write_token(token)
    if not isinstance(runs_left, int) or runs_left <= 0:
        print(meter_depleted_box())
        print(footer(ok=False, runs=0))
        return 1

    csv_path = args[0] if args else os.path.join(d.ROOT, "fixtures", "metrics.csv")
    if os.path.exists(csv_path):
        csv_data, src = open(csv_path, encoding="utf-8").read(), csv_path
    else:
        csv_data = ("metric_id,component,load_value,status\n"
                    "M-101,generator-alpha,87.4,active\n"
                    "M-102,turbine-beta,12.1,idle\n"
                    "M-103,coolant-main,55.2,active\n")
        src = "built-in sample (no csv path given)"
    contract = load_contract()

    with Spinner("Metering run…"):
        result = d.compile_csv(csv_data, contract, strict=True)
        receipt = d.write_receipt(csv_data, result, strict=True)

    audit = receipt["network_audit"]
    ext = audit.get("external_sockets_open")
    lines = [c("source", "dim") + "   " + src, ""]
    if not result.get("ok"):
        lines.append(c(f"✗ BLOCKED: {result.get('error')} {result.get('violations') or ''}", "red"))
    else:
        lines.append(c(f"✓ compiled {len(result['records'])} rows → tables/power-grid", "green"))
        lines += _table_lines(result["records"])
    lines.append("")
    lines.append((c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
                 c(f"   {ext} external sockets · lsof pids {audit.get('audited_pids')}", "slate"))
    lines.append(c("receipt", "dim") + "   " + str(d.RECEIPT_PATH))
    new_left = runs_left
    if result.get("ok"):
        token["runs_remaining"] = runs_left - 1
        write_token(token)
        new_left = token["runs_remaining"]
        api_key = token.get("api_key")
        if _is_paid_key(api_key):         # real rc_live_ key → book server-side (trial stays local)
            ok, detail = _meter_run(api_key, 1)
            lines.append((c("billing ✓", "green") if ok else c("billing ⚠", "amber")) +
                         c("   " + detail, "slate"))
    print(panel(lines, title="RAILCALL · local compile", color="cyan"))
    print(footer(ok=result.get("ok"), runs=new_left))
    return 0 if result.get("ok") else 1


def cmd_interpret(args):
    if not args:
        print(footer(ok=False, label='usage: railcall interpret "<prompt>"'))
        return 1
    token = read_token()
    if token is None:
        print(panel([c("Free-tier token not found at", "amber"), c("  " + TOKEN_PATH, "slate"), "",
                     c("Enroll:  curl -sL https://railcall.ai/install.sh | bash", "cyan")],
                    title="RAILCALL · interpret", color="amber"))
        print(footer(ok=False, runs=None))
        return 1
    runs_left = token.get("runs_remaining")
    api_key = token.get("api_key")
    # Server-authoritative balance gate for PAID keys (same as build): fetch the real balance, gate +
    # display on it, HARD-STOP if depleted; fall through to the local count on a fetch error (fail-open).
    # Free-trial keys stay fully local.
    server_runs = _server_runs(api_key)
    if server_runs is not None:
        runs_left = server_runs
        token["runs_remaining"] = server_runs
        write_token(token)
    if not isinstance(runs_left, int) or runs_left <= 0:
        print(meter_depleted_box())
        print(footer(ok=False, runs=0))
        return 1
    if not ollama_online():
        print(panel([c("Ollama not reachable on localhost:11434 — start it first.", "amber")],
                    title="RAILCALL · interpret", color="amber"))
        return 1
    prompt = " ".join(args)
    with Spinner(f"Metering run · {d.OLLAMA_MODEL}…"):
        res = d.interpret_nl(prompt, None, num_predict=256)
    a = res["airlock"]
    ext = a.get("during_call_external_sockets")
    if res.get("ollama_error"):
        print(panel([c(f"ollama error: {res['ollama_error']}", "red")], title="RAILCALL · interpret", color="red"))
        print(footer(ok=False))
        return 1
    body = (res.get("response") or "(empty)").strip().replace("\n", "\n")
    lines = [c("model", "dim") + "   " + f"{d.OLLAMA_MODEL}  ({d.OLLAMA_URL})",
             (c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
             c(f"   {ext} external sockets during call", "slate"), ""]
    lines += [body[i:i + (_termwidth() - 6)] for i in range(0, len(body), _termwidth() - 6)] or [c("(empty)", "slate")]
    lines.append("")
    lines.append(c("receipt", "dim") + "   " + str(d.INTERPRET_RECEIPT_PATH))
    token["runs_remaining"] = runs_left - 1   # interpret is a metered run, same as build
    write_token(token)
    api_key = token.get("api_key")
    if _is_paid_key(api_key):                 # real rc_live_ key → book server-side (trial stays local)
        ok, detail = _meter_run(api_key, 1)
        lines.append((c("billing ✓", "green") if ok else c("billing ⚠", "amber")) +
                     c("   " + detail, "slate"))
    print(panel(lines, title="RAILCALL · local NL interpret", color="cyan"))
    print(footer(ok=True, runs=token["runs_remaining"]))
    return 0


def cmd_daemon(_=None):
    if daemon_online():
        print(panel([c(f"daemon already running on {d.HOST}:{d.PORT}", "amber")], title="RAILCALL · daemon", color="amber"))
        return 0
    try:
        d.main()
    except OSError as e:
        print(panel([c(f"could not bind {d.HOST}:{d.PORT}: {e}", "red")], title="RAILCALL · daemon", color="red"))
        return 1
    return 0


def cmd_health(_=None):
    audit = d.lsof_socket_audit()
    ext = audit.get("external_sockets_open")
    lines = [
        c("daemon", "dim") + "   " + (c(f"online ({d.HOST}:{d.PORT})", "green") if daemon_online() else c("offline", "amber")),
        (c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
        c(f"   {ext} external sockets · audited pids {audit.get('audited_pids')}", "slate"),
    ]
    print(panel(lines, title="RAILCALL · health", color="cyan"))
    print(footer(ok=(ext == 0)))
    return 0


def cmd_balance(_=None):
    """Query the live gateway for this key's MEASURED balance — no fake numbers."""
    token = read_token()
    api_key = (token or {}).get("api_key")
    if not api_key:
        print(panel([c("no api_key in token — install first:", "amber"),
                     c("  curl -sL https://railcall.ai/install.sh | bash", "cyan")],
                    title="RAILCALL · balance", color="amber"))
        return 1
    gateway = _gateway()
    url = f"{gateway}/v1/balance?api_key={api_key}"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "railcall-cli"})
    data = None
    err = None
    with Spinner(f"Verifying key against {gateway}…"):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            err = e
    if err is not None:
        code = getattr(err, "code", None)
        msg = ("gateway does not recognize this api_key (no consumer row)" if code == 401
               else f"cannot reach gateway ({code or type(err).__name__})")
        print(panel([c("✗ " + msg, "amber" if code == 401 else "red")], title="RAILCALL · balance", color="red"))
        print(footer(ok=False))
        return 1
    runs = data.get("runs_remaining")
    if runs == 0:
        print(meter_depleted_box())
        print(footer(ok=False, runs=0))
        return 1
    lines = [
        c("key", "dim") + "    " + f"{str(api_key)[:14]}…",
        c("tier", "dim") + "   " + c(str(data.get("tier", "?")).upper(), "purple"),
        c("runs", "dim") + "   " + c(f"{runs} remaining", "green"),
    ]
    print(panel(lines, title="RAILCALL LEDGER · verified balance", color="cyan"))
    print(footer(ok=True, runs=runs))
    return 0


def cmd_login(args):
    """Save an api_key to the local token, then verify it against the gateway."""
    if not args:
        print(footer(ok=False, label="usage: railcall login <api_key>"))
        return 1
    api_key = args[0].strip()
    token = read_token() or {}
    token["api_key"] = api_key
    write_token(token)
    print(panel([c(f"✓ saved key {api_key[:14]}…", "green") + c("  → " + TOKEN_PATH, "dim")],
                title="RAILCALL · login", color="cyan"))
    return cmd_balance()


def cmd_studio(_=None):
    """Open the local RailCall Studio (the visual builder) on 127.0.0.1:8799 and launch the browser.
    Runs the bundled station server (install.sh drops it in ~/.railcall/station); loopback only, your
    data stays on this machine. Blocks until you Ctrl+C."""
    server = os.path.join(os.path.expanduser("~/.railcall"), "station", "workbench", "studio_server.py")
    if not os.path.exists(server):
        print(panel([c("Studio isn't installed yet.", "amber"),
                     c("Re-run the installer to fetch it:", "slate"),
                     c("  curl -fsSL https://railcall.ai/install.sh | bash", "cyan")],
                    title="RAILCALL · studio", color="amber"))
        print(footer(ok=False))
        return 1
    print(panel([c("Starting RailCall Studio …", "cyan"),
                 c("  http://127.0.0.1:8799/v2", "slate"),
                 c("  loopback only · your data stays on this machine", "dim"),
                 c("  Ctrl+C here to stop the Studio.", "dim")],
                title="RAILCALL · studio", color="purple"))
    import subprocess
    try:
        return subprocess.call([sys.executable, server], cwd=os.path.dirname(server))
    except KeyboardInterrupt:
        print(c("\nStudio stopped.", "dim"))
        return 0


COMMANDS = {"build": cmd_build, "interpret": cmd_interpret, "daemon": cmd_daemon,
            "start-daemon": cmd_daemon, "health": cmd_health, "dashboard": cmd_dashboard,
            "balance": cmd_balance, "login": cmd_login, "studio": cmd_studio}


def main():
    if len(sys.argv) < 2:
        return cmd_dashboard()
    fn = COMMANDS.get(sys.argv[1])
    if not fn:
        print(footer(ok=False, label=f"unknown command: {sys.argv[1]}"))
        return cmd_dashboard() or 1
    return fn(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)
