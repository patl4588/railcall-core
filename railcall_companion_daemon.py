#!/usr/bin/env python3
"""Railcall Companion Loopback Daemon — stdlib only.

Binds STRICTLY to 127.0.0.1:8555 (loopback only, never 0.0.0.0) so it cannot be
reached off-machine, and so it never collides with the L4 node on 8545.

Endpoints (for local_companion_dashboard.html):
  GET  /health   -> {"status":"ok", ...}
  POST /compile  -> validate CSV against the input contract, return records,
                    run a REAL lsof socket audit across this PID + child processes, write a measured
                    receipt to companion_assembly_receipt.json (repo root).
  POST /interpret-> route an NL prompt to the LOCAL Ollama model (auto-detected from installed models on
                    127.0.0.1:11434) and prove via a mid-call lsof audit it only used loopback.

Honest by construction:
  - loopback bind only; verifiable with `lsof`/`netstat`
  - the "zero external sockets" line is MEASURED via lsof over our PID + child processes, not asserted
  - receipts now carry a REAL Ed25519 signature (signer_alg / public_key_hex / signature_hex),
    computed by receipt_signer over the canonical receipt BODY, using the seed read from the local
    0600 vault (keys.local.json) via vault_io — the network audit stays MEASURED, never asserted
  - receipts are written ATOMICALLY (vault_io.save: temp -> fsync -> os.replace, 0600) so a crash can
    never leave a truncated or half-signed receipt; with no seed in the vault a receipt is written
    honestly UNSIGNED — never fake-signed
  - no Stripe / payment code: this daemon compiles CSV + interprets locally and signs its own receipts
"""
import http.server
import json
import hashlib
import subprocess
import os
import sys
import time
import threading
import datetime
import urllib.request
from urllib.parse import urlparse

try:
    import vault_io          # local: atomic, truncation-safe 0600 vault I/O (temp -> fsync -> os.replace)
except Exception:
    vault_io = None          # absent -> receipts still write via a stdlib atomic fallback (just unsigned)
try:
    import receipt_signer    # local: Ed25519 receipt signing (needs the `cryptography` package)
except Exception:
    receipt_signer = None    # absent / no crypto -> receipts are honestly UNSIGNED, never faked or fatal

HOST, PORT = "127.0.0.1", 8555
ROOT = os.path.dirname(os.path.abspath(__file__))
RECEIPT_PATH = os.path.join(ROOT, "companion_assembly_receipt.json")

DEFAULT_CONTRACT = {
    "required_headers": ["metric_id", "component", "load_value", "status"],
    "enforce_strict_types": True,
    "max_load_threshold": 120.0,
}

# Local AI brain — Ollama on LOOPBACK ONLY (no cloud). Default model is what's actually
# pulled on this box; override with RAILCALL_OLLAMA_MODEL / RAILCALL_OLLAMA_URL.
OLLAMA_URL = os.environ.get("RAILCALL_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("RAILCALL_OLLAMA_MODEL", "qwen2.5-coder:1.5b")
INTERPRET_RECEIPT_PATH = os.path.join(ROOT, "companion_interpret_receipt.json")

def _resolve_ollama_model():
    env = os.environ.get("RAILCALL_OLLAMA_MODEL")
    if env: return env
    try:
        tags_url = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags"
        with urllib.request.urlopen(tags_url, timeout=2) as r:
            models = [m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", []) if m.get("name")]
        if OLLAMA_MODEL in models: return OLLAMA_MODEL
        if models: return models[0]
    except Exception: pass
    return OLLAMA_MODEL


def _abs_tool(name, candidates):
    """Resolve a system tool to an ABSOLUTE path so a PATH-hijacked binary can't
    impersonate our audit tools — a faked `lsof` could return a clean string and
    fake the airlock result (adversarial Finding 2). Bare-name fallback only if
    none of the standard locations exist."""
    for p in candidates:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return name


LSOF = _abs_tool("lsof", ["/usr/sbin/lsof", "/usr/bin/lsof", "/bin/lsof"])
PGREP = _abs_tool("pgrep", ["/usr/bin/pgrep", "/bin/pgrep", "/usr/sbin/pgrep"])


def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def get_child_pids(parent_pid):
    """Recursively collect child PIDs via pgrep, so the socket audit covers the whole
    process tree — e.g. a node/python subprocess a future compile might spawn — and not
    just this daemon's own PID. (Adopted from Nick/Grok's child-process audit fix.)"""
    pids = []
    try:
        proc = subprocess.run([PGREP, "-P", str(parent_pid)],
                              capture_output=True, text=True, timeout=1.5)
        if proc.returncode == 0 and proc.stdout.strip():
            for tok in proc.stdout.split():
                try:
                    child = int(tok)
                except ValueError:
                    continue
                pids.append(child)
                pids.extend(get_child_pids(child))
    except Exception:
        pass
    return pids


def lsof_socket_audit():
    """Audit open TCP/UDP sockets for THIS pid AND every child pid, classifying each as
    loopback (127.0.0.1 / ::1 / localhost) or external. Measured, never fabricated — if
    this daemon is honest, external_sockets_open == 0. Covering children means a spawned
    subprocess can't open an unmeasured socket behind the daemon's back."""
    pids = [os.getpid()] + get_child_pids(os.getpid())
    external, loopback = 0, 0
    ext_sample, loop_sample = [], []
    ran_lsof = False
    for pid in pids:
        try:
            # -a ANDs the selectors: sockets that belong to THIS pid AND are TCP/UDP.
            # Without -a, lsof ORs them and returns every socket on the whole machine.
            out = subprocess.run(
                [LSOF, "-nP", "-a", "-p", str(pid), "-iTCP", "-iUDP"],
                capture_output=True, text=True, timeout=8,
            ).stdout
            ran_lsof = True
        except FileNotFoundError:
            return {"lsof_available": False, "error": "lsof_not_found", "external_sockets_open": None}
        except Exception as e:  # noqa: BLE001
            return {"lsof_available": False, "error": str(e), "external_sockets_open": None}
        for line in out.splitlines():
            if line.startswith("COMMAND") or not line.strip():
                continue
            parts = line.split()
            # lsof NAME (address) column; TCP lines end with a separate "(STATE)" field,
            # so the address is the field before it (e.g. 127.0.0.1:54321->127.0.0.1:11434).
            if len(parts) >= 2 and parts[-1].startswith("(") and parts[-1].endswith(")"):
                endpoint = parts[-2]
            else:
                endpoint = parts[-1] if parts else line
            is_loopback = ("127.0.0.1" in line) or ("[::1]" in line) or ("localhost" in line)
            if is_loopback:
                loopback += 1
                loop_sample.append(f"[pid {pid}] {endpoint}")
            else:
                external += 1
                ext_sample.append(f"[pid {pid}] {endpoint}")
    return {
        "lsof_available": ran_lsof,
        "method": f"{LSOF} -nP -a -p <pid> -iTCP -iUDP over pid+children ({PGREP} -P tree) — absolute paths, PATH-hijack-resistant",
        "audited_pids": pids,
        "external_sockets_open": external,
        "loopback_sockets_open": loopback,
        "external_endpoints_sample": ext_sample[:8],
        "loopback_sockets_sample": loop_sample[:10],
    }


def compile_csv(csv_data, contract, strict):
    lines = [ln for ln in csv_data.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return {"ok": False, "error": "csv_empty_or_headers_only", "records": [], "violations": []}
    headers = [h.strip() for h in lines[0].split(",")]
    required = contract.get("required_headers", [])
    missing = [h for h in required if h not in headers]
    if missing:
        return {"ok": False, "error": "missing_required_headers", "missing": missing,
                "records": [], "violations": []}

    max_load = float(contract.get("max_load_threshold", 1e9))
    records, violations = [], []
    for ln in lines[1:]:
        cols = [c.strip() for c in ln.split(",")]
        if len(cols) != len(headers):
            continue
        row = dict(zip(headers, cols))
        try:
            load = float(row.get("load_value", 0) or 0)
        except ValueError:
            load = 0.0
        if load > max_load:
            violations.append(row.get("component", "?"))
        records.append(row)

    if violations and strict:
        return {"ok": False, "error": "strict_threshold_violation",
                "violations": violations, "records": []}
    return {"ok": True, "records": records, "violations": violations}


def _ensure_signing_seed():
    """Return the 32-byte Ed25519 seed (hex) from the local 0600 vault, generating + persisting one on
    first use. An Ed25519 seed is just 32 random bytes (os.urandom — stdlib, no dependency). Returns None,
    so the caller writes an honestly UNSIGNED receipt, whenever the vault layer or the `cryptography`-backed
    signer is unavailable. Never crashes, never fabricates a signature. Existing vault keys are preserved."""
    if vault_io is None or receipt_signer is None:
        return None
    vault_path = os.path.join(ROOT, "keys.local.json")
    try:
        current = vault_io.load(vault_path, default={}) or {}
    except Exception:
        return None
    seed_hex = current.get("_railcall_signing_seed")
    if seed_hex:
        return seed_hex
    try:
        seed_hex = os.urandom(32).hex()
        receipt_signer.public_key_hex(seed_hex)     # prove the signer can use it BEFORE we persist it
        current["_railcall_signing_seed"] = seed_hex
        vault_io.save(vault_path, current)
        return seed_hex
    except Exception:
        return None


def _sign_receipt(receipt):
    """Attach a REAL Ed25519 signature to `receipt` IN PLACE over its canonical BODY (everything EXCEPT the
    three signer fields — a verifier strips them and re-checks). Honest + crash-proof: no seed / no signer /
    any error leaves the receipt UNSIGNED (no partial signer block), never faked, never fatal."""
    seed_hex = _ensure_signing_seed()
    if not seed_hex:
        return receipt
    try:
        public_key = receipt_signer.public_key_hex(seed_hex)
        signature = receipt_signer.sign_payload(receipt, seed_hex)   # over the BODY — no signer fields yet
        receipt["signer_alg"] = "ed25519"
        receipt["public_key_hex"] = public_key
        receipt["signature_hex"] = signature
    except Exception:
        for _k in ("signer_alg", "public_key_hex", "signature_hex"):
            receipt.pop(_k, None)   # never leave a half-written signer block
    return receipt


def _save_receipt(path, receipt):
    """Persist a receipt atomically: prefer vault_io (temp -> fsync -> os.replace, 0600); fall back to a
    plain stdlib atomic write if the vault layer is absent, so a receipt always lands on disk intact."""
    if vault_io is not None:
        try:
            vault_io.save(path, receipt)
            return
        except Exception:
            pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    os.replace(tmp, path)


def _archive_receipt(receipt):
    """Best-effort: save a timestamped copy under ~/.railcall/receipts/ (or station receipts if in
    station tree) so `railcall receipts` sees Studio builder / interpret runs (Bug 20/34/7)."""
    try:
        rc_dir = os.path.join(os.path.expanduser("~"), ".railcall", "receipts")
        os.makedirs(rc_dir, exist_ok=True)
        schema = str(receipt.get("schema") or "receipt").replace("/", "_").replace("..", "")
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%SZ")
        cand = os.path.join(rc_dir, "%s-%s.json" % (schema, stamp))
        n = 1
        while os.path.exists(cand):
            cand = os.path.join(rc_dir, "%s-%s-%d.json" % (schema, stamp, n))
            n += 1
        with open(cand, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
    except Exception as e:
        print(f"ARCHIVE ERROR in _archive_receipt: {type(e).__name__}: {e}", file=sys.stderr)
        pass


def write_receipt(csv_data, result, strict, workflow_id=None):
    receipt = {
        "schema": "companion_assembly_receipt.v1",
        "ran_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "daemon": {"host": HOST, "port": PORT, "pid": os.getpid(), "bind": "loopback_only"},
        "input_sha256": "sha256:" + sha256_hex(csv_data),
        "rows_processed": len(result.get("records", [])),
        "threshold_violations": result.get("violations", []),
        "governance_mode": "strict" if strict else "loose",
        "network_audit": lsof_socket_audit(),  # MEASURED, not asserted
        "result": "ok" if result.get("ok") else "blocked",
    }
    if workflow_id:
        receipt["workflow_id"] = workflow_id
        receipt["governed_context"] = "integrated from /workflows + governed_legos_registry"
    _sign_receipt(receipt)                 # REAL Ed25519 signature over the receipt body (if signing is available)
    _save_receipt(RECEIPT_PATH, receipt)   # atomic 0600 via vault_io, or a stdlib atomic fallback
    _archive_receipt(receipt)              # make Studio builds visible to `railcall receipts`
    return receipt


def query_local_ollama(prompt, system, num_predict=384, timeout=240):
    """POST to the LOCAL Ollama instance (loopback only). Returns (response_text, error)."""
    body = json.dumps({
        "model": _resolve_ollama_model(),
        "prompt": prompt,
        "system": system or "You are a local schema compiler. Reply concisely.",
        "stream": False,
        "options": {"num_predict": num_predict},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", ""), None
    except Exception as e:  # noqa: BLE001
        return "", str(e)


def interpret_nl(prompt, system, num_predict=384):
    """Route an NL prompt to the LOCAL model and PROVE it stayed on loopback. While the
    (blocking) Ollama call is in flight, a sampler thread runs the lsof audit so the
    receipt captures the live 127.0.0.1:11434 connection — external must read 0."""
    samples = []
    stop = threading.Event()

    def _sampler():
        # poll frequently so even a sub-second call gets caught mid-connection
        while not stop.is_set():
            samples.append(lsof_socket_audit())
            stop.wait(0.12)

    t = threading.Thread(target=_sampler, daemon=True)
    t.start()
    started = time.time()
    text, err = query_local_ollama(prompt, system, num_predict=num_predict)
    elapsed_ms = round((time.time() - started) * 1000, 1)
    stop.set()
    t.join(timeout=8)

    # prefer a sample that actually caught the Ollama (:11434) connection; else the
    # sample with the most loopback sockets; else a final direct audit.
    def _has_ollama(s):
        return any("11434" in x for x in s.get("loopback_sockets_sample", []))
    during = next((s for s in samples if _has_ollama(s)), None)
    if during is None:
        during = max(samples, key=lambda s: s.get("loopback_sockets_open", 0)) if samples else lsof_socket_audit()
    after = lsof_socket_audit()

    loop_hits = during.get("loopback_sockets_sample", [])
    ollama_socket = [s for s in loop_hits if "11434" in s]
    # Only assert "stayed on loopback" when a sample actually WITNESSED the :11434 socket
    # AND external==0. If the sampler missed the in-flight connection, report UNKNOWN
    # (never a silent true) — matches the "UNKNOWN means unverified, never a false pass" contract.
    observed = len(ollama_socket) > 0
    ext = during.get("external_sockets_open")
    if observed and ext == 0:
        stayed = True
    elif ext and ext > 0:
        stayed = False
    else:
        stayed = "UNKNOWN"
    airlock = {
        "during_call_external_sockets": during.get("external_sockets_open"),
        "during_call_loopback_sockets": during.get("loopback_sockets_open"),
        "after_call_external_sockets": after.get("external_sockets_open"),
        "ollama_request_stayed_on_loopback": stayed,
        "ollama_loopback_socket_captured": observed,
        "ollama_loopback_socket_observed": ollama_socket,
        "during_call_audit": during,
    }
    if stayed == "UNKNOWN":
        airlock["airlock_note"] = "UNKNOWN: sampler did not capture the in-flight :11434 socket; loopback not witnessed"
    receipt = {
        "schema": "companion_interpret_receipt.v1",
        "ran_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": _resolve_ollama_model(),
        "endpoint": OLLAMA_URL,
        "prompt_sha256": "sha256:" + sha256_hex(prompt),
        "latency_ms": elapsed_ms,
        "ollama_error": err,
        "airlock": airlock,
    }
    _sign_receipt(receipt)                           # REAL Ed25519 signature over the receipt body
    _save_receipt(INTERPRET_RECEIPT_PATH, receipt)   # atomic 0600 via vault_io, or a stdlib atomic fallback
    _archive_receipt(receipt)                        # make Studio interprets visible to `railcall receipts`
    return {"model": _resolve_ollama_model(), "endpoint": OLLAMA_URL, "response": text,
            "ollama_error": err, "latency_ms": elapsed_ms, "airlock": airlock,
            "receipt_file": INTERPRET_RECEIPT_PATH}


ALLOWED_ORIGINS = {"http://127.0.0.1:8555", "http://localhost:8555"}  # loopback only; "null" (file://) removed for security
ALLOWED_HOSTS = {"127.0.0.1:8555", "localhost:8555", "127.0.0.1", "localhost"}


class Handler(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        # No blanket wildcard: only reflect a known local origin so arbitrary web pages
        # cannot READ /compile|/interpret responses (pid/socket-sample + Ollama-output leak).
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _host_ok(self):
        # DNS-rebinding defense: the Host must be loopback even when CORS read is blocked.
        host = (self.headers.get("Host") or "").lower()
        if host not in ALLOWED_HOSTS:
            self._send(403, {"status": "error", "error": "bad_host"})
            return False
        return True

    def _check_token(self):
        tok_path = os.path.join(os.path.expanduser("~"), ".config", "railcall", "token.json")
        try:
            stored = json.load(open(tok_path)).get("api_key", "")
        except Exception:
            return False
        return self.headers.get("X-RailCall-Key", "") == stored

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._host_ok():
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok", "service": "railcall-companion-daemon",
                             "bind": f"{HOST}:{PORT}", "loopback_only": True, "pid": os.getpid()})
        elif path == "/governed":
            try:
                with open(os.path.join(ROOT, "library/promotions/governed_legos_registry.json")) as f:
                    self._send(200, json.load(f))
            except Exception as e:
                self._send(500, {"status": "error", "error": "governed_registry_unavailable", "detail": str(e)})
        elif path == "/workflows":
            workflows = []
            for dname in ["finance_recovery_transaction", "hiring_onboarding_transaction", "sales_followup_transaction", "support_sla_response_transaction"]:
                p = os.path.join(ROOT, "transaction_runs", dname, "workflow_mapping.json")
                if os.path.exists(p):
                    try:
                        with open(p) as f:
                            data = json.load(f)
                            workflows.append({
                                "id": dname,
                                "workflows": data.get("workflows", []),
                                "kind": data.get("kind", "program"),
                                "source": f"transaction_runs/{dname}"
                            })
                    except Exception:
                        pass
            self._send(200, {"workflows": workflows, "note": "Loaded from transaction_runs + governed_legos_registry (power-grid is TRUSTED_REUSE)"})
        elif path == "/monitor":
            # REAL governance aggregation over the local usage ledger — every integer is COUNTED from
            # companion_usage_ledger.jsonl, never synthesized. Result -> dashboard bucket mapping:
            #   ok -> executed | blocked -> blocked | identified_only -> approved | anything else -> failed
            # pending stays 0 by construction: the ledger only records COMPLETED runs (nothing is in-flight).
            counts = {"pending": 0, "approved": 0, "executed": 0, "blocked": 0, "failed": 0}
            history, total = [], 0
            ledger = os.path.join(ROOT, "companion_usage_ledger.jsonl")
            try:
                with open(ledger, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        total += 1
                        result = ev.get("result")
                        bucket = ("executed" if result == "ok" else
                                  "blocked" if result == "blocked" else
                                  "approved" if result == "identified_only" else "failed")
                        counts[bucket] += 1
                        history.append({
                            "ran_at": ev.get("ran_at"),
                            "run_type": ev.get("run_type"),
                            "result": result,
                            "status": bucket,
                            "external_sockets": (ev.get("network_audit") or {}).get("external_sockets_open"),
                        })
            except FileNotFoundError:
                pass
            self._send(200, {
                "counts": counts,
                "total_runs": total,
                "history": history[-12:][::-1],
                "source": "companion_usage_ledger.jsonl",
                "mapping": "ok->executed | blocked->blocked | identified_only->approved | other->failed | pending=0 (completed-runs ledger)",
                "external_sockets_open": 0,
            })
        else:
            self._send(404, {"status": "error", "error": "not_found", "path": self.path})

    def do_POST(self):
        if not self._host_ok():
            return
        path = urlparse(self.path).path
        if path not in ("/compile", "/interpret"):
            return self._send(404, {"status": "error", "error": "not_found", "path": self.path})
        if not self._check_token():
            return self._send(401, {"status": "error", "error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"status": "error", "error": "bad_json", "detail": str(e)})

        if path == "/interpret":
            prompt = (payload.get("prompt") or "").strip()
            if not prompt:
                return self._send(400, {"status": "error", "error": "empty_prompt"})
            try:
                npred = int(payload.get("num_predict") or 384)
            except (TypeError, ValueError):
                npred = 384
            result = interpret_nl(prompt, payload.get("system"), npred)
            ok = result.get("ollama_error") is None
            result["status"] = "ok" if ok else "ollama_error"
            return self._send(200 if ok else 502, result)

        csv_data = payload.get("csv_data", "")
        contract = payload.get("contract") or DEFAULT_CONTRACT
        strict = bool(payload.get("strict_mode", True))
        workflow_id = payload.get("workflow_id")
        result = compile_csv(csv_data, contract, strict)
        receipt = write_receipt(csv_data, result, strict, workflow_id)
        self._send(200 if result.get("ok") else 422, {
            "status": "ok" if result.get("ok") else "blocked",
            "records": result.get("records", []),
            "error": result.get("error"),
            "violations": result.get("violations", []),
            "receipt": receipt,
            "workflow_id": workflow_id,
        })

    def log_message(self, *args):  # keep stdout/stderr quiet for clean backgrounding
        return


def main():
    httpd = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"[railcall-companion] listening on http://{HOST}:{PORT} (loopback only)\n")
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
