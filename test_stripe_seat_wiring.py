#!/usr/bin/env python3
"""
test_stripe_seat_wiring.py — proof for Stripe → seat_count → _seats_for_org() → mint.

Before this wire, `entitlement.seats` was decorative because Stripe never
communicated the seat quantity to the DB. This suite pins the invariants:

  1. A 'seat' subscription session writes seat_count into consumers.
  2. _seats_for_org() prefers the paid seat_count over the org_members fallback.
  3. A legacy Developer Pass session does NOT touch seat_count (rows keep the
     old org_members behavior — no silent seat-cap change on existing customers).
  4. A subscription session with metadata but a failing line_items lookup still
     writes seat_count from the metadata fallback (defence in depth).
  5. `_provision_paid_session` remains idempotent on the session id under BOTH
     branches — Stripe retries + success-page fallback never double-provision.

Run: python3 test_stripe_seat_wiring.py     (exit 0 iff every check passes)
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-seat-wire-")
    os.environ["RAILCALL_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cloud_gateway as G       # noqa: E402
    G.DB_PATH = os.path.join(tmp, "test.db")
    G.init_db()

    # Stub Stripe's list_line_items so we don't need a real network. Returns
    # what the caller injects via _pending_line_items — this mirrors what Stripe
    # would actually reply with for a subscription session.
    import stripe as _stripe
    _pending = {}   # session_id -> [{"quantity": N}, ...]

    class _FakeItems(dict):
        pass

    def _fake_list_line_items(sid, limit=100):
        return _FakeItems(data=_pending.get(sid, []))
    _stripe.checkout.Session.list_line_items = _fake_list_line_items

    def _new_session(mode, session_id, email, amount=None, metadata=None, line_items=None):
        _pending[session_id] = line_items or []
        return {
            "id": session_id,
            "mode": mode,
            "customer_email": email,
            "amount_total": amount,
            "customer": "cus_" + uuid.uuid4().hex[:12],
            "metadata": metadata or {},
        }

    def _row_for(email):
        conn = G.db_connect()
        cur = conn.cursor()
        cur.execute(G.ph("SELECT plan, seat_count, free_runs_remaining, allocated_runs "
                         "FROM consumers WHERE email = ?"), (email,))
        r = cur.fetchone()
        conn.close()
        if r is None:
            return None
        if hasattr(r, "keys"):
            return dict(r)
        return {"plan": r[0], "seat_count": r[1],
                "free_runs_remaining": r[2], "allocated_runs": r[3]}

    # ─── 1. subscription session sets seat_count ────────────────────────────
    e1 = "sub@test.com"
    s1 = _new_session("subscription", "cs_seat_1", e1,
                      line_items=[{"quantity": 7}])
    conn = G.db_connect()
    raw_key = G._provision_paid_session(conn, s1)
    conn.commit(); conn.close()
    ok("1a. subscription session provisions",
       raw_key is not None and raw_key.startswith("rc_live_"), raw_key)
    row = _row_for(e1)
    ok("1b. row plan = 'paid'", row and row["plan"] == "paid", row)
    ok("1c. seat_count = 7 (from line_items.quantity)",
       row and row["seat_count"] == 7, row)
    ok("1d. free_runs_remaining = 0 on seat subscription (not a metered plan)",
       row and (row["free_runs_remaining"] or 0) == 0, row)

    # ─── 2. _seats_for_org() prefers seat_count over org_members ────────────
    # Seed an org for this email with only 2 members. Because seat_count=7 > 0,
    # the function must return 7, not 2 (billed truth beats invite truth).
    conn = G.db_connect()
    cur = conn.cursor()
    org_id = "org_" + uuid.uuid4().hex[:12]
    cur.execute(G.ph("INSERT INTO orgs (id, name, owner_email, created_at) VALUES (?, ?, ?, ?)"),
                (org_id, "Test", e1, datetime.now(timezone.utc).isoformat()))
    for i in range(2):
        cur.execute(G.ph("INSERT INTO org_members (id, org_id, email, role, status, created_at) "
                         "VALUES (?, ?, ?, 'member', 'active', ?)"),
                    ("mem_" + uuid.uuid4().hex[:8], org_id,
                     f"invitee{i}@test.com", datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    ok("2. _seats_for_org(%s) == 7 (billed) not 2 (invited)" % e1,
       G._seats_for_org(e1) == 7)

    # ─── 3. legacy Developer Pass does NOT touch seat_count ─────────────────
    e2 = "metered@test.com"
    s2 = _new_session("payment", "cs_pay_1", e2, amount=1000)   # $10 → 1000 flows
    conn = G.db_connect()
    raw_key2 = G._provision_paid_session(conn, s2)
    conn.commit(); conn.close()
    ok("3a. metered session provisions",
       raw_key2 is not None and raw_key2.startswith("rc_live_"), raw_key2)
    row2 = _row_for(e2)
    ok("3b. seat_count stays NULL/None on metered row (falls back to org_members)",
       row2 and row2["seat_count"] is None, row2)
    ok("3c. allocated_runs = 1000 (amount_total cents = runs)",
       row2 and row2["allocated_runs"] == 1000, row2)

    # ─── 4. metadata fallback when line_items lookup fails ─────────────────
    # Simulate Stripe returning an empty line_items list (network flake, or
    # subscription webhook fires before line items are queryable). Metadata
    # from the checkout endpoint must be trusted as the fallback.
    e4 = "meta@test.com"
    s4 = _new_session("subscription", "cs_seat_meta", e4,
                      line_items=[],   # empty → forces metadata fallback
                      metadata={"railcall_plan": "seat", "railcall_seats": "3"})
    conn = G.db_connect()
    raw_key4 = G._provision_paid_session(conn, s4)
    conn.commit(); conn.close()
    row4 = _row_for(e4)
    ok("4a. metadata-only subscription still provisions", raw_key4 is not None, raw_key4)
    ok("4b. seat_count = 3 from metadata fallback",
       row4 and row4["seat_count"] == 3, row4)

    # ─── 5. idempotency under both branches ────────────────────────────────
    # Re-fire s1 (subscription) and s2 (metered) — both must no-op cleanly.
    conn = G.db_connect()
    dup1 = G._provision_paid_session(conn, s1)
    dup2 = G._provision_paid_session(conn, s2)
    conn.commit(); conn.close()
    ok("5a. re-fired subscription is a no-op (returns None)", dup1 is None)
    ok("5b. re-fired metered payment is a no-op (returns None)", dup2 is None)
    # And the seat count did not change on the second attempt.
    row_final = _row_for(e1)
    ok("5c. seat_count unchanged after replay (still 7)",
       row_final and row_final["seat_count"] == 7, row_final)

    if FAILED:
        print("\n%d check(s) FAILED:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
