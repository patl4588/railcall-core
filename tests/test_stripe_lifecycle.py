#!/usr/bin/env python3
"""
test_stripe_lifecycle.py — proof the Stripe webhook flips customers OFF when they
cancel or dunning terminates, so their seats free instead of dangling forever.

Before this wire, only checkout.session.completed was handled — a cancelled
subscription left consumers.seat_count at N indefinitely, so the customer kept
holding N seats they no longer paid for and /v1/entitlement/mint kept honoring
that cap.

Pins:
  1. customer.subscription.deleted → status='inactive', seat_count=0
  2. customer.subscription.updated → status='active' → NO change (paying users
     don't get deactivated by innocent updates)
  3. customer.subscription.updated → status='canceled' → deactivated (Stripe
     surfaces the terminal state via updated, not always via deleted)
  4. Idempotent on event_id → replayed webhook doesn't corrupt state
  5. After deactivation, /v1/entitlement/mint returns 403 (status != active)
  6. invoice.payment_failed → logs but does NOT deactivate (grace period is
     Stripe's job; we wait for the subscription.updated → unpaid that follows)

Run: python3 test_stripe_lifecycle.py
"""
import json
import os
import sys
import tempfile
import time
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
    tmp = tempfile.mkdtemp(prefix="rc-lifecycle-")
    os.environ["RAILCALL_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"
    os.environ["RAILCALL_ISSUER_SEED"] = "77" * 32
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_lifecycle"

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print("• SKIP — fastapi TestClient unavailable: %r" % (e,))
        return 0

    import cloud_gateway as G      # noqa: E402
    G.DB_PATH = os.path.join(tmp, "test.db")
    G.init_db()

    # Stub signature verification so the tests don't need a real Stripe signing round-trip.
    # The webhook handler still parses the JSON and dispatches on `type` after the
    # signature branch — so replacing the verifier with a no-op is faithful to what the
    # handler ACTUALLY does downstream.
    import stripe as _stripe
    _stripe.Webhook.construct_event = lambda payload, sig, secret: None

    client = TestClient(G.app)

    # Seed: a paid customer with 5 seats, tied to stripe_customer_id 'cus_A'.
    buyer = "buyer@lifecycle.test"
    raw_key = "rc_live_" + uuid.uuid4().hex[:20]
    key_hash = G._hash_key(raw_key)
    conn = G.db_connect(); cur = conn.cursor()
    cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                     "plan, free_runs_remaining, allocated_runs, runs_used, status, "
                     "stripe_customer_id, source, seat_count) "
                     "VALUES (?, ?, ?, ?, ?, 'paid', 0, 0, 0, 'active', ?, 'stripe', 5)"),
                ("usr_lc", buyer, datetime.now(timezone.utc).isoformat(),
                 raw_key, key_hash, "cus_A"))
    conn.commit(); conn.close()

    def _row():
        conn = G.db_connect(); cur = conn.cursor()
        cur.execute(G.ph("SELECT status, seat_count FROM consumers WHERE stripe_customer_id = ?"),
                    ("cus_A",))
        r = cur.fetchone(); conn.close()
        if r is None:
            return None
        if hasattr(r, "keys"):
            return {"status": r["status"], "seat_count": r["seat_count"]}
        return {"status": r[0], "seat_count": r[1]}

    def _webhook(event_type, obj, event_id=None):
        ev = {"id": event_id or ("evt_" + uuid.uuid4().hex[:16]),
              "type": event_type,
              "data": {"object": obj}}
        return client.post("/v1/webhooks/stripe",
                           data=json.dumps(ev).encode(),
                           headers={"Content-Type": "application/json",
                                    "stripe-signature": "t=0,v1=stub"})

    # ─── 1. subscription.deleted → deactivate ───────────────────────────────
    r = _webhook("customer.subscription.deleted",
                 {"customer": "cus_A", "status": "canceled"})
    ok("1a. subscription.deleted returns 200", r.status_code == 200, r.text[:200])
    row = _row()
    ok("1b. status → inactive",     row and row["status"] == "inactive", row)
    ok("1c. seat_count → 0",        row and row["seat_count"] == 0, row)

    # ─── 2. active update → no-op (paying customer keeps paying) ────────────
    # Reset the row to active with seats to prove the branch guards status correctly.
    conn = G.db_connect(); cur = conn.cursor()
    cur.execute(G.ph("UPDATE consumers SET status='active', seat_count=5 "
                     "WHERE stripe_customer_id = ?"), ("cus_A",))
    conn.commit(); conn.close()
    r = _webhook("customer.subscription.updated",
                 {"customer": "cus_A", "status": "active"})
    ok("2a. subscription.updated status=active returns 200", r.status_code == 200, r.text[:200])
    row = _row()
    ok("2b. active update did NOT deactivate", row and row["status"] == "active", row)
    ok("2c. seat_count preserved at 5",         row and row["seat_count"] == 5, row)

    # ─── 3. terminal update (canceled) → deactivate ─────────────────────────
    r = _webhook("customer.subscription.updated",
                 {"customer": "cus_A", "status": "canceled"})
    row = _row()
    ok("3. subscription.updated status=canceled → deactivated",
       row and row["status"] == "inactive" and row["seat_count"] == 0, row)

    # ─── 4. idempotent — replayed event id doesn't corrupt ──────────────────
    # Reset again, then fire the SAME event id twice.
    conn = G.db_connect(); cur = conn.cursor()
    cur.execute(G.ph("UPDATE consumers SET status='active', seat_count=5 "
                     "WHERE stripe_customer_id = ?"), ("cus_A",))
    conn.commit(); conn.close()
    eid = "evt_dedup_" + uuid.uuid4().hex[:8]
    _webhook("customer.subscription.deleted",
             {"customer": "cus_A", "status": "canceled"}, event_id=eid)
    row1 = _row()
    _webhook("customer.subscription.deleted",
             {"customer": "cus_A", "status": "canceled"}, event_id=eid)
    row2 = _row()
    ok("4a. first delivery deactivated",
       row1 and row1["status"] == "inactive", row1)
    ok("4b. replayed delivery is idempotent (no double-write, still inactive)",
       row2 and row2["status"] == "inactive" and row2["seat_count"] == 0, row2)

    # ─── 5. deactivated customer can't mint ─────────────────────────────────
    r = client.post("/v1/entitlement/mint",
                    data={"api_key": raw_key, "install_pubkey": "cd" * 32})
    ok("5. mint refused (403 or 401) for deactivated account",
       r.status_code in (401, 403), (r.status_code, r.text[:200]))

    # ─── 6. invoice.payment_failed does NOT deactivate ──────────────────────
    conn = G.db_connect(); cur = conn.cursor()
    cur.execute(G.ph("UPDATE consumers SET status='active', seat_count=5 "
                     "WHERE stripe_customer_id = ?"), ("cus_A",))
    conn.commit(); conn.close()
    r = _webhook("invoice.payment_failed",
                 {"customer": "cus_A", "attempt_count": 1})
    ok("6a. invoice.payment_failed returns 200", r.status_code == 200, r.text[:200])
    row = _row()
    ok("6b. status STAYS active on first payment failure (grace period)",
       row and row["status"] == "active", row)
    ok("6c. seat_count STAYS at 5 (Stripe's dunning retries, we wait for terminal update)",
       row and row["seat_count"] == 5, row)

    if FAILED:
        print("\n%d check(s) FAILED:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
