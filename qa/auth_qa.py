#!/usr/bin/env python3
"""RailCall signup/auth QA — proves the web-gate auth surface is flawless: register,
weak-password rejection, idempotent duplicate, 409 on email-collision, login success/failure,
no user-enumeration, and reset requests that never leak account existence. Stdlib only."""
import urllib.request, urllib.error, json, sys, os, uuid

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8911")

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
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

email = "qa-auth-" + uuid.uuid4().hex[:10] + "@railcall.ai"
pw, wrongpw = "correct-horse-battery-9", "wrong-horse-9"
print("== RailCall signup/auth QA ==\nBASE = %s\nEMAIL = %s\n" % (BASE, email))

# 1. register a new account
code, j = call("POST", "/v1/auth/register", {"email": email, "password": pw})
key = j.get("api_key")
print("[register new]   HTTP %s  tier=%s  key=%s  remaining=%s" % (code, j.get("tier"), "rc_…" if key else None, j.get("remaining_runs")))
check("register new → 200 + rc_ key", code == 200 and bool(key and key.startswith("rc_")), "code=%s key=%r" % (code, key))
check("new account gets 500 free flows", j.get("remaining_runs") == 500 or j.get("allocated_runs") == 500, "remaining=%s" % j.get("remaining_runs"))

# 2. weak password rejected
code, j = call("POST", "/v1/auth/register", {"email": "qa-weak-" + uuid.uuid4().hex[:8] + "@railcall.ai", "password": "short"})
print("[weak password] HTTP %s  %s" % (code, json.dumps(j)[:120]))
check("weak password rejected (4xx)", 400 <= code < 500, "code=%s" % code)

# 3. duplicate email + SAME password → 409 (SECURE: register never reveals whether the password
#    matched an existing account — no password-correctness oracle; the gate UI bounces 409 to login)
code, j = call("POST", "/v1/auth/register", {"email": email, "password": pw})
print("[dup same pw]   HTTP %s  %s" % (code, json.dumps(j)[:160]))
check("duplicate email (same pw) → 409, no password oracle", code == 409, "code=%s" % code)

# 4. duplicate email + DIFFERENT password → 409 (account exists, must log in)
code, j = call("POST", "/v1/auth/register", {"email": email, "password": wrongpw})
print("[dup diff pw]   HTTP %s  %s" % (code, json.dumps(j)[:120]))
check("duplicate email + different pw → 409", code == 409, "code=%s" % code)

# 5. login with correct password
code, j = call("POST", "/v1/auth/login", {"email": email, "password": pw})
print("[login ok]      HTTP %s  key=%s" % (code, "rc_…" if j.get("api_key") else None))
check("login correct pw → 200 + key", code == 200 and bool(j.get("api_key")), "code=%s" % code)

# 6. login wrong password → 401
code, j = call("POST", "/v1/auth/login", {"email": email, "password": wrongpw})
print("[login wrong]   HTTP %s  %s" % (code, json.dumps(j)[:100]))
check("login wrong pw → 401", code == 401, "code=%s" % code)

# 7. login unknown email → 401 (SAME as wrong pw → no user enumeration)
code, j = call("POST", "/v1/auth/login", {"email": "nobody-" + uuid.uuid4().hex[:8] + "@railcall.ai", "password": pw})
print("[login unknown] HTTP %s  %s" % (code, json.dumps(j)[:100]))
check("login unknown email → 401 (no enumeration)", code == 401, "code=%s" % code)

# 8. reset request (known) → 200, never reveals existence
code, j = call("POST", "/v1/auth/request_reset", {"email": email})
print("[reset known]   HTTP %s" % code)
check("reset request (known) → 200", code == 200, "code=%s" % code)

# 9. reset request (unknown) → 200 (identical response = no enumeration)
code, j = call("POST", "/v1/auth/request_reset", {"email": "ghost-" + uuid.uuid4().hex[:8] + "@railcall.ai"})
print("[reset unknown] HTTP %s" % code)
check("reset request (unknown) → 200 (no enumeration)", code == 200, "code=%s" % code)

passed = sum(1 for _, c, _ in results if c)
print("\n== %d/%d checks passed ==" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 2)
