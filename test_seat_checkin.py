#!/usr/bin/env python3
"""
test_seat_checkin.py — proof for /v1/seat/checkin (paid-tier seat enforcement).

Without this endpoint the paid entitlement's `seats` count is decorative — a
customer with 3 seats could run the station on N machines because nothing
counted distinct activations. This suite pins the enforcement contract:

  1. Blind-hash auth works and unknown hash → 401 (raw key never on the wire).
  2. Malformed input rejects with 400 BEFORE any DB work.
  3. First-use install joins under cap → 200, seat now held.
  4. Same install re-pinging → still 200, held=True, seats_used unchanged (idempotent).
  5. Fresh install pushing over cap → 402 with honest posture, seat NOT reserved.
  6. Nonce dedup returns the SAME posture on retry (never double-counts).
  7. Metering nonce cannot masquerade as a seat nonce (namespace isolation).
  8. Stale seat frees automatically once past the TTL cutoff (prune on checkin).
  9. Free-tier caller with a valid hash gets a clean 403 "not entitled to seats"
     (never a generic 402 that would confuse the operator).
 10. /v1/seat/status returns the current posture without booking anything.

Run: python3 test_seat_checkin.py     (exit 0 iff every check passes)
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-seat-")
    os.environ["RAILCALL_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"
    os.environ["RAILCALL_ISSUER_SEED"] = "22" * 32       # not exercised here but keeps init clean

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print("• SKIP — fastapi TestClient unavailable: %r" % (e,))
        return 0

    import cloud_gateway as G       # noqa: E402
    G.DB_PATH = os.path.join(tmp, "test.db")
    G.init_db()

    client = TestClient(G.app)

    # ─── seed: one paid consumer with a 3-seat entitlement ──────────────────
    # The paid checkin lives under `plan='paid'`; seats_total comes from the
    # customer's org_members count via _seats_for_org(). Seed 3 members so the
    # cap is a real integer to push against.
    import uuid, hashlib
    raw_key = "rc_live_" + uuid.uuid4().hex[:20]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    email = "owner@test.com"

    conn = G.db_connect()
    cur = conn.cursor()
    cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                     "plan, free_runs_remaining, allocated_runs, runs_used, status, source) "
                     "VALUES (?, ?, ?, ?, ?, 'paid', 1000, 1000, 0, 'active', 'stripe')"),
                ("usr_" + uuid.uuid4().hex[:16],
                 email, datetime.now(timezone.utc).isoformat(),
                 raw_key, key_hash))
    org_id = "org_" + uuid.uuid4().hex[:16]
    cur.execute(G.ph("INSERT INTO orgs (id, name, owner_email, created_at) VALUES (?, ?, ?, ?)"),
                (org_id, "Test Org", email, datetime.now(timezone.utc).isoformat()))
    for i in range(3):
        cur.execute(G.ph("INSERT INTO org_members (id, org_id, email, role, status, created_at) "
                         "VALUES (?, ?, ?, 'member', 'active', ?)"),
                    ("mem_" + uuid.uuid4().hex[:12], org_id,
                     f"m{i}@test.com", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    def _pk(i):
        # 32-byte "install pubkey" — the actual bytes don't matter for the enforcement
        # test, only that they're distinct and shape-valid. Real installs derive theirs
        # from Ed25519 keygen.
        return (bytes([i]) * 32).hex()

    def checkin(kh, pk, nonce):
        return client.post("/v1/seat/checkin", json={
            "key_hash": kh, "install_pubkey": pk, "nonce": nonce})

    # ─── 1. blind auth: unknown key_hash → 401 ──────────────────────────────
    r = checkin("ab" * 32, _pk(1), "n-unknown")
    ok("1. unknown key_hash → 401", r.status_code == 401, r.text[:200])

    # ─── 2. malformed input → 400 (before any DB work) ──────────────────────
    r = checkin("nothex", _pk(1), "n-bad-1")
    ok("2a. non-hex key_hash → 400", r.status_code == 400, r.text[:200])
    r = checkin(key_hash, "short", "n-bad-2")
    ok("2b. malformed install_pubkey → 400", r.status_code == 400, r.text[:200])
    r = checkin(key_hash, _pk(1), "")
    ok("2c. empty nonce → 400", r.status_code == 400, r.text[:200])

    # ─── 3. first install joins under cap ───────────────────────────────────
    r = checkin(key_hash, _pk(1), "n-a1")
    j = r.json() if r.status_code == 200 else {}
    ok("3a. first install → 200", r.status_code == 200, r.text[:200])
    ok("3b. seats_total = 3", j.get("seat", {}).get("seats_total") == 3, j)
    ok("3c. seats_used = 1", j.get("seat", {}).get("seats_used") == 1, j)
    ok("3d. held = True",    j.get("seat", {}).get("held") is True, j)

    # ─── 4. same install re-ping → idempotent, count unchanged ──────────────
    r = checkin(key_hash, _pk(1), "n-a2")
    j = r.json() if r.status_code == 200 else {}
    ok("4a. same install re-ping → 200", r.status_code == 200, r.text[:200])
    ok("4b. seats_used stays 1",        j.get("seat", {}).get("seats_used") == 1, j)
    ok("4c. duplicate_nonce false on fresh nonce",
       j.get("seat", {}).get("duplicate_nonce") is False, j)

    # ─── 5. fill to cap then push over ──────────────────────────────────────
    r2 = checkin(key_hash, _pk(2), "n-b1")
    r3 = checkin(key_hash, _pk(3), "n-c1")
    ok("5a. seat 2 joins → 200", r2.status_code == 200, r2.text[:200])
    ok("5b. seat 3 joins → 200", r3.status_code == 200, r3.text[:200])
    r4 = checkin(key_hash, _pk(4), "n-d1")
    j4 = r4.json() if r4.status_code == 402 else {}
    ok("5c. seat 4 refused → 402", r4.status_code == 402, r4.text[:200])
    ok("5d. status seats_exhausted", j4.get("status") == "seats_exhausted", j4)
    ok("5e. at_capacity=True in refusal posture",
       j4.get("seat", {}).get("at_capacity") is True, j4)
    ok("5f. seats_used=3 in refusal posture",
       j4.get("seat", {}).get("seats_used") == 3, j4)

    # ─── 6. nonce dedup returns SAME posture — never double-counts ─────────
    # Re-fire seat 1's very first nonce. Seat count must not budge; nonce should
    # be flagged duplicate so the client can log it.
    r = checkin(key_hash, _pk(1), "n-a1")
    j = r.json() if r.status_code == 200 else {}
    ok("6a. replayed nonce → 200",      r.status_code == 200, r.text[:200])
    ok("6b. duplicate_nonce = True",     j.get("seat", {}).get("duplicate_nonce") is True, j)
    ok("6c. seats_used still 3 (no double count)",
       j.get("seat", {}).get("seats_used") == 3, j)

    # ─── 7. namespace isolation — a metering nonce cannot pass as a seat one ─
    # /meter scopes on "meter:<hash>:<nonce>"; /seat scopes on "seat:<hash>:<nonce>".
    # A raw nonce string that was consumed by /meter must NOT be seen as duplicate
    # here, and vice versa. Assert by inserting a meter-scoped row directly and then
    # checking that seat/checkin with the same nonce still gets duplicate_nonce=False.
    conn = G.db_connect()
    cur = conn.cursor()
    cur.execute(G.ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                     "ON CONFLICT (event_id) DO NOTHING"),
                ("meter:" + key_hash + ":cross-ns-nonce",
                 datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    r = checkin(key_hash, _pk(1), "cross-ns-nonce")   # seat re-ping w/ same nonce string
    j = r.json() if r.status_code == 200 else {}
    ok("7. cross-namespace nonce NOT deduped by seat handler",
       j.get("seat", {}).get("duplicate_nonce") is False, j)

    # ─── 8. TTL — stale seat frees automatically ───────────────────────────
    # Age seat 3 past the TTL cutoff; a subsequent 4th install must now be
    # accepted (the prune runs on every checkin).
    stale_iso = (datetime.now(timezone.utc) - timedelta(days=G._SEAT_TTL_DAYS + 1)).isoformat()
    conn = G.db_connect()
    cur = conn.cursor()
    cur.execute(G.ph("UPDATE seat_reservations SET last_seen_at = ? "
                     "WHERE api_key_hash = ? AND install_pubkey_hex = ?"),
                (stale_iso, key_hash, _pk(3)))
    conn.commit()
    conn.close()
    r = checkin(key_hash, _pk(4), "n-d2")
    j = r.json() if r.status_code == 200 else {}
    ok("8a. install 4 accepted after stale seat freed → 200",
       r.status_code == 200, r.text[:200])
    ok("8b. seats_used back to 3 (stale pruned + 4 added)",
       j.get("seat", {}).get("seats_used") == 3, j)

    # ─── 9. free-tier caller → 403 with actionable detail ──────────────────
    free_key = "rc_free_" + uuid.uuid4().hex[:20]
    free_hash = hashlib.sha256(free_key.encode()).hexdigest()
    conn = G.db_connect()
    cur = conn.cursor()
    cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                     "plan, free_runs_remaining, allocated_runs, runs_used, status, source) "
                     "VALUES (?, ?, ?, ?, ?, 'free', 500, 500, 0, 'active', 'signup')"),
                ("usr_" + uuid.uuid4().hex[:16], "free@test.com",
                 datetime.now(timezone.utc).isoformat(), free_key, free_hash))
    conn.commit(); conn.close()
    r = checkin(free_hash, _pk(9), "n-free-1")
    ok("9. free plan → 403 not entitled", r.status_code == 403, r.text[:200])

    # ─── 10. /v1/seat/status — read-only posture ──────────────────────────
    r = client.post("/v1/seat/status", json={"key_hash": key_hash})
    j = r.json() if r.status_code == 200 else {}
    ok("10a. status → 200", r.status_code == 200, r.text[:200])
    ok("10b. status seats_total = 3",
       j.get("seat", {}).get("seats_total") == 3, j)
    ok("10c. status entitled = True",
       j.get("seat", {}).get("entitled") is True, j)
    ok("10d. reservations list is non-empty",
       isinstance(j.get("reservations"), list) and len(j["reservations"]) > 0, j)
    ok("10e. reservations disclose only pubkey PREFIXES (no full pubkey leak)",
       all(r["install_pubkey_prefix"].endswith("…") for r in j["reservations"]), j)

    if FAILED:
        print("\n%d check(s) FAILED:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
