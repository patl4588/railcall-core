#!/usr/bin/env python3
"""RailCall $0.01/flow metering QA — proves the live billing math holds: blind metering,
exact per-flow decrement, replay protection, and overdraw (insufficient-balance) protection.
Runs against a gateway base URL (local throwaway instance by default). Stdlib only."""
import urllib.request, urllib.error, json, hashlib, sys, os, uuid

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8911")
EMAIL = os.environ.get("QA_EMAIL", "qa-meter-test@railcall.ai")

def call(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:    return e.code, json.loads(e.read().decode() or "{}")
        except Exception: return e.code, {}

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  — " + detail) if detail else ""))

print("== RailCall $0.01/flow metering QA ==")
print("BASE  = " + BASE)
print("EMAIL = " + EMAIL + "\n")

# 1. SIGNUP — email-only free tier
code, j = call("POST", "/v1/auth/signup", {"email": EMAIL})
key = j.get("api_key")
print("[signup]      HTTP %s  tier=%s  remaining=%s  key=%s" % (code, j.get("tier"), j.get("remaining_runs"), "rc_free_…" if key else None))
check("signup returns an rc_free_ key", bool(key and key.startswith("rc_free_")), "got %r" % key)
check("signup grants 100 free flows", j.get("remaining_runs") == 100 or j.get("allocated_runs") == 100, "remaining=%s" % j.get("remaining_runs"))
if not key:
    print("\n!! no key returned (email may already exist) — aborting"); sys.exit(1)

# Blind metering hash: SHA-256 of the api_key, computed CLIENT-SIDE. Raw key never sent to /meter.
key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
print("[key_hash]    sha256(api_key) = %s…" % key_hash[:16])

# 2. STARTING BALANCE
code, j = call("GET", "/v1/balance?api_key=" + key)
start = j.get("runs_remaining")
print("[balance]     start runs_remaining=%s ($%.2f)" % (start, (start or 0) * 0.01))
check("starting balance = 100 flows ($1.00)", start == 100, "got %s" % start)

# 3. TEN BLIND METERED FLOWS — body carries ONLY {key_hash, nonce, run_count}; no key, no data
nonces, ok = [], 0
for i in range(10):
    n = "qa-" + uuid.uuid4().hex
    nonces.append(n)
    code, j = call("POST", "/meter", {"key_hash": key_hash, "nonce": n, "run_count": 1, "action": "flow"})
    if code == 200 and j.get("authorized"):
        ok += 1
    if i == 0:
        print("[meter #1]    HTTP %s  %s" % (code, json.dumps(j)))
print("[meter x10]   %d/10 authorized" % ok)
check("all 10 flows metered 200 + authorized", ok == 10, "%d/10" % ok)

# 4. BALANCE AFTER 10 — must be exactly 90
code, j = call("GET", "/v1/balance?api_key=" + key)
after = j.get("runs_remaining")
print("[balance]     after 10 flows runs_remaining=%s ($%.2f)" % (after, (after or 0) * 0.01))
check("balance decremented by EXACTLY 10 (100 → 90)", after == 90, "got %s" % after)
check("ledger reads $0.90 (90 flows × $0.01)", after == 90, "%s flows = $%.2f" % (after, (after or 0) * 0.01))

# 5. REPLAY PROTECTION — reuse nonce #1, must NOT double-bill
code, j = call("POST", "/meter", {"key_hash": key_hash, "nonce": nonces[0], "run_count": 1, "action": "flow"})
print("[replay]      HTTP %s  %s" % (code, json.dumps(j)))
check("replayed nonce ignored (no double-bill)", code == 200 and "duplicate" in json.dumps(j).lower(), json.dumps(j))
code, j = call("GET", "/v1/balance?api_key=" + key)
after2 = j.get("runs_remaining")
check("balance unchanged after replay (still 90)", after2 == 90, "got %s" % after2)

# 6. OVERDRAW PROTECTION — try to meter 1000 against a 90 balance, must 402 and NOT decrement
code, j = call("POST", "/meter", {"key_hash": key_hash, "nonce": "qa-over-" + uuid.uuid4().hex, "run_count": 1000, "action": "flow"})
print("[overdraw]    meter 1000 on 90 balance → HTTP %s  %s" % (code, json.dumps(j)))
check("overdraw blocked with HTTP 402 (insufficient)", code == 402, "HTTP %s" % code)
code, j = call("GET", "/v1/balance?api_key=" + key)
after3 = j.get("runs_remaining")
check("balance untouched after blocked overdraw (still 90)", after3 == 90, "got %s" % after3)

# 7. PER-KEY NONCE ISOLATION — a DIFFERENT key reusing key-A's nonce string must NOT be deduped
#    against key-A's run. Nonces are scoped per key (key_hash+nonce) in the shared processed_events
#    table, so key-B sending key-A's already-burned nonce is a FRESH booking that decrements key-B's
#    OWN balance — proving one client's nonce can't collide with or free-ride on another's (the same
#    scoping is what keeps a client-chosen nonce from colliding with the Stripe webhook's "cs:<id>" rows).
EMAIL2 = "qa-meter-iso-" + uuid.uuid4().hex[:12] + "@railcall.ai"
code, j = call("POST", "/v1/auth/signup", {"email": EMAIL2})
key2 = j.get("api_key")
key2_hash = hashlib.sha256(key2.encode("utf-8")).hexdigest() if key2 else ""
check("second account provisioned (rc_free_)", bool(key2 and key2.startswith("rc_free_")), "got %r" % key2)
code, j = call("POST", "/meter", {"key_hash": key2_hash, "nonce": nonces[0], "run_count": 1, "action": "flow"})
print("[xkey nonce]  key-B reuses key-A's burned nonce → HTTP %s  %s" % (code, json.dumps(j)))
check("key-B NOT deduped against key-A's nonce (no cross-key free pass)",
      code == 200 and j.get("authorized") and "duplicate" not in json.dumps(j).lower(), json.dumps(j))
code, j = call("GET", "/v1/balance?api_key=" + key2)
b2 = j.get("runs_remaining")
check("key-B actually charged (100 → 99): the reused nonce booked, not free-passed", b2 == 99, "got %s" % b2)
code, j = call("GET", "/v1/balance?api_key=" + key)
check("key-A balance unaffected by key-B's activity (still 90)", j.get("runs_remaining") == 90, "got %s" % j.get("runs_remaining"))

passed = sum(1 for _, c, _ in results if c)
print("\n== %d/%d checks passed ==" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 2)
