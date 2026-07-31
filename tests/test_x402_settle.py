#!/usr/bin/env python3
"""End-to-end x402 CDP settle tests against a MOCK facilitator (no real funds, no Coinbase call).

Proves: real verify->settle records a settled (dryrun=0) payment with the tx hash; the CDP Bearer JWT is
attached; the mainnet gate 403s without the audit flag and passes with it; an unreachable facilitator 502s
and settles nothing; dry-run (no facilitator) is preserved. Run: python3 test_x402_settle.py
"""
import base64, os, re, json, time, threading, subprocess, urllib.request, urllib.error, sys, signal
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GW_PORT, FAC_PORT = 8180, 8199


def _throwaway_cdp_secret():
    """A generated Ed25519 keypair in CDP's 64-byte format (32B seed + 32B pubkey,
    base64). The JWT tests only need A valid signing key — the facilitator is a
    mock — so no real credential or machine-specific .env is required."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    seed = k.private_bytes(serialization.Encoding.Raw,
                           serialization.PrivateFormat.Raw,
                           serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw,
                                      serialization.PublicFormat.Raw)
    return base64.b64encode(seed + pub).decode()


# Portable: real CDP creds are OPTIONAL (export CDP_API_KEY_NAME/CDP_API_KEY_SECRET
# to exercise them); default is a throwaway keypair so the test runs anywhere.
CDP = {"CDP_API_KEY_NAME": os.environ.get("CDP_API_KEY_NAME") or "test-key-%d" % os.getpid(),
       "CDP_API_KEY_SECRET": os.environ.get("CDP_API_KEY_SECRET") or _throwaway_cdp_secret()}

# ── mock CDP facilitator ─────────────────────────────────────────────────────
STATE = {"auth_seen": None, "verify_valid": True, "settle_ok": True}
class Fac(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        STATE["auth_seen"] = self.headers.get("Authorization")
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.endswith("/verify"):
            out = {"isValid": STATE["verify_valid"], "invalidReason": None if STATE["verify_valid"] else "bad-sig"}
        else:
            out = ({"success": True, "transaction": "0xMOCKTESTNETTXHASH0001", "payer": "0xPAYER0001"}
                   if STATE["settle_ok"] else {"success": False, "errorReason": "insufficient_funds"})
        b = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

fac = HTTPServer(("127.0.0.1", FAC_PORT), Fac)
threading.Thread(target=fac.serve_forever, daemon=True).start()

# ── helpers ──────────────────────────────────────────────────────────────────
def POST(path, body, hdrs=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (GW_PORT, path),
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(hdrs or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

_port = [GW_PORT]
def start_gateway(extra_env):
    global GW_PORT
    _port[0] += 1; GW_PORT = _port[0]        # fresh port per boot — sidesteps TIME_WAIT races
    db = os.path.join(HERE, "railcall_consumers.db")   # the real DB_PATH (cwd-relative); reset per boot
    if os.path.exists(db): os.remove(db)
    env = {**os.environ, "X402_ENABLED": "1", "RAILCALL_LOCAL_ADMIN": "1", "PORT": str(GW_PORT),
           "CDP_API_KEY_NAME": CDP["CDP_API_KEY_NAME"], "CDP_API_KEY_SECRET": CDP["CDP_API_KEY_SECRET"],
           **extra_env}
    p = subprocess.Popen([sys.executable, "cloud_gateway.py"], cwd=HERE, env=env,
                         stdout=open(os.path.join(HERE, "gw_test.log"), "w"), stderr=subprocess.STDOUT)
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % GW_PORT, timeout=1); break
        except Exception: time.sleep(0.25)
    return p

def stop(p):
    p.send_signal(signal.SIGTERM)
    try: p.wait(timeout=5)
    except Exception: p.kill()

def make_agent():
    _, su = POST("/v1/auth/signup", {"email": "x402-settle@railcall.test"})
    key = su.get("api_key") or su.get("key")
    _, reg = POST("/v1/agent/register", {"api_key": key, "name": "settle-test",
                  "pay_to": "0x2222222222222222222222222222222222222222", "price_atomic": "10000"})
    if "agent_id" not in reg:
        raise SystemExit("register failed: %s" % reg)
    return key, reg["agent_id"]

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "  << " + detail))

# ── 1 · testnet real settle via facilitator ──────────────────────────────────
print("[1] testnet real settle (base-sepolia + mock facilitator)")
STATE.update(verify_valid=True, settle_ok=True, auth_seen=None)
p = start_gateway({"X402_NETWORK": "base-sepolia", "X402_FACILITATOR": "http://127.0.0.1:%d" % FAC_PORT})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "dGVzdA=="})
check("settle returns 200 paid", st == 200 and r.get("paid") is True, "%s %s" % (st, r))
check("dryRun is FALSE (real settle)", r.get("dryRun") is False, str(r.get("dryRun")))
check("tx hash recorded from facilitator", r.get("txHash") == "0xMOCKTESTNETTXHASH0001", str(r.get("txHash")))
check("CDP Bearer JWT was attached", (STATE["auth_seen"] or "").startswith("Bearer "), str(STATE["auth_seen"]))
_, earn = POST("/v1/agent/%s/earnings" % aid, {"api_key": key})
check("earnings ledger shows 1 settled", earn.get("payments") == 1, str(earn))
stop(p)

# ── 2 · facilitator says invalid -> 402, nothing settled ──────────────────────
print("[2] facilitator rejects the proof")
STATE.update(verify_valid=False)
p = start_gateway({"X402_NETWORK": "base-sepolia", "X402_FACILITATOR": "http://127.0.0.1:%d" % FAC_PORT})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "dGVzdA=="})
check("invalid proof -> 402", st == 402, "%s %s" % (st, r))
STATE.update(verify_valid=True)
stop(p)

# ── 3 · mainnet gate: 403 without audit, 200 with ─────────────────────────────
print("[3] mainnet is gated until the audit flag")
p = start_gateway({"X402_NETWORK": "base", "X402_FACILITATOR": "http://127.0.0.1:%d" % FAC_PORT})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "dGVzdA=="})
check("mainnet WITHOUT audit flag -> 403", st == 403, "%s %s" % (st, r))
stop(p)
p = start_gateway({"X402_NETWORK": "base", "X402_FACILITATOR": "http://127.0.0.1:%d" % FAC_PORT,
                   "X402_MAINNET_AUDITED": "1"})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "dGVzdA=="})
check("mainnet WITH audit flag -> 200 settled", st == 200 and r.get("dryRun") is False, "%s %s" % (st, r))
stop(p)

# ── 4 · facilitator unreachable -> 502, nothing settled ───────────────────────
print("[4] facilitator unreachable")
p = start_gateway({"X402_NETWORK": "base-sepolia", "X402_FACILITATOR": "http://127.0.0.1:59999"})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "dGVzdA=="})
check("unreachable facilitator -> 502 (not settled)", st == 502, "%s %s" % (st, r))
stop(p)

# ── 5 · dry-run preserved (no facilitator) ────────────────────────────────────
print("[5] no facilitator -> dry-run preserved")
p = start_gateway({"X402_NETWORK": "base-sepolia", "X402_FACILITATOR": ""})
key, aid = make_agent()
st, r = POST("/v1/agent/%s/invoke" % aid, {"input": "go"}, {"X-Payment": "anything"})
check("no facilitator -> 200 dryRun TRUE", st == 200 and r.get("dryRun") is True, "%s %s" % (st, r))
stop(p)

fac.shutdown()
print("\n%d passed · %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
