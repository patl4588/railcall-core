#!/usr/bin/env python3
"""
Railcall Cloud Gateway — Stripe checkout + webhook fulfillment, plus the admin
dashboard API. Secrets come from env vars (Render) or a local .env. Admin routes
are gated behind RAILCALL_LOCAL_ADMIN. Storage is Postgres when DATABASE_URL is
set (Render, durable) and SQLite locally (so the same code stays testable).
"""
import os
import json
import hashlib
import sqlite3
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone, timedelta

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

FILE_ENV = load_env()

def cfg(name, default=""):
    """Prefer real environment variables (Render) over the local .env file."""
    v = os.environ.get(name)
    return v if v is not None else FILE_ENV.get(name, default)

STRIPE_SECRET_KEY = cfg("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = cfg("STRIPE_WEBHOOK_SECRET")

# Storage: Postgres when DATABASE_URL is set (Render), else local SQLite.
DB_PATH = "railcall_consumers.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):   # Render emits postgres://, psycopg2 wants postgresql://
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
USE_PG = bool(DATABASE_URL)
if USE_PG:
    import psycopg2
    import psycopg2.extras

# Admin routes (/admin, /api/keys, /api/dashboard_data) are gated behind this flag.
# Set RAILCALL_LOCAL_ADMIN=1 ONLY locally. On Render it's absent → those routes 404,
# so no secret or PII is ever reachable on the public internet.
LOCAL_ADMIN = os.environ.get("RAILCALL_LOCAL_ADMIN") == "1"

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "127.0.0.1" if LOCAL_ADMIN else "0.0.0.0")
DOMAIN_URL = os.environ.get("DOMAIN_URL", "https://railcall-core.onrender.com")  # live default — never localhost in prod

ALLOWED_KEYS = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                "CDP_API_KEY_NAME", "CDP_API_KEY_SECRET", "GROQ_API_KEY")

stripe.api_key = STRIPE_SECRET_KEY
app = FastAPI()

# CORS: the post-checkout success page can be served from Pages (railcall.ai) while
# it fetches the key-handoff endpoint on THIS gateway origin. Restrict to our domains.
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://railcall.ai", "https://www.railcall.ai",
                   "https://railcall-core.onrender.com"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- db layer
def db_connect():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_cursor(conn):
    """A cursor whose rows support row["col"] access on both backends."""
    if USE_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()

def ph(sql):
    """SQLite uses ? placeholders; Postgres uses %s."""
    return sql.replace("?", "%s") if USE_PG else sql


# ------------------------------------------------------- api-key crypto (A4 upgrade)
# Keys are hashed at rest. The RAW key is shown to the user exactly once (signup response, or
# the paid success page) and never persisted in the clear for keys minted after this upgrade.
# api_key_hash is the canonical auth column; the legacy `api_key` column is kept only as a
# zero-downtime fallback for pre-upgrade rows until they're rotated.
def _hash_key(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if isinstance(raw, str) and raw else ""


def _looks_raw(k):
    """A real RailCall key starts with rc_; a sha256 hex digest never does. Lets us tell a
    legacy plaintext value apart from a stored hash without a schema flag."""
    return isinstance(k, str) and k.startswith("rc_")


def _consumer_by_key(cur, raw, cols):
    """Resolve a consumer by its raw api_key: hash-first against api_key_hash (canonical), then
    fall back to the legacy plaintext column (so Pat's pre-upgrade live key keeps working and the
    backfill window has no downtime). `cur` must be a db_cursor (dict-style rows). `cols` is a
    fixed column list from our own code (never user input). Returns the row or None."""
    h = _hash_key(raw)
    if h:
        cur.execute(ph("SELECT " + cols + " FROM consumers WHERE api_key_hash = ?"), (h,))
        row = cur.fetchone()
        if row:
            return row
    cur.execute(ph("SELECT " + cols + " FROM consumers WHERE api_key = ?"), (raw,))
    return cur.fetchone()


# A5-TTL: a paid buyer's transient raw key (pending_key) is purged INSTANTLY on first cli/login;
# this is the belt for keys that sit UNCLAIMED. pending_key is set — and created_at refreshed — at the
# paid INSERT AND on a repeat-purchase rotation, so created_at == when it was minted → we sweep by
# created_at, no extra timestamp column needed.
PENDING_KEY_TTL_HOURS = 24


def _sweep_pending_keys():
    """Null any pending_key older than the TTL (unclaimed handoffs). Best-effort, never raises;
    runs on boot and after each webhook. Returns the count purged."""
    conn = None
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=PENDING_KEY_TTL_HOURS)).isoformat()
        conn = db_connect()
        cur = conn.cursor()
        cur.execute(ph("UPDATE consumers SET pending_key = NULL "
                       "WHERE pending_key IS NOT NULL AND created_at < ?"), (cutoff,))
        n = cur.rowcount
        conn.commit()
        return n
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def init_db():
    """Create tables if missing. A fresh Render/Postgres DB and a fresh SQLite
    file both start empty, so without this the webhook fails 'no such table'."""
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS consumers (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            api_key TEXT UNIQUE,
            plan TEXT NOT NULL DEFAULT 'free',
            free_runs_remaining INTEGER NOT NULL DEFAULT 100,
            runs_used INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            stripe_customer_id TEXT,
            source TEXT NOT NULL DEFAULT 'signup'
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            processed_at TEXT
        )''')
        # Small durable key/value store. Used to cache the Stripe Billing Portal configuration id
        # so we reuse ONE code-defined config across restarts instead of minting a new one per deploy.
        cur.execute('''CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        conn.commit()
        # Additive, zero-downtime: allocated_runs = TOTAL ever granted to a key (immutable by /meter), so
        # the dashboard shows "used / allocated" directly. Each migration step runs in its own tx so a
        # re-run (column already exists) can't poison the Postgres connection.
        try:
            cur.execute("ALTER TABLE consumers ADD COLUMN allocated_runs INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            cur.execute("UPDATE consumers SET allocated_runs = free_runs_remaining + runs_used "
                        "WHERE allocated_runs = 0 AND (free_runs_remaining + runs_used) > 0")
            conn.commit()
        except Exception:
            conn.rollback()
        # A4 crypto upgrade — hash keys at rest. api_key_hash = canonical lookup; pending_key =
        # transient raw for the one-time paid success-page handoff (purged on first login). Both
        # additive + own-tx so a re-run can't poison the connection.
        for ddl in ("ALTER TABLE consumers ADD COLUMN api_key_hash TEXT",
                    "ALTER TABLE consumers ADD COLUMN pending_key TEXT"):
            try:
                cur.execute(ddl)
                conn.commit()
            except Exception:
                conn.rollback()
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_consumers_api_key_hash ON consumers (api_key_hash)")
            conn.commit()
        except Exception:
            conn.rollback()
        # Backfill: pre-upgrade rows hold a raw key but no hash. Compute + fill (Python, uniform
        # across PG/SQLite). Guarded by api_key_hash IS NULL, and new rows insert WITH a hash, so
        # this runs once and never double-hashes. Then verify integrity: 0 rows left unhashed.
        try:
            cur.execute("SELECT id, api_key FROM consumers WHERE api_key_hash IS NULL OR api_key_hash = ''")
            legacy = cur.fetchall()
            filled = 0
            for r in legacy:
                rid, rawk = r[0], r[1]
                if rawk:
                    cur.execute(ph("UPDATE consumers SET api_key_hash = ? WHERE id = ?"), (_hash_key(rawk), rid))
                    filled += 1
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM consumers WHERE (api_key_hash IS NULL OR api_key_hash = '') "
                        "AND api_key IS NOT NULL AND api_key <> ''")
            unhashed = cur.fetchone()[0]
            if filled or unhashed:
                print(f"🔐 API-key migration: backfilled {filled} legacy hash(es); unhashed remaining = {unhashed}")
        except Exception as e:
            conn.rollback()
            print(f"⚠ API-key hash backfill skipped: {e}")
        # A4-Clear: purge legacy cleartext now that every row carries its hash. Drop the NOT NULL
        # so the historical raw strings can be nulled (Postgres: instant catalog change; SQLite:
        # fresh tables are already nullable, ALTER is a caught no-op). GUARDED to api_key_hash present
        # so we never strip a row that would become unauthenticatable. Idempotent (0 rows after run 1).
        try:
            cur.execute("ALTER TABLE consumers ALTER COLUMN api_key DROP NOT NULL")
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            cur.execute("UPDATE consumers SET api_key = NULL "
                        "WHERE api_key_hash IS NOT NULL AND api_key_hash <> '' AND api_key LIKE 'rc_%'")
            purged = cur.rowcount
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM consumers WHERE api_key LIKE 'rc_%'")
            cleartext_left = cur.fetchone()[0]
            if purged or cleartext_left:
                print(f"🔒 A4-Clear: purged {purged} legacy cleartext key(s); cleartext remaining = {cleartext_left}")
        except Exception as e:
            conn.rollback()
            print(f"⚠ A4-Clear purge skipped: {e}")
        # A5-TTL: sweep unclaimed transient pending_key values on boot.
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=PENDING_KEY_TTL_HOURS)).isoformat()
            cur.execute(ph("UPDATE consumers SET pending_key = NULL "
                           "WHERE pending_key IS NOT NULL AND created_at < ?"), (cutoff,))
            swept = cur.rowcount
            conn.commit()
            if swept:
                print(f"🧹 pending_key TTL sweep: purged {swept} unclaimed transient key(s) > {PENDING_KEY_TTL_HOURS}h")
        except Exception:
            conn.rollback()
    finally:
        conn.close()


init_db()


# ------------------------------------------------------ dashboard (gated)
@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    try:
        with open("index.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Landing page not found.", status_code=404)


@app.get("/success.html", response_class=HTMLResponse)
async def serve_success():
    try:
        with open("success.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Payment successful — 1,000 runs added.", status_code=200)


@app.get("/honesty_gate_audit.html", response_class=HTMLResponse)
async def serve_audit():
    try:
        with open("honesty_gate_audit.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Audit page not found.", status_code=404)


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_hub():
    if not LOCAL_ADMIN:
        raise HTTPException(status_code=404)
    try:
        with open("admin_command_hub.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Admin hub file not found.", status_code=404)


@app.get("/api/keys")
async def api_keys():
    if not LOCAL_ADMIN:
        raise HTTPException(status_code=404)
    return {k: cfg(k, "") for k in ALLOWED_KEYS}


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
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        cur.execute("SELECT email, free_runs_remaining, runs_used FROM consumers LIMIT 10")
        rows = cur.fetchall()
        conn.close()
        return [{"email": r["email"], "runs": r["free_runs_remaining"], "used": r["runs_used"]} for r in rows]
    except Exception:
        return []


def get_metering():
    out = {"total_runs_used": 0, "est_revenue": 0.0, "consumers": 0, "by_status": {}}
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        cur.execute("SELECT runs_used, status FROM consumers")
        rows = cur.fetchall()
        conn.close()
        total = sum((r["runs_used"] or 0) for r in rows)
        by_status = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {"total_runs_used": total, "est_revenue": round(total * 0.005, 2),
                "consumers": len(rows), "by_status": by_status}
    except Exception:
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
    if not LOCAL_ADMIN:
        raise HTTPException(status_code=404)
    return {"users": get_users(), "metering": get_metering(),
            "telemetry": get_telemetry(), "groq_status": check_groq()}


@app.get("/v1/balance")
async def balance(api_key: str = ""):
    """Key-scoped balance lookup — returns ONLY the caller's own measured runs from
    the DB. Safe to expose publicly (unlike /api/dashboard_data, which dumps all
    consumers and stays gated): the api_key IS the credential, and one key only ever
    reveals its own row. No mocked numbers — straight from Postgres/SQLite."""
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing api_key")
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        row = _consumer_by_key(cur, api_key, "free_runs_remaining, plan")
        conn.close()
    except Exception:
        raise HTTPException(status_code=500, detail="database error")
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or unknown API key")
    return {"status": "success", "runs_remaining": row["free_runs_remaining"], "tier": row["plan"]}


@app.get("/v1/key_for_session")
async def key_for_session(session_id: str = ""):
    """Post-checkout key handoff. Given the Stripe Checkout session_id (passed to
    success.html via success_url), verify the session is REAL and PAID with Stripe,
    then return the api_key the webhook provisioned for that buyer. Read-only:
    provisioning stays solely in the webhook, so a key is never double-credited. The
    success page polls this until status=='ready' (covers the redirect-vs-webhook
    race). The unguessable session_id is the capability; we never reveal a key for an
    unpaid or unknown session."""
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    try:
        sess = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Unknown or invalid session")
    # stripe v15 StripeObjects don't expose .get() — use attribute access.
    if getattr(sess, "payment_status", None) != "paid":
        return {"status": "unpaid"}
    cd = getattr(sess, "customer_details", None)
    email = (getattr(cd, "email", None) if cd else None) or getattr(sess, "customer_email", None)
    if not email:
        return {"status": "pending"}
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        cur.execute(ph("SELECT pending_key, free_runs_remaining, plan FROM consumers WHERE email = ?"), (email,))
        row = cur.fetchone()
        conn.close()
    except Exception:
        raise HTTPException(status_code=500, detail="database error")
    if not row:
        # Paid, but the webhook hasn't written the row yet — page keeps polling.
        return {"status": "pending"}
    if not row["pending_key"]:
        # Key already retrieved + in use (transient raw purged on first login). We never stored
        # it in the clear, so we can't re-reveal it — guide the buyer to their saved key instead.
        return {"status": "issued", "runs_remaining": row["free_runs_remaining"], "tier": row["plan"]}
    return {"status": "ready", "api_key": row["pending_key"],
            "runs_remaining": row["free_runs_remaining"], "tier": row["plan"]}


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
            # Post-checkout: premium success page (served by this gateway and Pages).
            success_url=DOMAIN_URL + '/success.html?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=DOMAIN_URL + '/?canceled=1',
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------------------------------------------------- stripe webhook
# free_runs_remaining is parametrized (?) so the webhook allocates DYNAMICALLY from amount_total.
# On a repeat purchase by the same email, EXCLUDED.free_runs_remaining is the newly-purchased amount,
# so the balance accumulates (existing + this purchase).
CONSUMER_UPSERT = '''INSERT INTO consumers
    (id, email, created_at, api_key, api_key_hash, pending_key, plan, free_runs_remaining, allocated_runs, runs_used, status, stripe_customer_id, source)
    VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, 0, 'active', ?, 'stripe')
    ON CONFLICT (email) DO UPDATE SET
        plan = 'paid',
        created_at = EXCLUDED.created_at,
        api_key = EXCLUDED.api_key,
        api_key_hash = EXCLUDED.api_key_hash,
        pending_key = EXCLUDED.pending_key,
        free_runs_remaining = consumers.free_runs_remaining + EXCLUDED.free_runs_remaining,
        allocated_runs = consumers.allocated_runs + EXCLUDED.allocated_runs,
        stripe_customer_id = EXCLUDED.stripe_customer_id'''
# On repeat purchase (email conflict) we ROTATE the key: hash-at-rest (A4) means the buyer's
# existing key can't be re-revealed, so a paid event mints a fresh rc_live_, overwrites the stored
# hash, and re-arms pending_key for the one-time /success handoff. created_at is refreshed so the
# A5-TTL sweep that runs right after this webhook treats the freshly-minted pending_key as new
# (an unchanged old created_at would let that sweep purge it instantly). The previous key stops
# working; the buyer copies the new one on the success page (which also saves it for the dashboard).


@app.post("/v1/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    try:
        stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")

    # Signature verified above. stripe v15 StripeObjects don't expose .get(),
    # so use the already-verified raw payload as a plain dict.
    data = json.loads(payload)
    event_id = data.get('id')
    if data.get('type') == 'checkout.session.completed':
        session = data['data']['object']
        email = (session.get('customer_details') or {}).get('email') or session.get('customer_email')
        if email:
            conn = db_connect()
            try:
                cur = conn.cursor()
                # Idempotency: Stripe delivers at-least-once + retries. Dedupe on event id.
                cur.execute(ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                               "ON CONFLICT (event_id) DO NOTHING"),
                            (event_id, datetime.now(timezone.utc).isoformat()))
                if cur.rowcount == 0:
                    conn.commit()
                    print(f"↪ Webhook: duplicate event {event_id} ignored (idempotent)")
                    return {"status": "success", "note": "duplicate ignored"}
                # Dynamic allocation — Stripe sends amount_total in CENTS; 1 cent = 1 run.
                amount_total = session.get('amount_total')
                allocated_runs = amount_total if (isinstance(amount_total, int) and not isinstance(amount_total, bool)
                                                  and 0 < amount_total <= 10_000_000) else 0
                if allocated_runs <= 0:
                    conn.commit()  # idempotency row already inserted; don't reprocess this event
                    print(f"⚠ Webhook: invalid/missing amount_total ({amount_total!r}) for {email} — 0 runs provisioned")
                    return {"status": "success", "note": "no amount_total"}
                raw_key = "rc_live_" + uuid.uuid4().hex[:20]
                key_hash = _hash_key(raw_key)
                cur.execute(ph(CONSUMER_UPSERT),
                            ("usr_" + uuid.uuid4().hex[:20], email,
                             datetime.now(timezone.utc).isoformat(),
                             key_hash, key_hash, raw_key,   # api_key=hash, api_key_hash=hash, pending_key=raw (handoff)
                             allocated_runs, allocated_runs,
                             session.get('customer')))
                conn.commit()
                print(f"✅ Webhook: provisioned {allocated_runs} runs (${allocated_runs/100:.2f}) for {email}")
            except Exception as e:
                conn.rollback()
                print(f"❌ Webhook DB error: {e}")
            finally:
                conn.close()

    _sweep_pending_keys()  # A5-TTL: opportunistically purge unclaimed transient keys between restarts
    return {"status": "success"}


# ------------------------------------------------------- free-tier signup + CLI auth
FREE_TIER_RUNS = 100  # matches the landing page + pricing hero ("100 free runs, no card")


def _valid_email(e):
    return isinstance(e, str) and "@" in e and "." in e.split("@")[-1] and 3 < len(e) < 255


async def _body(request):
    try:
        return await request.json()
    except Exception:
        try:
            return dict(await request.form())
        except Exception:
            return {}


@app.post("/v1/auth/signup")
async def signup(request: Request):
    """Email-only, card-free Free-Tier onboarding. Get-or-create: a known email returns its EXISTING key
    + tier untouched (idempotent, never downgrades a paid user); a new email gets an rc_free_ key with 50
    runs. The web console redirects to /dashboard with the returned key."""
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="valid email required")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT api_key, pending_key, plan, free_runs_remaining, runs_used, allocated_runs "
                       "FROM consumers WHERE email = ?"), (email,))
        row = cur.fetchone()
        if row:  # already onboarded — no duplicate, no downgrade
            # We can only hand a key back if we still have it in the clear: a legacy plaintext row,
            # or a transient pending_key (fresh paid buyer pre-login). A hashed-only account can't
            # be re-revealed — the client uses its locally-saved key (dashboard handles that).
            legacy_raw = row["api_key"] if _looks_raw(row["api_key"]) else None
            raw = row["pending_key"] or legacy_raw
            resp = {"tier": row["plan"],
                    "allocated_runs": row["allocated_runs"] or (row["free_runs_remaining"] + row["runs_used"]),
                    "used_runs": row["runs_used"], "remaining_runs": row["free_runs_remaining"],
                    "redirect": "/dashboard", "note": "existing account"}
            if raw:
                resp["api_key"] = raw
            else:
                resp["existing_account"] = True
            return resp
        key = "rc_free_" + uuid.uuid4().hex[:20]
        key_hash = _hash_key(key)   # store ONLY the hash — raw is returned once below, never persisted clear
        cur.execute(ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, plan, free_runs_remaining, "
                       "allocated_runs, runs_used, status, source) "
                       "VALUES (?, ?, ?, ?, ?, 'free', ?, ?, 0, 'active', 'signup')"),
                    ("usr_" + uuid.uuid4().hex[:20], email, datetime.now(timezone.utc).isoformat(),
                     key_hash, key_hash, FREE_TIER_RUNS, FREE_TIER_RUNS))
        conn.commit()
        print(f"✅ Signup: free tier ({FREE_TIER_RUNS} runs) for {email}")
        return {"api_key": key, "tier": "free", "allocated_runs": FREE_TIER_RUNS, "used_runs": 0,
                "remaining_runs": FREE_TIER_RUNS, "redirect": "/dashboard"}
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="signup failed")
    finally:
        conn.close()


@app.post("/v1/cli/login")
async def cli_login(request: Request):
    """`railcall login <key>` posts its token here. Validates the key against the DB (free OR paid prefix),
    returns tier + remaining so the CLI can persist the token and print a welcome line."""
    body = await _body(request)
    token = str(body.get("api_key") or body.get("token") or body.get("key") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing api_key")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        row = _consumer_by_key(cur, token, "id, plan, free_runs_remaining, runs_used, allocated_runs, status, pending_key")
    finally:
        conn.close()
    if not row or row["status"] != "active":
        raise HTTPException(status_code=401, detail="invalid or inactive key")
    if row["pending_key"]:
        # Key is now in active use → purge the transient cleartext kept only for the one-time
        # success-page handoff. Best-effort; authentication never depends on the raw column.
        conn2 = db_connect()
        try:
            c2 = conn2.cursor()
            c2.execute(ph("UPDATE consumers SET pending_key = NULL WHERE id = ?"), (row["id"],))
            conn2.commit()
        except Exception:
            conn2.rollback()
        finally:
            conn2.close()
    return {"authenticated": True, "tier": row["plan"], "remaining_runs": row["free_runs_remaining"],
            "allocated_runs": row["allocated_runs"] or (row["free_runs_remaining"] + row["runs_used"]),
            "used_runs": row["runs_used"]}


# ------------------------------------------------- billing portal configuration (code-defined)
# The portal layout is defined HERE, not in the Stripe UI: invoice_history (PDF receipts),
# customer_update (corporate tax IDs / business email / address), payment_method_update — wrapped
# in a business_profile (headline + privacy + terms) that both the classic and "next-generation"
# portal layouts render. The config id is cached in app_settings so we reuse ONE config across
# restarts instead of minting a new one each deploy. Field names verified against the installed
# stripe 15.2.1 source (billing_portal/_configuration.py + _session.py).
PORTAL_CONFIG_SETTING_KEY = "portal_config_id"
_portal_config_id = None  # process-level cache


def _settings_get(key):
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT value FROM app_settings WHERE key = ?"), (key,))
        row = cur.fetchone()
        return row["value"] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _settings_set(key, value):
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(ph("INSERT INTO app_settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), (key, value))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def _build_portal_config():
    """Create the premium, code-defined portal configuration. allowed_updates ⊆
    {address,email,name,phone,shipping,tax_id} per the SDK; we expose the three a corporate buyer
    needs (business email, physical address, tax id). Privacy/terms URLs are real on-site pages."""
    return stripe.billing_portal.Configuration.create(
        business_profile={
            "headline": "RailCall — local-first agent governance",
            "privacy_policy_url": "https://railcall.ai/privacy.html",
            "terms_of_service_url": "https://railcall.ai/terms.html",
        },
        features={
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "customer_update": {
                "enabled": True,
                "allowed_updates": ["email", "address", "tax_id"],
            },
        },
        default_return_url="https://railcall.ai/dashboard",
    )


def ensure_portal_config():
    """Get-or-create the Billing Portal Configuration and return its id, or None if Stripe is
    unconfigured / the call fails (the session then falls back to the account-default portal).
    Idempotent across restarts via the cached id in app_settings. Never raises."""
    global _portal_config_id
    if _portal_config_id:
        return _portal_config_id
    if not STRIPE_SECRET_KEY:
        return None
    try:
        stored = _settings_get(PORTAL_CONFIG_SETTING_KEY)
        if stored:
            try:
                cfgobj = stripe.billing_portal.Configuration.retrieve(stored)
                if getattr(cfgobj, "active", True):
                    _portal_config_id = stored
                    return _portal_config_id
            except Exception:
                pass  # stored id missing/stale on Stripe's side → recreate below
        created = _build_portal_config()
        _portal_config_id = created.id
        _settings_set(PORTAL_CONFIG_SETTING_KEY, _portal_config_id)
        print(f"✅ Billing Portal Configuration ready: {_portal_config_id}")
        return _portal_config_id
    except Exception as e:
        print(f"⚠ ensure_portal_config failed: {e}")
        return None


def _ensure_stripe_customer(token, email):
    """Create + persist a Stripe Customer for a PAID user who has none. Payment-Link checkouts
    don't always create a Customer, so a paid consumer row can have a null stripe_customer_id —
    which would leave the billing portal unopenable. We lazily create one (no charge; pure setup)
    on first portal use and store it, so the portal works for existing and future paid buyers.
    Returns the customer id, or None on failure. The UPDATE is guarded so a concurrent click can't
    clobber an already-set id."""
    try:
        cust = stripe.Customer.create(email=email, metadata={"source": "railcall_portal"})
    except Exception as e:
        print(f"⚠ Stripe Customer create failed for {email}: {e}")
        return None
    cid = cust.id
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(ph("UPDATE consumers SET stripe_customer_id = ? "
                       "WHERE (api_key_hash = ? OR api_key = ?) AND (stripe_customer_id IS NULL OR stripe_customer_id = '')"),
                    (cid, _hash_key(token), token))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return cid


# Where Stripe's "Return to RailCall" link sends the user back to. Whitelisted so a
# caller can't redirect the portal anywhere off-domain.
PORTAL_RETURN_ALLOWED = ("https://railcall.ai/dashboard", "https://www.railcall.ai/dashboard",
                         "https://railcall-core.onrender.com/dashboard")


@app.post("/v1/billing/portal")
async def billing_portal(request: Request):
    """Mint a Stripe Billing Portal session for the consumer behind this api_key so they can view
    statements, download invoices, and swap cards. Only paid consumers have a stripe_customer_id;
    free users (and anyone pre-first-purchase) get an honest 'after first purchase' response — never
    a fabricated link. Stripe config errors (e.g. portal not activated) are surfaced verbatim, not
    faked into success."""
    body = await _body(request)
    token = str(body.get("api_key") or body.get("token") or body.get("key") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing api_key")
    req_return = str(body.get("return_url") or "").strip()
    return_url = req_return if req_return in PORTAL_RETURN_ALLOWED else "https://railcall.ai/dashboard"
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        row = _consumer_by_key(cur, token, "stripe_customer_id, status, plan, email")
    finally:
        conn.close()
    if not row or row["status"] != "active":
        raise HTTPException(status_code=401, detail="invalid or inactive key")
    customer_id = row["stripe_customer_id"]
    if not customer_id:
        if (row["plan"] or "free") != "paid":  # genuine free tier — honest, not an error
            return {"portal_url": None, "reason": "no_purchases",
                    "message": "The billing portal opens after your first top-up."}
        if not STRIPE_SECRET_KEY:
            return {"portal_url": None, "reason": "stripe_unconfigured",
                    "message": "Billing is not configured on this server."}
        # Paid, but no Stripe Customer (bought via a Payment Link that didn't create one).
        # Lazily create + persist one so the portal opens for existing and future paid buyers.
        customer_id = _ensure_stripe_customer(token, row["email"])
        if not customer_id:
            return {"portal_url": None, "reason": "stripe_error",
                    "message": "Could not create a billing profile. Please contact support."}
    if not STRIPE_SECRET_KEY:
        return {"portal_url": None, "reason": "stripe_unconfigured",
                "message": "Billing is not configured on this server."}
    config_id = ensure_portal_config()  # premium code-defined layout (None → account default)
    try:
        params = {"customer": customer_id, "return_url": return_url}
        if config_id:
            params["configuration"] = config_id
        session = stripe.billing_portal.Session.create(**params)
        return {"portal_url": session.url, "configuration": config_id}
    except Exception as e:
        # e.g. portal not yet activated in Stripe Settings → surface honestly, don't fake a link.
        print(f"⚠ Billing portal error for customer {customer_id}: {e}")
        return {"portal_url": None, "reason": "stripe_error", "message": str(e)}


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    try:
        with open("dashboard.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Dashboard page not found.", status_code=404)


# ------------------------------------------------------------ metered-run sink
@app.post("/meter")
async def meter(request: Request):
    """Book a governed-run ping from a configured client against the consumer's prepaid
    balance: runs_used += N, free_runs_remaining -= N. Deduped on idempotency_key (the
    run's receipt-integrity hash) via the SAME processed_events table the Stripe webhook
    uses, so a client retry can't double-bill. One source of truth — the consumers row,
    the same one /v1/balance reads and get_metering() sums. The api_key is the credential."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    api_key = body.get("api_key")
    run_count = body.get("run_count")
    idem = body.get("idempotency_key")
    if not isinstance(api_key, str) or not api_key:
        raise HTTPException(status_code=400, detail="missing api_key")
    if isinstance(run_count, bool) or not isinstance(run_count, int) or run_count <= 0 or run_count > 100000:
        raise HTTPException(status_code=400, detail="invalid run_count")
    if not isinstance(idem, str) or not idem:
        raise HTTPException(status_code=400, detail="missing idempotency_key")
    hashed = _hash_key(api_key)
    conn = db_connect()
    try:
        cur = conn.cursor()
        # Idempotency: same at-least-once protection as the Stripe webhook.
        cur.execute(ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                       "ON CONFLICT (event_id) DO NOTHING"),
                    (idem, datetime.now(timezone.utc).isoformat()))
        if cur.rowcount == 0:
            conn.commit()
            return {"status": "success", "note": "duplicate ignored"}
        # MARGIN VAULT (A5): atomic conditional deduction — book ONLY if the prepaid balance covers
        # the request. The floor lives in the WHERE clause, so concurrent runs can never drive a key
        # below zero (no check-then-act race). (api_key_hash OR api_key keeps zero-downtime auth.)
        cur.execute(ph("UPDATE consumers SET runs_used = runs_used + ?, "
                       "free_runs_remaining = free_runs_remaining - ? "
                       "WHERE (api_key_hash = ? OR api_key = ?) AND (allocated_runs - runs_used) >= ?"),
                    (run_count, run_count, hashed, api_key, run_count))
        booked = cur.rowcount
        if booked == 0:
            # Nothing booked → DON'T burn the idempotency key (the run never recorded, so a retry
            # after a top-up must succeed). Roll back the idem insert, then disambiguate the cause:
            # unknown key (401) vs known key with insufficient balance (402).
            conn.rollback()
            exists = _consumer_by_key(db_cursor(conn), api_key, "allocated_runs")
            if not exists:
                raise HTTPException(status_code=401, detail="unknown api_key")
            raise HTTPException(status_code=402, detail="insufficient runs — top up to continue")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()
    return {"status": "success", "runs_recorded": run_count}


@app.get("/health")
async def health():
    """Active DB-connectivity probe: opens a real connection, reads the live storage
    engine (Postgres vs SQLite) straight off that connection, and the registered
    consumer count — so durability can be verified empirically instead of asserted.
    Exposes no secrets and no PII: only an aggregate COUNT(*), never a consumer row
    (which is why this is safe public, unlike the gated /api/dashboard_data)."""
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        cur.execute("SELECT COUNT(*) AS n FROM consumers")
        row = cur.fetchone()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"database degraded: {e}")
    count = row["n"] if row else 0
    return {"status": "ONLINE",
            "db_mode": "PostgreSQL" if USE_PG else "SQLite",
            "consumers_registered": count,
            "redirect_base": DOMAIN_URL}


if __name__ == "__main__":
    import uvicorn
    print(f"Railcall Cloud Gateway -> http://{HOST}:{PORT}  (db: {'postgres' if USE_PG else 'sqlite'})")
    print(f"  Stripe key: {'set' if STRIPE_SECRET_KEY else 'MISSING'}  |  webhook secret: {'set' if STRIPE_WEBHOOK_SECRET else 'MISSING'}")
    uvicorn.run(app, host=HOST, port=PORT)
