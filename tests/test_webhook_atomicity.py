#!/usr/bin/env python3
"""PROVE the Stripe webhook is atomic + crash-safe. Inject a failure mid-provision (after the
idempotency insert, before commit) and assert: (a) the event is NOT marked processed, (b) no
consumer is created, (c) the handler returns non-2xx so Stripe retries, (d) the retry provisions
cleanly with no lost credits. Real SQLite rows; live Postgres untouched."""
import os, sys, tempfile, shutil, sqlite3, json
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloud_gateway.py')
tmp = tempfile.mkdtemp(prefix="rc-atom-"); shutil.copy(SRC, tmp); os.chdir(tmp)
os.environ.pop("DATABASE_URL", None); os.environ["STRIPE_SECRET_KEY"]="sk_test_dummy"; os.environ["STRIPE_WEBHOOK_SECRET"]="whsec_dummy"
sys.path.insert(0, tmp)
import cloud_gateway as G
from fastapi.testclient import TestClient
c = TestClient(G.app); DB = os.path.join(tmp, "railcall_consumers.db")
G.stripe.Webhook.construct_event = lambda payload, sig, secret: None   # signature pre-verified
def q(sql, a=()):
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    r = conn.execute(sql, a).fetchall(); conn.close(); return r
def evt(eid, email, amt):
    return {"id": eid, "type": "checkout.session.completed",
            "data": {"object": {"object": "checkout.session", "amount_total": amt,
                                "customer": "cus_x", "customer_details": {"email": email}}}}
def post(e):
    return c.post("/v1/webhooks/stripe", data=json.dumps(e),
                  headers={"stripe-signature": "t=1,v1=x", "Content-Type": "application/json"})

P = F = 0
def ck(n, cond):
    global P, F
    print(f"  {'PASS' if cond else 'FAIL'}  {n}");  P += 1 if cond else 0; F += 0 if cond else 1

EID, EMAIL = "evt_atomic_1", "buyer-atomic@test.dev"
GOOD = G.CONSUMER_UPSERT

print("— Phase 1: server CHOKES mid-provision (idem inserted, then provision blows up) —")
G.CONSUMER_UPSERT = "INSERT INTO nonexistent_table (a,b,c,d,e,f,g,h,i) VALUES (?,?,?,?,?,?,?,?,?)"  # forces a DB error AFTER the idem insert
r1 = post(evt(EID, EMAIL, 1000))
ck("handler returns non-2xx (500) so Stripe will retry", r1.status_code == 500)
ck("event NOT marked processed (idem rolled back with the provision)",
   len(q("SELECT 1 FROM processed_events WHERE event_id=?", (EID,))) == 0)
ck("no consumer created (nothing half-committed)", len(q("SELECT 1 FROM consumers WHERE email=?", (EMAIL,))) == 0)

print("— Phase 2: Stripe RETRIES the same event (server healthy now) —")
G.CONSUMER_UPSERT = GOOD
r2 = post(evt(EID, EMAIL, 1000))
ck("retry returns 200 (provisioned)", r2.status_code == 200)
row = q("SELECT plan, allocated_runs, free_runs_remaining FROM consumers WHERE email=?", (EMAIL,))
ck("buyer got their credits — NO lost runs (allocated=1000, paid)",
   bool(row) and row[0]["allocated_runs"] == 1000 and row[0]["plan"] == "paid")
ck("event now marked processed exactly once", len(q("SELECT 1 FROM processed_events WHERE event_id=?", (EID,))) == 1)

print("— Phase 3: a 2nd genuine duplicate delivery does NOT double-credit —")
r3 = post(evt(EID, EMAIL, 1000))
ck("duplicate ignored (200, note)", r3.status_code == 200 and r3.json().get("note") == "duplicate ignored")
ck("balance unchanged on duplicate (still 1000, not 2000)",
   q("SELECT allocated_runs FROM consumers WHERE email=?", (EMAIL,))[0]["allocated_runs"] == 1000)

print(f"\nWEBHOOK ATOMICITY: {P} PASS / {F} FAIL")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if F else 0)
