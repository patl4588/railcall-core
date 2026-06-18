#!/usr/bin/env python3
"""
Railcall Cloud Gateway — Stripe checkout + webhook fulfillment, plus the admin
dashboard API. Secrets are read from .env (never hardcoded). Bound to loopback.
"""
import os
import json
import sqlite3
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone

import stripe
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse

# ------------------------------------------------------------------ config
def load_env(path=".env"):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()
STRIPE_SECRET_KEY = ENV.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = ENV.get("STRIPE_WEBHOOK_SECRET", "")
DOMAIN_URL = "http://localhost:8080"
DB_PATH = "railcall_consumers.db"
HOST = "127.0.0.1"   # loopback only; this process holds your Stripe secret
PORT = 8080

# Only these keys are ever exposed by /api/keys (.env has ~20 other provider secrets).
ALLOWED_KEYS = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                "CDP_API_KEY_NAME", "CDP_API_KEY_SECRET", "GROQ_API_KEY")

stripe.api_key = STRIPE_SECRET_KEY
app = FastAPI()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------ dashboard (preserved)
@app.get("/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_hub():
    try:
        with open("admin_command_hub.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Admin hub file not found.", status_code=404)


@app.get("/api/keys")
async def api_keys():
    return {k: ENV.get(k, "") for k in ALLOWED_KEYS}


def check_groq():
    try:
        req = urllib.request.Request("https://api.groq.com", method="HEAD")
        urllib.request.urlopen(req, timeout=2)
        return "ONLINE"
    except urllib.error.HTTPError:
        return "ONLINE"   # any HTTP response = reachable
    except urllib.error.URLError:
        return "OFFLINE"


def get_users():
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT email, free_runs_remaining, runs_used FROM consumers LIMIT 10"
        ).fetchall()
        conn.close()
        return [{"email": r["email"], "runs": r["free_runs_remaining"], "used": r["runs_used"]} for r in rows]
    except sqlite3.Error:
        return []


def get_metering():
    out = {"total_runs_used": 0, "est_revenue": 0.0, "consumers": 0, "by_status": {}}
    if not os.path.exists(DB_PATH):
        return out
    try:
        conn = get_db()
        rows = conn.execute("SELECT runs_used, status FROM consumers").fetchall()
        conn.close()
        total = sum((r["runs_used"] or 0) for r in rows)
        by_status = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {"total_runs_used": total, "est_revenue": round(total * 0.005, 2),
                "consumers": len(rows), "by_status": by_status}
    except sqlite3.Error:
        return out


def get_telemetry():
    path = "companion_usage_ledger.jsonl"
    if not os.path.exists(path):
        return []
    entries = []
    try:
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        for line in lines[-12:]:
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            na = j.get("network_audit") or {}
            ext = None
            if isinstance(na, dict):
                for k in ("during_call_external_sockets", "external_sockets_open", "after_call_external_sockets"):
                    if k in na:
                        ext = na[k]
                        break
            res = j.get("result")
            if isinstance(res, str) and len(res) > 60:
                res = res[:60] + "…"
            entries.append({"ran_at": j.get("ran_at"), "run_type": j.get("run_type"),
                            "latency_ms": j.get("latency_ms"), "ext_sockets": ext, "result": res})
    except OSError:
        pass
    return list(reversed(entries))


@app.get("/api/dashboard_data")
async def dashboard_data():
    return {"users": get_users(), "metering": get_metering(),
            "telemetry": get_telemetry(), "groq_status": check_groq()}


# ------------------------------------------------------------- stripe checkout
@app.post("/create-checkout-session")
async def create_checkout_session(email: str = Form(...)):
    try:
        session = stripe.checkout.Session.create(
            customer_email=email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': 1000,
                    'product_data': {'name': 'Railcall Developer Pass (1,000 Runs)'},
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=DOMAIN_URL + '/admin',
            cancel_url=DOMAIN_URL + '/admin',
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------------------------------------------------- stripe webhook
@app.post("/v1/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception as e:
        # SignatureVerificationError (name varies across stripe versions) or other
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        email = (session.get('customer_details') or {}).get('email') or session.get('customer_email')
        if email:
            conn = get_db()
            try:
                # Schema-correct upsert: real table requires id, created_at, api_key (NOT NULL).
                conn.execute(
                    '''INSERT INTO consumers
                       (id, email, created_at, api_key, plan, free_runs_remaining, runs_used, status, stripe_customer_id, source)
                       VALUES (?, ?, ?, ?, 'paid', 1000, 0, 'active', ?, 'stripe')
                       ON CONFLICT(email) DO UPDATE SET
                           plan='paid',
                           free_runs_remaining = free_runs_remaining + 1000,
                           stripe_customer_id = excluded.stripe_customer_id''',
                    ("usr_" + uuid.uuid4().hex[:20], email,
                     datetime.now(timezone.utc).isoformat(),
                     "rc_live_" + uuid.uuid4().hex[:20],
                     session.get('customer')),
                )
                conn.commit()
                print(f"✅ Webhook: provisioned 1,000 runs for {email}")
            except sqlite3.Error as e:
                conn.rollback()
                print(f"❌ Webhook DB error: {e}")
            finally:
                conn.close()

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    print(f"Railcall Cloud Gateway -> http://{HOST}:{PORT}")
    print(f"  Stripe key from .env: {'set' if STRIPE_SECRET_KEY else 'MISSING'}  |  webhook secret: {'set' if STRIPE_WEBHOOK_SECRET else 'MISSING'}")
    uvicorn.run(app, host=HOST, port=PORT)
