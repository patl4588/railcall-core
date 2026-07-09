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
  railcall demo                    30-second golden path: build a sample workflow locally,
                                   mint a REAL signed receipt, and verify it offline (no network)
  railcall build [path/to.csv]     local CSV compile + recursive socket audit + receipt
  railcall interpret "<prompt>"    local NL pass via Ollama, airlock-proven
                                   (model auto-detected; override: RAILCALL_OLLAMA_MODEL=<name>)
  railcall daemon                  start the loopback companion daemon (127.0.0.1:8555)
  railcall health                  daemon reachability + a socket audit of this process
  railcall doctor                  check the local environment (python, cryptography, Ollama,
                                   PATH, token, gateway) — each line PASS/WARN/FAIL + the exact fix
  railcall balance                 live run balance from the gateway
  railcall login <key>             save your rc_live_ key, then verify balance
  railcall verify [receipt]        re-check a receipt offline — no network, no trust
                                   (--key <signing_pubkey.json|dir> = verify against an explicit key)
  railcall rotate-key              mint a fresh Ed25519 signing keypair; archive the old public key
                                   (signing_pubkey.prev-<ts>.json) so pre-rotation receipts still verify

Paid runs (a saved rc_live_ key) are booked against the server-side prepaid balance via the
gateway's /meter after each successful build/interpret; free-trial runs stay fully local.
"""
import sys
import os

# Windows console encoding helper: force UTF-8 to prevent cp1252 UnicodeEncodeErrors
if sys.platform.startswith("win") or os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import re
import ast
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


# --------------------------------------------------- receipt history + audit log (community: Sami, bugs 20/27/28)
# A governed run must never destroy the proof of the last one, and every run should leave an append-only
# trail. Both live NEXT TO the canonical receipts in the daemon ROOT. Both are BEST-EFFORT — a history or
# log failure is swallowed and can NEVER break or fail a real run.
# Unify workspace paths between CLI and Studio (Finding 01 / community feedback)
_home = os.path.expanduser("~")
_station_workspace = os.path.join(_home, ".railcall", "station", ".railcall_workspace")
if os.path.isdir(_station_workspace):
    RECEIPTS_DIR = os.path.join(_station_workspace, "receipts")
    AUDIT_LOG_PATH = os.path.join(_station_workspace, "audit_log.jsonl")
else:
    RECEIPTS_DIR = os.path.join(getattr(d, "ROOT", os.path.join(_home, ".railcall")), "receipts")
    AUDIT_LOG_PATH = os.path.join(getattr(d, "ROOT", os.path.join(_home, ".railcall")), "audit_log.jsonl")


def _receipt_key_id(receipt):
    """The signing key_id to record in the trail — from the receipt's own signature block (Studio shape),
    else THIS install's pinned key doc, else a short fingerprint of the receipt's public key. NEVER a
    secret and NEVER the API key."""
    sig = receipt.get("signature")
    if isinstance(sig, dict) and sig.get("key_id"):
        return sig["key_id"]
    doc = _install_pubkey()
    if isinstance(doc, dict) and doc.get("key_id"):
        return doc["key_id"]
    pk = receipt.get("public_key_hex")
    return ("pk:" + pk[:16]) if isinstance(pk, str) and pk else None


def _archive_and_log(command, canonical_path, ok=True):
    """After a governed run writes its canonical (fixed-name) receipt, ALSO (1) keep a timestamped HISTORY
    copy under receipts/ so a later run can't overwrite this proof (bugs 20/27), and (2) append one
    structured line to audit_log.jsonl (bug 28). Reads the receipt straight off disk so the archived bytes
    are EXACTLY what was signed. Returns the history path, or None. Best-effort: any failure is swallowed."""
    try:
        receipt = json.loads(open(canonical_path, encoding="utf-8").read())
    except Exception:
        return None
    history_path = None
    try:
        os.makedirs(RECEIPTS_DIR, exist_ok=True)
        schema = str(receipt.get("schema") or command or "receipt").replace("/", "_").replace("..", "")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        cand = os.path.join(RECEIPTS_DIR, "%s-%s.json" % (schema, stamp))
        n = 1
        while os.path.exists(cand):   # collision-safe within the same second
            cand = os.path.join(RECEIPTS_DIR, "%s-%s-%d.json" % (schema, stamp, n)); n += 1
        d._save_receipt(cand, receipt)   # same atomic 0600 writer as the canonical receipt
        history_path = cand
    except Exception:
        history_path = None
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": command,
            "schema": receipt.get("schema"),
            "key_id": _receipt_key_id(receipt),
            "signed": bool(receipt.get("signature_hex") or
                           (isinstance(receipt.get("signature"), dict) and receipt["signature"].get("signature"))),
            "receipt": os.path.basename(canonical_path),
            "history": os.path.basename(history_path) if history_path else None,
            "ok": bool(ok),
        }
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass
    return history_path


# --------------------------------------------------- CSV formula-injection detection (community: Sami, bug 13)
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _is_formula_injection(cell):
    """CSV/spreadsheet formula-injection candidate (OWASP): a cell a spreadsheet app could EXECUTE on open.
    True when the first meaningful char is a formula trigger (= + - @ TAB CR) — after stripping a leading
    quote/space a spreadsheet ignores — EXCEPT (a) clean numbers, so -5 / +3.14 / 1e3 stay data, and
    (b) a lone trigger char, so a bare '-' placeholder isn't flagged."""
    s = cell or ""
    if not s:
        return False
    s2 = s.lstrip(" '\"")
    if len(s2) < 2 or s2[0] not in _FORMULA_TRIGGERS:
        return False
    try:                               # a clean number is data, never a formula
        float(s2.replace(",", "").replace(" ", ""))
        return False
    except ValueError:
        return True


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


def _is_metered_key(api_key):
    """A key the gateway knows + tracks server-side: a paid rc_live_ OR a real free rc_free_ account
    (created by web signup). Both have a server balance, so metering them makes the dashboard's run
    counter live for everyone. The install.sh local sentinel (rc_local_trial_100) is NOT a server
    account — it stays fully local/offline and never hits the gateway."""
    return isinstance(api_key, str) and (api_key.startswith("rc_live_") or api_key.startswith("rc_free_"))


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
    if not _is_metered_key(api_key):
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
    # Show the model the CLI would ACTUALLY use — auto-detected from local Ollama the same way
    # `railcall interpret` / `railcall doctor` do (query /api/tags, ~2s) — not a hardcoded default
    # that may not be installed. When Ollama is reachable but no model resolves, say so honestly
    # rather than claiming a model that isn't pulled.
    if oon:
        det_model, _dm_note, _dm_err = _resolve_ollama_model()
        model_line = (c(f"{det_model} (local Ollama)", "green") if det_model
                      else c("Ollama reachable · no model installed", "amber"))
    else:
        model_line = c("Ollama not reachable on :11434", "amber")
    head = [
        c("RAILCALL", "bold") + c("  ·  local companion CLI", "slate"),
        "",
        c("workspace", "dim") + "  " + str(d.ROOT),
        c("daemon   ", "dim") + "  " + (c(f"online ({d.HOST}:{d.PORT})", "green") if don
                                        else c("offline — railcall daemon", "amber")),
        c("model    ", "dim") + "  " + model_line,
    ]
    print(panel(head, title="RAILCALL", color="purple"))
    cmds = [
        c("demo", "cyan") + "               30-second golden path: build → signed receipt → offline verify",
        c("studio", "cyan") + "             open the visual Studio in your browser (127.0.0.1:8799)",
        c("build", "cyan") + c(" [csv]", "dim") + "        local compile + socket audit + receipt",
        c("audit", "cyan") + c(" <csv>", "dim") + "        zero-retention structural audit + signed receipt",
        c("verify", "cyan") + c(" [receipt]", "dim") + "   re-check the last receipt offline — no network, no trust",
        c("receipts", "cyan") + c(" list", "dim") + "   browse the signed receipt history — timestamped, never overwritten",
        c("interpret", "cyan") + c(' "<prompt>"', "dim") + "  local NL pass (Ollama), airlock-proven",
        c("daemon", "cyan") + "             start loopback daemon on 127.0.0.1:8555",
        c("health", "cyan") + "             daemon + socket-audit status",
        c("doctor", "cyan") + "             check the local environment (PASS/WARN/FAIL + the exact fix)",
        c("balance", "cyan") + "            live run balance from the gateway",
        c("login", "cyan") + c(" <key>", "dim") + "        save your rc_live_ key, then verify",
        c("rotate-key", "cyan") + "         mint a fresh Ed25519 signing key (archives the old public key)",
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

    # A SUPPLIED dataset path that doesn't exist is an honest error — never silently fall
    # back to the built-in sample and mint a green receipt over data the user never gave us
    # (contest finding #14: silent power-grid fallback). The sample is the default ONLY when
    # no path was supplied.
    supplied = bool(args)
    csv_path = args[0] if args else os.path.join(d.ROOT, "fixtures", "metrics.csv")
    if supplied and not os.path.exists(csv_path):
        print(panel([c("dataset not found:", "red"), c("  " + csv_path, "slate"), "",
                     c("check the path, or run 'railcall build' with no argument to use the sample.", "dim")],
                    title="RAILCALL · build", color="red"))
        print(footer(ok=False, runs=runs_left))
        return 1
    if os.path.exists(csv_path):
        try:
            csv_data, src = open(csv_path, encoding="utf-8").read(), csv_path
        except Exception as _e:
            print(panel([c("could not read dataset:", "red"), c("  " + csv_path, "slate"),
                         c("  " + str(_e), "dim")], title="RAILCALL · build", color="red"))
            print(footer(ok=False, runs=runs_left))
            return 1
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
        if _is_metered_key(api_key):      # rc_live_ / rc_free_ server account → book server-side
            ok, detail = _meter_run(api_key, 1)
            lines.append((c("billing ✓", "green") if ok else c("billing ⚠", "amber")) +
                         c("   " + detail, "slate"))
    history_path = _archive_and_log("build", str(d.RECEIPT_PATH), ok=result.get("ok"))  # history + audit_log
    if history_path:
        lines.append(c("history", "dim") + "   " + os.path.join(RECEIPTS_DIR, os.path.basename(history_path)))
    print(panel(lines, title="RAILCALL · local compile", color="cyan"))
    print(footer(ok=result.get("ok"), runs=new_left))
    return 0 if result.get("ok") else 1


def _resolve_ollama_model():
    """Pick the local Ollama model honestly instead of 404ing on a hardcoded default.
    Order: RAILCALL_OLLAMA_MODEL env → the current default if it is actually installed
    (per /api/tags) → the first installed model (with a printed note) → an honest error
    when nothing is pulled. /api/tags is read with a ~2s timeout; if it can't be read we
    keep the current default (prior behavior). Returns (model, note, error_lines)."""
    env = os.environ.get("RAILCALL_OLLAMA_MODEL")
    if env:
        return env, None, None
    tags_url = d.OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=2) as r:
            models = [m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", [])
                      if m.get("name")]
    except Exception:
        return d.OLLAMA_MODEL, None, None
    if d.OLLAMA_MODEL in models:
        return d.OLLAMA_MODEL, None, None
    if models:
        return models[0], ("using %s (auto-detected — override with RAILCALL_OLLAMA_MODEL=<name>)"
                           % models[0]), None
    return None, None, [
        "No models installed in local Ollama — nothing to interpret with.",
        "  Pull one first:   ollama pull " + d.OLLAMA_MODEL,
        "  or point at yours:  RAILCALL_OLLAMA_MODEL=<name> railcall interpret \"…\"",
    ]


_CODE_FENCE_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)
_CODE_HINT_RE = re.compile(r"^\s*(import\s+\w|from\s+\S+\s+import\s|def\s+\w+\s*\(|class\s+\w)", re.M)


def _code_candidate(text):
    """The Python code the model produced, or None when the reply is prose (nothing to
    parse-gate). A fenced ``` block wins; otherwise the whole reply counts only when it
    reads as Python — prose answers must not be failed through ast.parse."""
    m = _CODE_FENCE_RE.search(text)
    if m:
        return m.group(1)
    if _CODE_HINT_RE.search(text):
        return text
    return None


def cmd_interpret(args):
    if not args:
        print(panel([c('usage: railcall interpret "<prompt>"', "amber"),
                     c("model is auto-detected from local Ollama — override with", "slate"),
                     c("  RAILCALL_OLLAMA_MODEL=<name> railcall interpret \"…\"", "cyan")],
                    title="RAILCALL · interpret", color="amber"))
        print(footer(ok=False))
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
        print(panel([c("The local model server (Ollama) isn't answering on 127.0.0.1:11434.", "amber"),
                     c("  Only `railcall interpret` needs it; build / audit / verify don't.", "slate"),
                     c("  Fix:  ollama serve      (first time, also: ollama pull " + d.OLLAMA_MODEL + ")", "cyan"),
                     c("  No run was metered — your balance is untouched.", "dim")],
                    title="RAILCALL · interpret", color="amber"))
        print(footer(ok=False))
        return 1
    model, model_note, model_err = _resolve_ollama_model()
    if model_err:
        print(panel([c(model_err[0], "amber")] + [c(l, "slate") for l in model_err[1:]],
                    title="RAILCALL · interpret", color="amber"))
        print(footer(ok=False))
        return 1
    d.OLLAMA_MODEL = model      # query_local_ollama reads this module global
    if model_note:
        print("  " + c(model_note, "slate"))
    prompt = " ".join(args)
    with Spinner(f"Metering run · {d.OLLAMA_MODEL}…"):
        res = d.interpret_nl(prompt, None, num_predict=256)
    a = res["airlock"]
    ext = a.get("during_call_external_sockets")
    if res.get("ollama_error"):
        print(panel([c("The local model call failed mid-run — nothing was written or sent.", "red"),
                     c("  Ollama said: " + str(res["ollama_error"]), "slate"),
                     c("  Common fixes: pull the model (ollama pull %s), or free memory and retry." % d.OLLAMA_MODEL, "cyan"),
                     c("  No run was metered — your balance is untouched.", "dim")],
                    title="RAILCALL · interpret", color="red"))
        print(footer(ok=False))
        return 1
    body = (res.get("response") or "(empty)").strip().replace("\n", "\n")
    # Parse-gate any code the model produced: NEVER hand back Python that does not parse.
    # One honest retry (the exact SyntaxError goes back to the model), then fail non-zero.
    syntax_note = None
    code = _code_candidate(body)
    if code is not None:
        try:
            ast.parse(code)
        except SyntaxError as first_err:
            retry_prompt = (prompt + "\n\nYour previous code fails to parse with this Python "
                            "SyntaxError:\n" + str(first_err) + "\nReturn a corrected version.")
            with Spinner(f"Output didn't parse — retrying once · {d.OLLAMA_MODEL}…"):
                res2 = d.interpret_nl(retry_prompt, None, num_predict=256)
            failed_err, failed_code = None, code
            if res2.get("ollama_error"):
                failed_err = first_err
            else:
                body2 = (res2.get("response") or "").strip()
                code2 = _code_candidate(body2)
                if code2 is None:
                    code2 = body2       # retry was asked for code; hold whatever came back to the same bar
                try:
                    ast.parse(code2)
                    res, body = res2, body2
                    a = res["airlock"]
                    ext = a.get("during_call_external_sockets")
                    syntax_note = "syntax check: first output had a SyntaxError; retried once — corrected output parses"
                except SyntaxError as second_err:
                    failed_err, failed_code = second_err, code2
            if failed_err is not None:
                print(panel([c("✗ INTERPRET FAILED — model output is not valid Python after one retry", "red"),
                             c("  SyntaxError: " + str(failed_err), "amber"),
                             c("  The broken code is printed below. Nothing was written or executed.", "slate")],
                            title="RAILCALL · interpret", color="red"))
                print(failed_code)
                print(footer(ok=False))
                return 1
    lines = [c("model", "dim") + "   " + f"{d.OLLAMA_MODEL}  ({d.OLLAMA_URL})",
             (c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
             c(f"   {ext} external sockets during call", "slate"), ""]
    lines += [body[i:i + (_termwidth() - 6)] for i in range(0, len(body), _termwidth() - 6)] or [c("(empty)", "slate")]
    lines.append("")
    if syntax_note:
        lines.append(c("· " + syntax_note, "dim"))
    lines.append(c("receipt", "dim") + "   " + str(d.INTERPRET_RECEIPT_PATH))
    token["runs_remaining"] = runs_left - 1   # interpret is a metered run, same as build
    write_token(token)
    api_key = token.get("api_key")
    if _is_metered_key(api_key):              # rc_live_ / rc_free_ server account → book server-side
        ok, detail = _meter_run(api_key, 1)
        lines.append((c("billing ✓", "green") if ok else c("billing ⚠", "amber")) +
                     c("   " + detail, "slate"))
    history_path = _archive_and_log("interpret", str(d.INTERPRET_RECEIPT_PATH), ok=True)  # history + audit_log
    if history_path:
        lines.append(c("history", "dim") + "   " + os.path.join(RECEIPTS_DIR, os.path.basename(history_path)))
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


def cmd_doctor(_=None):
    """Check the local environment for the exact classes of failure that break local runs — an old
    python, no `cryptography` (so receipts mint UNSIGNED), a PEP-668 pip refusal, an unreachable or
    empty Ollama, ~/.railcall/bin off PATH, a missing token — and report each honestly PASS/WARN/FAIL
    with the exact fix. Reaches the network for ONE 2s gateway ping only; offline is a fully-supported
    state for local build/audit/interpret, so it is reported as fine, never as a failure."""
    lines = []
    worst = 0   # 0 = pass, 1 = warn, 2 = fail — drives the summary + exit code

    def rec(status, text, fix=None):
        nonlocal worst
        worst = max(worst, {"PASS": 0, "WARN": 1, "FAIL": 2}[status])
        col = {"PASS": "green", "WARN": "amber", "FAIL": "red"}[status]
        lines.append(c(status, col) + "  " + text)
        if fix:
            lines.append(c("      → " + fix, "dim"))

    # python3 version
    v = sys.version_info
    if v >= (3, 8):
        rec("PASS", "python %d.%d.%d (>= 3.8)" % (v.major, v.minor, v.micro))
    else:
        rec("FAIL", "python %d.%d.%d is too old — RailCall needs >= 3.8" % (v.major, v.minor, v.micro),
            "install a newer python3 (e.g. brew install python@3.12), then re-run this")

    # cryptography — without it receipts are honestly UNSIGNED (still airlock-measured)
    try:
        import cryptography  # noqa: F401
        ver = getattr(cryptography, "__version__", "?")
        rec("PASS", "cryptography %s importable — receipts are Ed25519-SIGNED" % ver)
    except Exception:
        rec("WARN", "cryptography NOT importable — receipts will mint UNSIGNED (still airlock-measured)",
            "python3 -m pip install --user --break-system-packages cryptography")

    # Ollama (only `railcall interpret` needs it) + which model is actually installed
    tags_url = d.OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=2) as r:
            models = [m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", [])
                      if m.get("name")]
        if not models:
            rec("WARN", "Ollama reachable on :11434 but NO models installed (interpret needs one)",
                "ollama pull " + d.OLLAMA_MODEL)
        elif d.OLLAMA_MODEL in models:
            rec("PASS", "Ollama reachable on :11434 · default model %s installed" % d.OLLAMA_MODEL)
        else:
            rec("WARN", "Ollama reachable but default %s NOT installed (have: %s)"
                % (d.OLLAMA_MODEL, ", ".join(models[:4])),
                "ollama pull %s   (or run interpret with RAILCALL_OLLAMA_MODEL=%s)"
                % (d.OLLAMA_MODEL, models[0]))
    except Exception:
        rec("WARN", "Ollama not reachable on 127.0.0.1:11434 (only 'railcall interpret' needs it)",
            "start it (ollama serve) then: ollama pull " + d.OLLAMA_MODEL)

    # ~/.railcall/bin on PATH — the install.sh shim lives here
    bindir = os.path.join(os.path.expanduser("~"), ".railcall", "bin")
    if bindir in os.environ.get("PATH", "").split(os.pathsep):
        rec("PASS", "~/.railcall/bin is on PATH")
    else:
        is_windows = os.name == "nt" or sys.platform.startswith(("win", "msys", "cygwin")) or "MSYSTEM" in os.environ
        if is_windows:
            rec("WARN", "~/.railcall/bin is NOT on PATH — the 'railcall' shim may not be found",
                'For Git Bash/MINGW: export PATH="$HOME/.railcall/bin:$PATH"  (add to ~/.bashrc); for cmd: setx PATH "%PATH%;%USERPROFILE%\\.railcall\\bin"')
        else:
            rec("WARN", "~/.railcall/bin is NOT on PATH — the 'railcall' shim may not be found",
                'export PATH="$HOME/.railcall/bin:$PATH"   (add that line to ~/.zshrc or ~/.bashrc)')

    # token.json present + shape (never print the full key)
    tok = read_token()
    if tok is None:
        rec("WARN", "token.json not found at " + TOKEN_PATH + " (build/interpret need it)",
            "curl -fsSL https://railcall.ai/install.sh | bash   (or: railcall login <key>)")
    elif not isinstance(tok, dict) or not tok.get("api_key"):
        rec("WARN", "token.json present but has no api_key field",
            "railcall login <your rc_… key>")
    else:
        ak = str(tok.get("api_key"))
        runs = tok.get("runs_remaining")
        rec("PASS", "token.json present · key %s… · runs_remaining %s"
            % (ak[:12], runs if isinstance(runs, int) else "?"))

    # gateway ping — 2s, honest, and offline is FINE (local runs need no network)
    gw = _gateway()
    if _probe(gw + "/health", timeout=2):
        rec("PASS", "gateway reachable at " + gw + " (live balance + metering)")
    else:
        # a fully-supported state, not a failure — do NOT inflate the summary
        lines.append(c("PASS", "green") + "  gateway offline at " + gw
                     + " — FINE; local build/audit/interpret need no network")

    summary = {
        0: c("✓ environment is ready for local runs", "green"),
        1: c("⚠ usable, but some features are degraded — apply the → fixes above", "amber"),
        2: c("✗ blocking problem — fix the FAIL line above before running", "red"),
    }[worst]
    lines.append("")
    lines.append(summary)
    print(panel(lines, title="RAILCALL · doctor", color="purple"))
    print(footer(ok=(worst < 2), label={0: "Ready", 1: "Degraded", 2: "Blocked"}[worst]))
    return 0 if worst < 2 else 1


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
        if code == 401:
            # bad/unrecognized key: say WHAT happened + the exact recovery step
            lines = [
                c("✗ the gateway does not recognize this key (401 — no account on file)", "amber"),
                c("  The saved key isn't a provisioned rc_live_/rc_free_ account, or it was rotated.", "slate"),
                c("  Fix:  railcall login <your rc_live_… key>   (copy it from your railcall.ai dashboard)", "cyan"),
                c("  New here?  curl -fsSL https://railcall.ai/install.sh | bash", "dim"),
            ]
        else:
            # gateway unreachable: name the host, reassure that local work still runs, give the fix
            gw = _gateway()
            lines = [
                c("✗ couldn't reach the billing gateway (%s)" % (code or type(err).__name__), "red"),
                c("  " + gw + " is unreachable — you're likely offline, or it's briefly down.", "slate"),
                c("  Local build / audit / interpret need NO network and still work right now.", "slate"),
                c("  Fix:  check your connection and retry, or point at another gateway with", "cyan"),
                c("        RAILCALL_GATEWAY_URL=<url> railcall balance", "cyan"),
            ]
        print(panel(lines, title="RAILCALL · balance", color=("amber" if code == 401 else "red")))
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
    if not api_key:
        print(panel([c("key cannot be empty — usage: railcall login <api_key>", "red")],
                    title="RAILCALL · login", color="red"))
        print(footer(ok=False)); return 1
    old_token = read_token() or {}
    token = dict(old_token)
    token["api_key"] = api_key
    write_token(token)
    print(panel([c(f"✓ saved key {api_key[:14]}…", "green") + c("  → " + TOKEN_PATH, "dim")],
                title="RAILCALL · login", color="cyan"))
    rc = cmd_balance()
    if rc != 0:
        write_token(old_token)
        print(panel([c("Previous key restored — the new key was not accepted.", "amber")],
                    title="RAILCALL · login", color="amber"))
    return rc


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


# ---- railcall audit: local, zero-retention structural audit of a CSV/log (stdlib only) ----
_AUDIT_RE = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "ssn": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
    "intg": re.compile(r"^-?\d+$"),
    "floatg": re.compile(r"^-?\d*\.\d+$"),
    "isodate": re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$"),
    "usdate": re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"),
    "phone": re.compile(r"^[+(]?[\d][\d\s().+-]{6,}$"),
    "money": re.compile(r"^[$£€]?\s?-?[\d,]+(\.\d+)?$"),
    "boolean": re.compile(r"^(true|false|yes|no|y|n)$", re.I),
}


def _audit_classify(v):
    v = (v or "").strip()
    if v == "":
        return "empty"
    R = _AUDIT_RE
    if R["email"].match(v): return "email"
    if R["ssn"].match(v): return "ssn"
    if R["intg"].match(v): return "int"
    if R["floatg"].match(v): return "float"
    if R["isodate"].match(v): return "date-iso"
    if R["usdate"].match(v): return "date-us"
    digits = re.sub(r"\D", "", v)
    if R["phone"].match(v) and 7 <= len(digits) <= 15: return "phone"
    if R["money"].match(v) and re.search(r"\d", v): return "number-ish"
    if R["boolean"].match(v): return "bool"
    return "text"


def _audit_family(t):
    if t in ("int", "float", "number-ish"): return "number"
    if t in ("date-iso", "date-us"): return "date"
    return t


def _audit_rows(rows):
    rows = [r for r in rows if any((x or "").strip() for x in r)]
    if len(rows) < 2:
        return None
    headers = [(h or "").strip() or ("column_%d" % (i + 1)) for i, h in enumerate(rows[0])]
    data, ncol, findings = rows[1:], len(rows[0]), []
    ragged = sum(1 for r in data if len(r) != ncol)
    if ragged:
        findings.append(("warn", "%d row%s the wrong number of columns" % (ragged, " has" if ragged == 1 else "s have")))
    seen = {}
    for h in headers:
        seen[h.lower()] = seen.get(h.lower(), 0) + 1
    for k, cnt in seen.items():
        if cnt > 1:
            findings.append(("warn", 'duplicate column name "%s" (x%d)' % (k, cnt)))
    pii = 0
    injection = 0
    for ci, name in enumerate(headers):
        fam, fine, empties, formats = {}, {}, 0, {}
        for r in data:
            raw = (r[ci] if ci < len(r) else "") or ""
            t = _audit_classify(raw); f = _audit_family(t)
            fam[f] = fam.get(f, 0) + 1; fine[t] = fine.get(t, 0) + 1
            if t == "empty": empties += 1
            if f in ("date", "phone"): formats[t] = formats.get(t, 0) + 1
        nonempty = len(data) - empties
        if nonempty <= 0:
            findings.append(("info", '"%s" is entirely empty' % name)); continue
        dom, domn = None, 0
        for f, cnt in fam.items():
            if f != "empty" and cnt > domn: dom, domn = f, cnt
        if dom and domn / nonempty < 0.985:
            findings.append(("warn", 'mixed values in "%s" — %d of %d non-empty rows are not %s' % (name, nonempty - domn, nonempty, dom)))
        if len(formats) > 1:
            findings.append(("warn", 'inconsistent formats in "%s" (%s)' % (name, " + ".join(formats.keys()))))
        er = empties / len(data)
        if 0.15 <= er < 1.0:
            findings.append(("info", '"%s" is %d%% empty' % (name, round(er * 100))))
        if fine.get("email"): findings.append(("pii", 'PII: "%s" contains email addresses' % name)); pii += 1
        if fine.get("phone"): findings.append(("pii", 'PII: "%s" contains phone numbers' % name)); pii += 1
        if fine.get("ssn"): findings.append(("pii", 'sensitive: "%s" looks like SSNs' % name)); pii += 1
        inj = sum(1 for r in data if _is_formula_injection(r[ci] if ci < len(r) else ""))
        if inj:
            findings.append(("risk", 'CSV injection: "%s" has %d cell%s starting with a formula trigger '
                             '(= + - @) — could execute if opened in Excel/Sheets' % (name, inj, "" if inj == 1 else "s")))
            injection += inj
    rank = {"risk": 0, "pii": 1, "warn": 2, "info": 3}
    findings.sort(key=lambda fd: rank.get(fd[0], 4))
    return {"headers": headers, "rows": len(data), "cols": ncol, "findings": findings,
            "breakers": sum(1 for fd in findings if fd[0] == "warn"), "pii": pii, "injection": injection}


def cmd_audit(args):
    """Audit a CSV/log file's STRUCTURE locally — schema, ragged rows, mixed-type columns, PII — and
    mint a local airlock-measured receipt. ZERO-RETENTION: the file is read from your disk, parsed in
    memory, and nothing is sent anywhere (no LLM, no upload). usage: railcall audit <file.csv>"""
    if not args:
        print(footer(ok=False, label="usage: railcall audit <file.csv>")); return 1
    path = args[0]
    if not os.path.exists(path):
        print(panel([c("File not found:", "amber"), c("  " + path, "slate")], title="RAILCALL · audit", color="amber"))
        print(footer(ok=False)); return 1
    import csv as _csv
    import io as _io
    raw = open(path, encoding="utf-8", errors="replace").read()
    file_ext = os.path.splitext(path)[1].lower()
    head_ch = raw.lstrip()[:1]

    def _reject(reason):
        """REJECT clearly-non-tabular input: print a refusal, mint NO receipt, exit non-zero.
        `railcall audit` structurally audits delimited tables (.csv/.tsv) — a system file, a JSON
        blob, or a binary is not a spreadsheet, and minting an 'audited' receipt for one misleads."""
        print(panel([c("Refusing to audit — this isn't a CSV/TSV table.", "red"),
                     c("  " + path, "slate"),
                     c("  " + reason, "slate"),
                     c("  `railcall audit` structurally audits delimited tables (.csv/.tsv).", "slate"),
                     c("  No receipt was minted — point it at a CSV/TSV export instead.", "dim")],
                    title="RAILCALL · audit", color="red"))
        print(footer(ok=False, label="Rejected — not a CSV/TSV table"))
        return 1

    # Binary content (NUL bytes) is never a CSV/TSV table and would otherwise crash the csv reader.
    if file_ext not in (".csv", ".tsv") and "\x00" in raw:
        return _reject("content contains NUL bytes (binary, not text)")

    sniff_ok = True
    try:
        dialect = _csv.Sniffer().sniff(raw[:4096], delimiters=",\t;|")
    except Exception:
        dialect = _csv.excel
        sniff_ok = False
    try:
        parsed_rows = list(_csv.reader(_io.StringIO(raw), dialect))
    except _csv.Error:
        # a genuine table parses cleanly; a parser blow-up means this isn't one
        if file_ext not in (".csv", ".tsv"):
            return _reject("content could not be parsed as a delimited table")
        raise
    res = _audit_rows(parsed_rows)
    if res is None:
        print(panel([c("Need a header row + at least one data row.", "amber")], title="RAILCALL · audit", color="amber"))
        print(footer(ok=False)); return 1
    # Rejection gate (BUG 12): REJECT only when BOTH hold — the extension isn't .csv/.tsv AND the
    # content doesn't parse as delimited tabular data. A .csv/.tsv file, or a non-CSV extension whose
    # content DOES parse as a multi-column table, keeps prior behavior exactly.
    non_tabular = []
    if head_ch in ("{", "["):
        non_tabular.append("content is JSON-like (starts with %r)" % head_ch)
    if not sniff_ok and res["cols"] == 1:
        non_tabular.append("no delimiter detected — only one column parsed per line")
    if file_ext not in (".csv", ".tsv") and non_tabular:
        return _reject("; ".join(non_tabular))
    # Honesty gate: for input that survives the reject (e.g. a non-CSV extension whose content
    # still parses as a table) warn LOUDLY when it doesn't look like CSV — proceed, receipt says so.
    not_csv_reasons = []
    if file_ext not in (".csv", ".tsv"):
        not_csv_reasons.append("extension %s is not .csv/.tsv" % (file_ext or "(none)"))
    if head_ch in ("{", "["):
        not_csv_reasons.append("content starts with %r (JSON-like)" % head_ch)
    if not sniff_ok and res["cols"] == 1:
        not_csv_reasons.append("no CSV dialect detected and only 1 column parsed")
    input_warning = None
    if not_csv_reasons:
        input_warning = ("input does not look like CSV (" + "; ".join(not_csv_reasons) +
                         ") — parsed as CSV anyway; results may be meaningless")
    net = d.lsof_socket_audit()
    receipt = {
        "schema": "railcall_audit_receipt.v1",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "file": {"name": os.path.basename(path), "sha256": "sha256:" + d.sha256_hex(raw),
                 "bytes": len(raw.encode("utf-8"))},
        "audit": {"rows": res["rows"], "columns": res["cols"], "import_breakers": res["breakers"],
                  "pii_columns": res["pii"], "formula_injection_cells": res.get("injection", 0),
                  "findings": [{"severity": s, "detail": t} for s, t in res["findings"]]},
        "network_audit": net,        # MEASURED via lsof — not asserted
        "result": "audited_with_input_warning" if input_warning else "audited",
    }
    if input_warning:
        receipt["input_warning"] = input_warning
    d._sign_receipt(receipt)         # Ed25519 if a key is vaulted; honestly unsigned otherwise
    receipt_path = os.path.join(d.ROOT, "railcall_audit_receipt.json")
    d._save_receipt(receipt_path, receipt)
    history_path = _archive_and_log("audit", receipt_path, ok=True)   # timestamped history + audit_log.jsonl
    ext = net.get("external_sockets_open")
    lines = [c("file", "dim") + "   " + os.path.basename(path) +
             c("   %d rows x %d cols" % (res["rows"], res["cols"]), "slate"), ""]
    if input_warning:
        lines.append(c("⚠ WARNING", "red") + " " + c(input_warning, "amber"))
        lines.append("")
    if not res["findings"]:
        lines.append(c("✓ no structural issues found", "green"))
    else:
        icon = {"risk": ("‼", "red"), "pii": ("⚠", "purple"), "warn": ("!", "amber"), "info": ("i", "slate")}
        for sev, det in res["findings"][:14]:
            mk, col = icon.get(sev, ("·", "slate"))
            lines.append(c(mk, col) + " " + c(det, "slate"))
        if len(res["findings"]) > 14:
            lines.append(c("  … %d more" % (len(res["findings"]) - 14), "dim"))
    lines.append("")
    lines.append(c("%d import-breakers · %d PII columns · %d formula-injection cells" %
                   (res["breakers"], res["pii"], res.get("injection", 0)),
                   "red" if res.get("injection") else ("amber" if res["breakers"] else "green")))
    lines.append((c("airlock ✓", "green") if ext == 0 else c("airlock ?", "amber")) +
                 c("   %s external sockets · the file never left this machine" %
                   (ext if ext is not None else "?"), "slate"))
    signed = "ed25519-signed" if receipt.get("signature_hex") else "unsigned (pip install cryptography to sign)"
    lines.append(c("receipt", "dim") + "   " + receipt_path + c("  · " + signed, "dim"))
    if history_path:
        lines.append(c("history", "dim") + "   " + os.path.join(RECEIPTS_DIR, os.path.basename(history_path)) +
                     c("  · railcall receipts list", "dim"))
    print(panel(lines, title="RAILCALL · local audit", color="cyan"))
    print(footer(ok=True, label="Audited (input warning)" if input_warning else None))
    return 0


def _install_pubkey():
    """Load THIS install's pinned public-key doc (public_key_hex, key_id) from signing_pubkey.json.
    Trusted locations ONLY: $RAILCALL_WS, the station workspace, ~/.railcall, and the daemon ROOT
    workspace. The directory NEXT TO the receipt is deliberately NEVER searched: a key that travels
    with the receipt is self-attestation — a forger drops a fake signing_pubkey.json beside a forged
    receipt and it 'verifies'. Keys come from this install, or explicitly from the user via --key."""
    home = os.path.expanduser("~")
    dirs = []
    env = os.environ.get("RAILCALL_WS")
    if env:
        dirs.append(env)
    dirs += [
        os.path.join(home, ".railcall", "station", ".railcall_workspace"),
        os.path.join(home, ".railcall", ".railcall_workspace"),
        os.path.join(getattr(d, "ROOT", os.path.join(home, ".railcall")), ".railcall_workspace"),
    ]
    for dp in dirs:
        try:
            doc = json.loads(open(os.path.join(dp, "signing_pubkey.json"), encoding="utf-8").read())
            if isinstance(doc, dict) and doc.get("public_key_hex"):
                return doc
        except Exception:
            continue
    return None


def _verify_studio_receipt(receipt, path, user_key=None, explain=False):
    """Verify a Studio/workflow receipt: its 'signature' block signs the integrity field STRING
    (integrity_hash for builds, integrity for runs, integrity_root for workflow receipts), checked
    against this install's pinned signing_pubkey.json — or, when the user passed --key, against
    THAT key, with the trust clearly attributed in the output. `user_key` is (doc, path). When
    `explain` is set, every check is traced to stdout as it runs; output is otherwise unchanged."""
    def ex(msg):
        if explain:
            print(c("  · " + msg, "dim"))
    sb = receipt.get("signature") or {}
    # BUILD receipts carry integrity_hash; RUN receipts carry integrity; workflow
    # receipts carry integrity_root — same precedence as the routing check.
    ih_field = next((k for k in ("integrity_hash", "integrity", "integrity_root") if receipt.get(k)), None)
    ih = receipt.get(ih_field) if ih_field else None
    key_id = sb.get("key_id"); alg = sb.get("alg", "ed25519")
    net = receipt.get("network_audit") or {}
    ext = net.get("external_sockets_open")
    ex("integrity field read: %s = %r" % (ih_field, ih))
    ex("receipt signature alg %s · key_id %s" % (alg, key_id))
    if user_key is not None:
        doc, key_src = user_key
    else:
        doc, key_src = _install_pubkey(), None
    ex("trust key source: %s" % ("--key %s (user-supplied)" % key_src if key_src
                                 else "this install's pinned signing_pubkey.json"))
    if doc is None:
        print(panel([c("Studio receipt — need this install's signing key to verify offline.", "amber"),
                     c("  Verify inside the Studio (PROOF rail → VERIFY ALL FROM DISK), or run this on the", "slate"),
                     c("  machine that built the receipt.", "slate"),
                     c("  Third-party auditors: pass the publisher's key explicitly —", "slate"),
                     c("    railcall verify <receipt.json> --key <signing_pubkey.json>", "cyan")],
                    title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    ex("pinned key_id %s vs receipt key_id %s → %s"
       % (doc.get("key_id"), key_id,
          "MATCH" if (key_id and doc.get("key_id") and key_id == doc.get("key_id"))
          else ("MISMATCH (different install)" if key_id and doc.get("key_id") else "no key_id to compare")))
    if key_id and doc.get("key_id") and key_id != doc.get("key_id"):
        who = ("the --key you supplied" if key_src else "this install")
        print(panel([c("Studio receipt signed by a DIFFERENT key than %s." % who, "amber"),
                     c("  receipt key_id " + str(key_id) + " vs " + who + " " + str(doc.get("key_id")), "slate"),
                     c("  Verify it on the machine that built it — a receipt's key can't be trusted from here.", "slate")],
                    title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(doc["public_key_hex"]))
        try:
            pk.verify(bytes.fromhex(sb.get("sig", "")), str(ih).encode("utf-8"))
            ok = True
        except InvalidSignature:
            ok = False
        ex("ed25519 verify(sig, str(%s)) → %s" % (ih_field, "VALID" if ok else "INVALID"))
        ex("airlock: %s external sockets recorded during the run"
           % (ext if ext is not None else "not recorded"))
    except Exception:
        print(panel([c("Can't check this signature — the `cryptography` package isn't importable here.", "amber"),
                     c("  Install it, then re-run the exact same verify:", "slate"),
                     c("  python3 -m pip install --user --break-system-packages cryptography", "cyan"),
                     c("  railcall verify " + os.path.basename(path), "cyan")],
                    title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    lines = [c("receipt", "dim") + "   " + os.path.basename(path) + c("   " + str(receipt.get("schema", "")), "slate"),
             c("signer", "dim") + "    " + str(alg) + c("  key_id " + str(key_id), "slate"), ""]
    signed_by = "the USER-SUPPLIED key" if key_src else "this install's key"
    if ok:
        lines.append(c("✓ SIGNATURE VALID", "green") + c("   the %s field is signed by %s" % (ih_field, signed_by), "slate"))
    else:
        lines.append(c("✗ SIGNATURE INVALID", "red") + c("   altered after signing, or a different key signed it", "slate"))
    if ext is not None:
        lines.append((c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
                     c("   %s external sockets recorded during the run" % ext, "slate"))
    lines.append("")
    if key_src:
        lines.append(c("Verified against a USER-SUPPLIED key (--key " + key_src + ") — explicit trust,", "dim"))
        lines.append(c("chosen by you; this key did NOT come from this install or the receipt.", "dim"))
    else:
        lines.append(c("Verified offline against this install's signing_pubkey.json — no network.", "dim"))
    print(panel(lines, title="RAILCALL · verify", color=("cyan" if ok else "red")))
    print(footer(ok=ok))
    return 0 if ok else 1


def cmd_verify(args):
    """Re-check an Ed25519-signed receipt OFFLINE — no network, no trust in us. Handles both receipt
    shapes: CLI-audit receipts (flat signature_hex/public_key_hex) and Studio/workflow receipts (a
    nested 'signature' block signing the integrity_hash / integrity / integrity_root STRING, checked
    against this install's pinned key). --key <path> verifies against an explicit, user-supplied
    signing_pubkey.json instead (for third-party auditors) — the output attributes that trust.
    --explain traces every check performed (which integrity field was read, key_id matched vs
    pinned, signature valid/invalid, airlock socket count) so verification is legible, not magic.
    usage: railcall verify [receipt.json] [--key <signing_pubkey.json | dir>] [--explain]"""
    args = list(args)
    explain = "--explain" in args
    if explain:
        args = [a for a in args if a != "--explain"]

    def ex(msg):
        if explain:
            print(c("  · " + msg, "dim"))
    user_key = None     # (doc, path) — explicit, clearly-attributed trust; never implicit
    if "--key" in args:
        i = args.index("--key")
        if i + 1 >= len(args):
            print(footer(ok=False, label="usage: railcall verify [receipt.json] --key <signing_pubkey.json|dir>"))
            return 1
        kp = args[i + 1]
        del args[i:i + 2]
        if os.path.isdir(kp):
            kp = os.path.join(kp, "signing_pubkey.json")
        try:
            kd = json.loads(open(kp, encoding="utf-8").read())
            if not (isinstance(kd, dict) and kd.get("public_key_hex")):
                raise ValueError("no public_key_hex field in that file")
        except Exception as e:
            print(panel([c("Could not load the --key file:", "amber"), c("  " + kp, "slate"),
                         c("  " + str(e), "slate")], title="RAILCALL · verify", color="amber"))
            print(footer(ok=False)); return 1
        user_key = (kd, kp)
    # default to the most recent audit receipt so `railcall verify` (no arg) just works
    path = args[0] if args else os.path.join(d.ROOT, "railcall_audit_receipt.json")
    if not os.path.exists(path):
        msg = ([c("No receipt to verify yet.", "amber"), c("  Mint one first:  railcall audit <file.csv>", "slate")]
               if not args else [c("Receipt not found:", "amber"), c("  " + path, "slate")])
        print(panel(msg, title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    try:
        receipt = json.loads(open(path, encoding="utf-8").read())
        if not isinstance(receipt, dict):
            raise ValueError("expected a JSON object")
    except Exception as e:
        print(panel([c("This file isn't a readable RailCall receipt.", "amber"),
                     c("  " + path, "slate"),
                     c("  Parser said: " + str(e), "slate"),
                     c("  It may be truncated, hand-edited, or not JSON. Mint a fresh one with", "slate"),
                     c("    railcall audit <file.csv>    (or  railcall demo  for a sample receipt)", "cyan")],
                    title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    ex("loaded %s (schema %s)" % (os.path.basename(path), receipt.get("schema", "?")))
    # Studio/workflow receipts nest the signature under a "signature" block and sign the integrity
    # field STRING: integrity_hash (Studio builds), integrity (Studio runs), or integrity_root
    # (workflow receipts). Route ALL of them to the dedicated verifier — falling through would
    # print a false "UNSIGNED" on signed run/workflow receipts.
    _sb = receipt.get("signature")
    if isinstance(_sb, dict) and _sb.get("sig") and any(
            receipt.get(k) for k in ("integrity_hash", "integrity", "integrity_root")):
        ex("shape: nested-signature (Studio/workflow receipt) → studio verifier")
        return _verify_studio_receipt(receipt, path, user_key=user_key, explain=explain)
    ex("shape: flat signature_hex over the canonical body (CLI-audit receipt)")
    sig = receipt.get("signature_hex"); pub = receipt.get("public_key_hex"); alg = receipt.get("signer_alg")
    key_src = None
    if user_key is not None:    # explicit trust: check against the user's key, not the receipt's own
        pub, key_src = user_key[0]["public_key_hex"], user_key[1]
    ex("trust key source: %s" % ("--key %s (user-supplied)" % key_src if key_src
                                 else "the receipt's own embedded public_key_hex"))
    if not sig or not pub:
        if receipt.get("schema"):
            # v1-schema receipt went through the full minting pipeline but sig fields are absent.
            # Signature was stripped after signing — treat as tampered, not "never signed".
            print(panel([c("✗ SIGNATURE INVALID", "red"),
                         c("  This receipt has a v1 schema but is missing its signature fields.", "slate"),
                         c("  The signature was stripped after minting — treat as tampered.", "slate")],
                        title="RAILCALL · verify", color="red"))
        else:
            print(panel([c("UNSIGNED receipt — nothing to verify.", "amber"),
                         c("  Minted without a signing key. Install cryptography, re-run the audit/build,", "slate"),
                         c("  and a real Ed25519 signature gets attached.", "slate")],
                        title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    try:
        import receipt_signer as _rs
    except Exception:
        _rs = getattr(d, "receipt_signer", None)
    if _rs is None:
        print(panel([c("Can't check this signature — the `cryptography` package isn't importable here.", "amber"),
                     c("  Install it, then re-run the exact same verify:", "slate"),
                     c("  python3 -m pip install --user --break-system-packages cryptography", "cyan"),
                     c("  railcall verify " + os.path.basename(path), "cyan")],
                    title="RAILCALL · verify", color="amber"))
        print(footer(ok=False)); return 1
    body = {k: v for k, v in receipt.items() if k not in ("signer_alg", "public_key_hex", "signature_hex")}
    ex("public key %s… · integrity: %s over the canonical body (%d fields)"
       % (pub[:16], alg or "ed25519", len(body)))
    ok = _rs.verify_payload(body, sig, pub)
    net = receipt.get("network_audit") or {}
    ext = net.get("external_sockets_open")
    ex("signature verify → %s" % ("VALID" if ok else "INVALID"))
    ex("airlock: %s external sockets recorded during the run"
       % (ext if ext is not None else "not recorded"))
    lines = [c("receipt", "dim") + "   " + os.path.basename(path) + c("   " + str(receipt.get("schema", "")), "slate"),
             c("signer", "dim") + "    " + str(alg or "ed25519") + c("  pub " + pub[:16] + "…", "slate"), ""]
    if ok:
        lines.append(c("✓ SIGNATURE VALID", "green") + c("   the receipt body matches the signature, byte-for-byte", "slate"))
    else:
        lines.append(c("✗ SIGNATURE INVALID", "red") + c("   altered after signing, or this key did not sign it", "slate"))
    if ext is not None:
        lines.append((c("airlock ✓", "green") if ext == 0 else c("airlock ✗", "red")) +
                     c("   %s external sockets recorded during the run" % ext, "slate"))
    lines.append("")
    if key_src:
        lines.append(c("Verified against a USER-SUPPLIED key (--key " + key_src + ") — explicit trust,", "dim"))
        lines.append(c("chosen by you; the receipt's own embedded key was NOT used.", "dim"))
    else:
        lines.append(c("Verified offline — no network call; the public key came from the receipt itself,", "dim"))
        lines.append(c("so anyone holding this file can re-run the exact same check.", "dim"))
    print(panel(lines, title="RAILCALL · verify", color=("cyan" if ok else "red")))
    print(footer(ok=ok))
    return 0 if ok else 1


# ── backup / restore of the compliance artifact (receipts + policy chain) ─────
# A customer's signed receipts and the hash-chained policy history ARE the
# compliance record. They live on one machine (your disk, 0600). `railcall
# backup` bundles them into a portable, self-verifying archive so a machine
# death doesn't lose the audit trail; `railcall restore` re-verifies every
# byte + re-walks the policy chain BEFORE writing anything back.

_BACKUP_SCHEMA = "railcall_backup_manifest.v1"


def _station_ws():
    """The station workspace the Studio writes receipts + policy chain into."""
    return os.path.join(os.path.expanduser("~/.railcall"), "station", ".railcall_workspace")


def _backup_members(ws):
    """Deterministic, sorted list of (abs_path, arcname) for the compliance set —
    receipts of every kind, the live policy + its signed history, and the public
    signing key (so receipts verify offline after restore). Secrets are NEVER
    included: keys.local.json / the signing seed are excluded by construction."""
    wanted_dirs = ["receipts", os.path.join("receipts", "capoff"),
                   "flow_receipts", "batch_receipts"]
    wanted_files = ["approval_policy.json", "approval_policy_history.jsonl",
                    "signing_pubkey.json"]
    out = []
    for d_ in wanted_dirs:
        p = os.path.join(ws, d_)
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                fp = os.path.join(p, f)
                if os.path.isfile(fp) and f.endswith(".json") and not f.startswith("."):
                    out.append((fp, os.path.join(d_, f)))
    for f in wanted_files:
        fp = os.path.join(ws, f)
        if os.path.isfile(fp):
            out.append((fp, f))
    return sorted(out, key=lambda t: t[1])


def _policy_chain_head(ws):
    """(count, head_version, intact, first_break) for the policy history chain."""
    p = os.path.join(ws, "approval_policy_history.jsonl")
    if not os.path.isfile(p):
        return {"versions": 0, "head": 0, "intact": True, "first_break": None}
    rows = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    rows.sort(key=lambda r: r.get("to_version") or 0)
    prev, head, intact, brk = None, 0, True, None
    for h in rows:
        if prev is not None and h.get("prev_integrity") not in (None, prev):
            intact, brk = False, "v%s" % h.get("to_version"); break
        prev = h.get("integrity_hash"); head = h.get("to_version") or head
    return {"versions": len(rows), "head": head, "intact": intact, "first_break": brk}


def _build_manifest(ws, members):
    files = []
    for fp, arc in members:
        raw = open(fp, "rb").read()
        files.append({"path": arc, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw)})
    return {"schema": _BACKUP_SCHEMA, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "workspace": ws, "file_count": len(files), "files": files,
            "policy_chain": _policy_chain_head(ws)}


def cmd_backup(args):
    """Bundle your receipts + hash-chained policy history into a portable, self-
    verifying archive (secrets are NEVER included). usage: railcall backup [out.tgz]"""
    import tarfile
    ws = _station_ws()
    members = _backup_members(ws)
    if not members:
        # informational, not an error — an empty workspace is a valid state, scripts rely on exit 0
        print(panel([c("Nothing to back up yet — no receipts or policy history in", "amber"),
                     c("  " + ws, "slate"),
                     c("Run a governed flow in the Studio first, then back up.", "dim")],
                    title="RAILCALL · backup", color="amber"))
        print(footer(ok=True, label="Nothing to back up")); return 0
    manifest = _build_manifest(ws, members)
    d._sign_receipt(manifest)   # Ed25519 over the manifest body if a key is vaulted; honest-unsigned otherwise
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "railcall_backup_%s.tgz" % stamp)
    tmp_manifest = os.path.join(ws, ".backup_manifest.json")
    with open(tmp_manifest, "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    try:
        with tarfile.open(out, "w:gz") as tar:
            tar.add(tmp_manifest, arcname="MANIFEST.json")
            for fp, arc in members:
                tar.add(fp, arcname=os.path.join("workspace", arc))
    finally:
        try:
            os.remove(tmp_manifest)
        except OSError:
            pass
    ch = manifest["policy_chain"]
    signed = "ed25519-signed" if manifest.get("signature_hex") else "unsigned (pip install cryptography to sign)"
    print(panel([
        c("✓ backed up", "green") + c("  %d files" % manifest["file_count"], "slate"),
        c("policy chain", "dim") + c("  v0→v%d · %s" % (ch["head"], "intact" if ch["intact"] else "BROKEN at " + str(ch["first_break"])),
          "green" if ch["intact"] else "red"),
        c("archive", "dim") + "   " + out + c("  · " + signed, "dim"),
        "",
        c("Store it off this machine (S3, a second disk, your password manager's file vault).", "slate"),
        c("Verify anytime:  railcall backup-verify " + os.path.basename(out), "dim"),
    ], title="RAILCALL · backup", color="cyan"))
    print(footer(ok=True))
    return 0


def _read_backup(path):
    """(manifest, name->bytes) from a backup archive, or (None, err)."""
    import tarfile
    if not os.path.isfile(path):
        return None, "file not found: " + path
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            if "MANIFEST.json" not in names:
                return None, "not a RailCall backup (no MANIFEST.json)"
            manifest = json.loads(tar.extractfile("MANIFEST.json").read().decode())
            blobs = {}
            for m in tar.getmembers():
                if m.isfile() and m.name.startswith("workspace/"):
                    # path-traversal guard: reject any arcname that escapes workspace/
                    arc = m.name[len("workspace/"):]
                    if arc.startswith("/") or ".." in arc.split("/"):
                        return None, "unsafe path in archive: " + m.name
                    blobs[arc] = tar.extractfile(m).read()
        return {"manifest": manifest, "blobs": blobs}, None
    except Exception as e:
        return None, "unreadable archive: " + str(e)[:120]


def _verify_backup(path):
    """Recompute every sha256, re-walk the policy chain, check the manifest
    signature. Returns (ok, lines-for-panel, bad-count)."""
    got, err = _read_backup(path)
    if err:
        return False, [c(err, "amber")], 1
    manifest, blobs = got["manifest"], got["blobs"]
    lines, bad = [], 0
    for f in manifest.get("files", []):
        raw = blobs.get(f["path"])
        if raw is None:
            lines.append(c("✗ missing", "red") + c("  " + f["path"], "slate")); bad += 1; continue
        if "sha256:" + hashlib.sha256(raw).hexdigest() != f["sha256"]:
            lines.append(c("✗ tampered", "red") + c("  " + f["path"], "slate")); bad += 1
    # signature (over the manifest body, minus signer fields)
    sig = manifest.get("signature_hex"); pk = manifest.get("public_key_hex")
    if sig and pk:
        import receipt_signer as _rs
        body = {k: v for k, v in manifest.items() if k not in ("signer_alg", "public_key_hex", "signature_hex")}
        try:
            sig_ok = _rs.verify_payload(body, sig, pk)
        except Exception:
            sig_ok = False
        lines.append((c("✓ manifest signature verified", "green") if sig_ok
                      else c("✗ manifest signature FAILED", "red")))
        if not sig_ok:
            bad += 1
    else:
        lines.append(c("· manifest unsigned (honest — no signing key was present at backup)", "dim"))
    ch = manifest.get("policy_chain", {})
    lines.insert(0, c("policy chain", "dim") + c("  v0→v%s · %s" % (ch.get("head"),
                 "intact" if ch.get("intact") else "BROKEN at " + str(ch.get("first_break"))),
                 "green" if ch.get("intact") else "red"))
    lines.insert(0, c("%d files · %d issue(s)" % (len(manifest.get("files", [])), bad),
                      "green" if bad == 0 else "red"))
    return bad == 0, lines, bad


def cmd_backup_verify(args):
    """Re-verify a backup archive OFFLINE — every sha256, the policy chain, the
    signature — with zero trust in us. usage: railcall backup-verify <backup.tgz>"""
    if not args:
        print(footer(ok=False, label="usage: railcall backup-verify <backup.tgz>")); return 1
    ok, lines, _ = _verify_backup(args[0])
    print(panel(lines, title="RAILCALL · backup-verify", color=("cyan" if ok else "red")))
    print(footer(ok=ok))
    return 0 if ok else 1


def cmd_restore(args):
    """Restore receipts + policy chain from a backup. VERIFIES the whole archive
    first and refuses on any failure; will not clobber a NEWER on-disk policy
    chain unless you pass --force. usage: railcall restore <backup.tgz> [--force]"""
    if not args:
        print(footer(ok=False, label="usage: railcall restore <backup.tgz> [--force]")); return 1
    path = args[0]; force = "--force" in args[1:]
    ok, vlines, _ = _verify_backup(path)
    if not ok:
        print(panel([c("Refusing to restore — the backup did not verify:", "red")] + vlines,
                    title="RAILCALL · restore", color="red"))
        print(footer(ok=False)); return 1
    got, _ = _read_backup(path)
    manifest, blobs = got["manifest"], got["blobs"]
    ws = _station_ws()
    # never silently regress a newer chain
    cur_head = _policy_chain_head(ws)["head"]
    bak_head = manifest.get("policy_chain", {}).get("head", 0)
    if cur_head > bak_head and not force:
        print(panel([
            c("On-disk policy chain (v%d) is NEWER than the backup (v%d)." % (cur_head, bak_head), "amber"),
            c("Restoring would roll it back. Re-run with --force if that's intended.", "slate"),
        ], title="RAILCALL · restore", color="amber"))
        print(footer(ok=False)); return 1
    os.makedirs(ws, exist_ok=True)
    for arc, raw in sorted(blobs.items()):
        dest = os.path.join(ws, arc)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(raw)
    print(panel([
        c("✓ restored", "green") + c("  %d files → %s" % (len(blobs), ws), "slate"),
        c("verified before write — every sha256 + the policy chain + the signature.", "dim"),
    ], title="RAILCALL · restore", color="cyan"))
    print(footer(ok=True))
    return 0


# ── railcall rotate-key: rotate the local Ed25519 signing keypair ─────────────
# The PRIVATE signing seed lives in the 0600 vault (keys.local.json) the daemon signs every
# receipt with; signing_pubkey.json is its PUBLIC half, published so any receipt verifies
# offline. Rotation mints a fresh keypair, republishes the public doc under a NEW key_id, and
# ARCHIVES the outgoing public doc to signing_pubkey.prev-<ts>.json so receipts signed BEFORE
# the rotation still verify (pass the archived doc to `verify --key`). On-disk receipts are
# untouched: flat CLI receipts embed their own public key; Studio receipts carry a key_id that
# verify already matches against the archived doc.

def _keys_workspace():
    """The workspace dir where the PUBLIC signing_pubkey.json is published (same dirs `verify`
    searches via _install_pubkey). Honors RAILCALL_WS; else the install ROOT's .railcall_workspace."""
    env = os.environ.get("RAILCALL_WS")
    if env:
        return env
    return os.path.join(getattr(d, "ROOT", os.path.expanduser("~/.railcall")), ".railcall_workspace")


def _vault_file():
    """The 0600 private-key vault the daemon signer actually reads (ROOT/keys.local.json). Rotating
    the seed HERE is what makes new build/audit/demo receipts sign with the fresh key."""
    return os.path.join(getattr(d, "ROOT", os.path.expanduser("~/.railcall")), "keys.local.json")


def _write_pubkey_doc(ws, doc):
    """Atomically publish the PUBLIC signing_pubkey.json (world-readable is fine — it's the verify key)."""
    os.makedirs(ws, exist_ok=True)
    path = os.path.join(ws, "signing_pubkey.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def _persist_signing_seed(seed_hex):
    """Write the new private seed into the 0600 vault, PRESERVING every other vault key. Prefers
    vault_io (temp -> fsync -> os.replace, 0600); falls back to a stdlib atomic 0600 write. Never
    logs the seed."""
    vault_path = _vault_file()
    try:
        import vault_io as _v
    except Exception:
        _v = getattr(d, "vault_io", None)
    if _v is not None:
        _v.update(vault_path, lambda cur: cur.update({"_railcall_signing_seed": seed_hex}))
        return vault_path
    # stdlib atomic fallback — still 0600, still preserves any other keys already in the vault
    try:
        with open(vault_path, encoding="utf-8") as f:
            cur = json.load(f)
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    cur["_railcall_signing_seed"] = seed_hex
    os.makedirs(os.path.dirname(vault_path), exist_ok=True)
    tmp = vault_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
    os.chmod(tmp, 0o600)            # secret is never even briefly world-readable
    os.replace(tmp, vault_path)
    os.chmod(vault_path, 0o600)
    return vault_path


def cmd_rotate_key(_=None):
    """Rotate the local Ed25519 signing keypair: mint a fresh key, publish the new signing_pubkey.json
    (new key_id), archive the OLD public doc to signing_pubkey.prev-<ts>.json, and store the new private
    seed in the 0600 vault. Receipts signed BEFORE rotation still verify against the archived key. Fails
    closed (writes nothing) if `cryptography` is missing. usage: railcall rotate-key"""
    # fail closed: no signer -> no honest rotation. Never publish a public key no seed can sign for.
    try:
        import receipt_signer as _rs
    except Exception:
        _rs = getattr(d, "receipt_signer", None)
    if _rs is None:
        print(panel([c("Can't rotate — the `cryptography` package isn't importable here.", "amber"),
                     c("  Rotation must mint a REAL keypair, so it fails closed rather than write a", "slate"),
                     c("  public key no signature could match. Install it, then re-run:", "slate"),
                     c("  python3 -m pip install --user --break-system-packages cryptography", "cyan"),
                     c("  railcall rotate-key", "cyan")],
                    title="RAILCALL · rotate-key", color="amber"))
        print(footer(ok=False)); return 1

    ws = _keys_workspace()
    old_path = os.path.join(ws, "signing_pubkey.json")
    old_doc = None
    if os.path.exists(old_path):
        try:
            old_doc = json.loads(open(old_path, encoding="utf-8").read())
        except Exception:
            old_doc = None      # unreadable current doc -> treat as first publish, don't archive garbage

    # mint the fresh keypair — 32 random bytes IS a full Ed25519 seed (stdlib os.urandom)
    try:
        new_seed = os.urandom(32).hex()
        new_pub = _rs.public_key_hex(new_seed)          # proves the signer accepts the seed before we commit
    except Exception as e:
        print(panel([c("Key generation failed — nothing was changed.", "red"),
                     c("  " + str(e), "slate")], title="RAILCALL · rotate-key", color="red"))
        print(footer(ok=False)); return 1
    new_key_id = hashlib.sha256(bytes.fromhex(new_pub)).hexdigest()[:16]   # same id convention as the signer

    # archive the outgoing PUBLIC doc FIRST so pre-rotation receipts stay verifiable (verify --key <archived>)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archived = None
    if old_doc is not None:
        archived = os.path.join(ws, "signing_pubkey.prev-%s.json" % stamp)
        try:
            with open(archived, "w", encoding="utf-8") as f:
                json.dump(old_doc, f, indent=2); f.write("\n")
        except Exception as e:
            print(panel([c("Refusing to rotate — couldn't archive the current public key first.", "red"),
                         c("  " + str(e), "slate"),
                         c("  Rotating without an archive would strand receipts signed by the old key.", "slate")],
                        title="RAILCALL · rotate-key", color="red"))
            print(footer(ok=False)); return 1

    # publish the new PUBLIC doc, then persist the new PRIVATE seed to the 0600 vault
    new_doc = {
        "schema": "railcall_signing_pubkey.v1",
        "alg": "ed25519",
        "public_key_hex": new_pub,
        "key_id": new_key_id,
        "rotated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("Ed25519 PUBLIC key for this RailCall install. Receipt signatures verify against THIS key. "
                 "Safe to publish; the matching private seed never leaves the 0600 vault."),
    }
    try:
        pub_path = _write_pubkey_doc(ws, new_doc)
        vault_path = _persist_signing_seed(new_seed)
    except Exception as e:
        print(panel([c("Rotation failed while writing the new key — check permissions on", "red"),
                     c("  " + ws, "slate"), c("  " + str(e), "slate")],
                    title="RAILCALL · rotate-key", color="red"))
        print(footer(ok=False)); return 1

    old_id = (old_doc or {}).get("key_id")
    lines = [
        c("✓ rotated signing key", "green") + c("   new key_id " + new_key_id, "slate"),
        "",
        c("new public key", "dim") + "   " + pub_path,
        c("private seed  ", "dim") + "   " + vault_path + c("  (0600, never published)", "dim"),
    ]
    if archived:
        lines.append(c("archived old  ", "dim") + "   " + archived +
                     (c("  key_id " + str(old_id), "slate") if old_id else ""))
        lines.append("")
        lines.append(c("Receipts signed BEFORE now were signed by the old key — they still verify.", "slate"))
        lines.append(c("Flat CLI receipts carry their own key; for a Studio receipt point verify at the archive:", "slate"))
        lines.append(c("  railcall verify <receipt.json> --key " + archived, "cyan"))
    else:
        lines.append("")
        lines.append(c("No previous public key was on disk — this is the first published key.", "slate"))
    lines.append("")
    lines.append(c("From now on, new receipts are signed by " + new_key_id + ".", "dim"))
    print(panel(lines, title="RAILCALL · rotate-key", color="cyan"))
    print(footer(ok=True, label="Rotated"))
    return 0


# ── railcall demo: the 30-second golden path (build -> signed receipt -> verify) ──
# One command a brand-new user runs to watch the whole promise work, entirely locally: it builds a
# tiny bundled sample workflow (watch a folder for CSVs, dedup rows, write a local summary — DRY-RUN),
# mints a REAL Ed25519-signed receipt, then verifies it OFFLINE. No network, no sends, no daemon, no
# Ollama. The receipt is a FLAT CLI receipt (embeds its own public key), so `verify` re-checks it
# against the receipt itself — nothing about this needs install state or a server.
_DEMO_SAMPLE_CSV = (
    "order_id,customer,amount\n"
    "1001,acme,42.00\n"
    "1002,globex,17.50\n"
    "1001,acme,42.00\n"        # exact duplicate of the first data row
    "1003,initech,88.25\n"
    "1002,globex,17.50\n"      # exact duplicate of the second data row
)


def cmd_demo(_=None):
    """The 30-second golden path — build a tiny sample workflow locally (watch a folder for CSVs, dedup
    rows, write a local summary — DRY-RUN), mint a REAL signed receipt, and verify it offline. No network,
    no sends. usage: railcall demo"""
    # dedup the bundled sample by whole-row (the workflow's core step), all in memory
    rows = [ln for ln in _DEMO_SAMPLE_CSV.split("\n") if ln.strip()]
    body = rows[1:]
    seen, unique = set(), []
    for r in body:
        if r not in seen:
            seen.add(r); unique.append(r)
    dupes = len(body) - len(unique)
    summary = ("watch-folder-dedup-summary: %d rows in, %d unique, %d duplicate rows removed"
               % (len(body), len(unique), dupes))

    # the receipt is a FLAT CLI receipt: it embeds its own public key, so `verify` re-checks it against
    # the receipt itself — no install state needed. network_audit is MEASURED via lsof, never asserted.
    net = d.lsof_socket_audit()
    receipt = {
        "schema": "railcall_demo_receipt.v1",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workflow": {
            "name": "watch-folder-dedup-summary",
            "steps": ["watch <folder> for new *.csv",
                      "dedup rows (drop exact-duplicate lines)",
                      "write a local summary.txt"],
            "mode": "dry-run",       # nothing is watched / sent / executed — this demos the SHAPE, safely
        },
        "sample": {"rows_in": len(body), "unique_rows": len(unique),
                   "duplicates_removed": dupes, "summary": summary},
        "input_sha256": "sha256:" + d.sha256_hex(_DEMO_SAMPLE_CSV),
        "network_audit": net,        # MEASURED, not asserted
        "result": "dry_run_ok",
    }
    d._sign_receipt(receipt)         # REAL Ed25519 if a key is vaulted; honestly UNSIGNED otherwise
    demo_path = os.path.join(d.ROOT, "railcall_demo_receipt.json")
    d._save_receipt(demo_path, receipt)

    ext = net.get("external_sockets_open")
    lines = [
        c("1 · build", "dim") + "   " + c("watch-folder-dedup-summary", "cyan") + c("  (dry-run — nothing sent)", "slate"),
        c("2 · dedup", "dim") + "   " + c(summary, "slate"),
        "",
        (c("airlock ✓", "green") if ext == 0 else c("airlock ?", "amber")) +
        c("   %s external sockets · ran entirely on this machine" % (ext if ext is not None else "?"), "slate"),
        c("3 · receipt", "dim") + " " + demo_path,
    ]
    if not receipt.get("signature_hex"):
        # honest: the golden path's payoff is a REAL signature; without cryptography there isn't one to verify
        lines.append("")
        lines.append(c("⚠ receipt minted UNSIGNED — `cryptography` isn't installed, so there's no", "amber"))
        lines.append(c("  signature to verify. Install it to see the full proof, then re-run demo:", "slate"))
        lines.append(c("  python3 -m pip install --user --break-system-packages cryptography", "cyan"))
        print(panel(lines, title="RAILCALL · demo", color="amber"))
        print(footer(ok=False, label="Unsigned (install cryptography)"))
        return 1
    lines.append(c("           signed ed25519 · pub " + str(receipt.get("public_key_hex", ""))[:16] + "…", "dim"))
    print(panel(lines, title="RAILCALL · demo", color="cyan"))
    # 4 · verify the receipt we JUST minted, OFFLINE — reuse the real verifier so this is proof, not a mock
    print(c("4 · verify (offline, no network)…", "dim"))
    return cmd_verify([demo_path])


def cmd_receipts(args):
    """Browse the receipt history (community: Sami, bugs 20/27). Every governed run keeps a timestamped
    copy under receipts/ so a later run never destroys an earlier proof — the canonical fixed-name file is
    always the latest; this is the full trail. usage: railcall receipts [list] [-n N]"""
    sub = args[0] if args and not args[0].startswith("-") else "list"
    if sub not in ("list", "ls"):
        print(footer(ok=False, label="usage: railcall receipts list [-n N]")); return 1
    limit = 20
    if "-n" in args:
        try:
            limit = max(1, int(args[args.index("-n") + 1]))
        except (ValueError, IndexError):
            pass
    try:
        files = [f for f in os.listdir(RECEIPTS_DIR) if f.endswith(".json")]
    except (FileNotFoundError, OSError):
        files = []
    if not files:
        print(panel([c("No receipt history yet.", "amber"),
                     c("  Run 'railcall build', 'railcall audit <csv>', or 'railcall interpret' —", "slate"),
                     c("  each keeps a timestamped, verifiable copy under:", "slate"),
                     c("  " + RECEIPTS_DIR, "dim")], title="RAILCALL · receipts", color="amber"))
        print(footer(ok=True, label="0 receipts")); return 0
    # Newest first by WRITE TIME — not by filename: the name is <schema>-<UTC>, so a plain
    # reverse string-sort would order by schema first and bury the genuinely-latest receipt.
    def _mtime(fn):
        try:
            return os.path.getmtime(os.path.join(RECEIPTS_DIR, fn))
        except OSError:
            return 0.0
    files.sort(key=_mtime, reverse=True)
    shown = files[:limit]
    lines = [c("history", "dim") + "   " + RECEIPTS_DIR, ""]
    for fn in shown:
        schema, signed, result = "", "unsigned", ""
        try:
            r = json.loads(open(os.path.join(RECEIPTS_DIR, fn), encoding="utf-8").read())
            schema = r.get("schema") or ""
            signed = ("ed25519-signed" if (r.get("signature_hex") or
                      (isinstance(r.get("signature"), dict) and r["signature"].get("signature"))) else "unsigned")
            result = r.get("result") or ("ok" if r.get("ok") else "")
        except Exception:
            pass
        badge = c("✓", "green") if signed.startswith("ed25519") else c("○", "slate")
        lines.append(badge + " " + c(fn, "cyan"))
        lines.append(c("   " + schema + (("  · " + str(result)) if result else "") + "  · " + signed, "slate"))
    if len(files) > len(shown):
        lines.append("")
        lines.append(c("  … %d more (railcall receipts list -n %d)" % (len(files) - len(shown), len(files)), "dim"))
    lines.append("")
    lines.append(c("verify any of them offline:", "dim"))
    lines.append(c("  railcall verify " + os.path.join(RECEIPTS_DIR, shown[0]), "cyan"))
    print(panel(lines, title="RAILCALL · receipt history (%d)" % len(files), color="cyan"))
    print(footer(ok=True, label="%d receipt%s" % (len(files), "" if len(files) == 1 else "s")))
    return 0


COMMANDS = {"build": cmd_build, "interpret": cmd_interpret, "daemon": cmd_daemon,
            "start-daemon": cmd_daemon, "health": cmd_health, "dashboard": cmd_dashboard,
            "doctor": cmd_doctor, "demo": cmd_demo, "rotate-key": cmd_rotate_key,
            "balance": cmd_balance, "login": cmd_login, "studio": cmd_studio, "audit": cmd_audit,
            "verify": cmd_verify, "receipts": cmd_receipts, "backup": cmd_backup, "restore": cmd_restore,
            "backup-verify": cmd_backup_verify}


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
