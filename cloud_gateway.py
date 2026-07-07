#!/usr/bin/env python3
"""
Railcall Cloud Gateway — Stripe checkout + webhook fulfillment, plus the admin
dashboard API. Secrets come from env vars (Render) or a local .env. Admin routes
are gated behind RAILCALL_LOCAL_ADMIN. Storage is Postgres when DATABASE_URL is
set (Render, durable) and SQLite locally (so the same code stays testable).
"""
import os
import json
import base64
import re
import hashlib
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import uuid
import hmac
import traceback
import threading
from datetime import datetime, timezone, timedelta

import stripe
from fastapi import FastAPI, Request, HTTPException, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse


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
RESEND_API_KEY = cfg("RESEND_API_KEY")              # transactional email (team invites, password resets)
EMAIL_FROM = cfg("EMAIL_FROM", "RailCall <noreply@railcall.ai>")  # verified Resend sender

# ── x402 agentic crypto payments — DRY-RUN / TESTNET scaffolding (finalize after the wallet contracts are
# audited). Master-gated OFF by default. Nothing here moves real funds: with no X402_FACILITATOR set the
# /verify is a dry-run (records a testnet reference, settles nothing on-chain). Mainnet stays off until the
# SmartAccount/SessionWallet audit lands.
X402_ENABLED = cfg("X402_ENABLED", "") == "1"                 # master gate for the /v1/agent endpoints
X402_NETWORK = cfg("X402_NETWORK", "base-sepolia")            # TESTNET only for now
X402_USDC_ASSET = cfg("X402_USDC_ASSET", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")  # USDC on Base Sepolia
X402_FACILITATOR = cfg("X402_FACILITATOR", "")               # CDP facilitator URL; empty => dry-run (no real settle)
X402_BUILDER_BPS = int(cfg("X402_BUILDER_BPS", "7000") or "7000")  # builder revenue share, basis points (70%)
# Coinbase CDP credentials (v2 Ed25519 API key). Used ONLY to sign a short-lived Bearer JWT for the CDP
# facilitator — never logged, never returned. Set via the owner-gated bootstrap (they're in ALLOWED_KEYS).
CDP_API_KEY_NAME = cfg("CDP_API_KEY_NAME", "")
CDP_API_KEY_SECRET = cfg("CDP_API_KEY_SECRET", "")
# Mainnet is REFUSED until the wallet/settlement audit lands — this flag is the human sign-off, off by default.
# Even with a facilitator + real funds, base-mainnet settlement 403s unless an operator explicitly sets this.
X402_MAINNET_AUDITED = cfg("X402_MAINNET_AUDITED", "") == "1"
# The USDC EIP-712 domain the facilitator uses to verify the payer's EIP-3009 signature. Base-sepolia
# USDC is name="USDC" version="2" (VERIFIED live: "USD Coin" → token_name_mismatch). Without these in
# `extra`, the facilitator can't rebuild the domain → invalid_exact_evm_missing_eip712_domain.
X402_USDC_NAME = cfg("X402_USDC_NAME", "USDC")
X402_USDC_VERSION = cfg("X402_USDC_VERSION", "2")

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
                "CDP_API_KEY_NAME", "CDP_API_KEY_SECRET", "GROQ_API_KEY",
                "RESEND_API_KEY", "EMAIL_FROM")

stripe.api_key = STRIPE_SECRET_KEY
# Hide the interactive API surface (/docs, /redoc, /openapi.json) in production — it maps every
# endpoint and is needless info-disclosure on the public gateway. Keep it locally for dev (no PG).
_DEV_DOCS = not USE_PG
app = FastAPI(
    docs_url=("/docs" if _DEV_DOCS else None),
    redoc_url=("/redoc" if _DEV_DOCS else None),
    openapi_url=("/openapi.json" if _DEV_DOCS else None),
)

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


# Passwords: PBKDF2-HMAC-SHA256, per-user random salt, stored as 'pbkdf2$<iters>$<salt_hex>$<hash_hex>'.
# Stdlib, slow-by-design, verified in CONSTANT TIME. The plaintext password is never stored or logged.
_PBKDF2_ITERS = 240000


def _hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _PBKDF2_ITERS)
    return "pbkdf2$%d$%s$%s" % (_PBKDF2_ITERS, salt.hex(), dk.hex())


def _verify_password(pw, stored):
    try:
        algo, iters, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _consumer_by_key(cur, raw, cols):
    """Resolve a consumer by its raw api_key: hash-first against api_key_hash (canonical), then
    fall back to the legacy plaintext column (so Pat's pre-upgrade live key keeps working and the
    backfill window has no downtime). `cur` must be a db_cursor (dict-style rows). `cols` is a
    fixed column list from our own code (never user input). Returns the row or None."""
    # Reject structurally-impossible keys BEFORE any DB round-trip: a NUL or other control char in a
    # Postgres text parameter raises and would surface to the caller as a 500 "database error" (an info
    # leak). A real key is rc_<tier>_<hex>: printable ASCII, no whitespace, so anything non-printable
    # cannot match a stored row anyway. Fail it closed as "not found" and the caller returns a clean 401.
    if not isinstance(raw, str) or not raw or len(raw) > 256 or not raw.isascii() or not raw.isprintable():
        return None
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


def _platform_cfg(k):
    """Read one key from platform_config (the owner-bootstrap store). None on any miss/error —
    callers fall back to the env-derived module constant, so this can never break a request."""
    try:
        conn = db_connect()
        try:
            cur = db_cursor(conn)
            cur.execute(ph("SELECT v FROM platform_config WHERE k = ?"), (k,))
            row = cur.fetchone()
            v = (row["v"] if row and not isinstance(row, tuple) else (row[0] if row else None))
            return v if v and str(v).strip() else None
        finally:
            conn.close()
    except Exception:
        return None


def _send_email(to, subject, html, text=None):
    """Fire-and-forget transactional email via Resend (HTTP API, stdlib urllib — no new dependency).
    Sends on a daemon thread and returns immediately, so it NEVER blocks the request / async event loop.
    Key resolves per-send: owner-bootstrap store first, env var fallback — so email can be activated
    by the bootstrap endpoint with no redeploy. No-op + False if neither is set (nothing breaks)."""
    resend_key = _platform_cfg("RESEND_API_KEY") or RESEND_API_KEY
    if not resend_key or not to:
        return False
    sender = _platform_cfg("EMAIL_FROM") or EMAIL_FROM
    payload = json.dumps({
        "from": sender, "to": [to], "subject": subject,
        "html": html, "text": text or re.sub(r"<[^>]+>", "", html),
    }).encode()

    def _go():
        req = urllib.request.Request(
            "https://api.resend.com/emails", data=payload, method="POST",
            headers={"Authorization": "Bearer " + resend_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if not (200 <= r.status < 300):
                    print(f"email non-2xx to {to}: {r.status}", flush=True)
        except Exception as e:
            print(f"email send failed to {to}: {e}", flush=True)

    threading.Thread(target=_go, daemon=True).start()
    return True


def _email_shell(title, body_html, button_label=None, button_url=None):
    """Minimal branded HTML email (inline styles — most mail clients strip <style> blocks)."""
    btn = ""
    if button_label and button_url:
        btn = (f'<a href="{button_url}" style="display:inline-block;background:#6366f1;color:#fff;'
               f'text-decoration:none;font-weight:600;font-size:15px;padding:12px 22px;border-radius:10px;'
               f'margin:18px 0">{button_label}</a>')
    return (
        '<div style="background:#0b0f17;padding:32px 16px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        '<div style="max-width:460px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden">'
        '<div style="padding:18px 24px;border-bottom:1px solid #eef0f3;font-weight:700;font-size:16px;color:#111827">RailCall</div>'
        f'<div style="padding:24px;color:#374151;font-size:14px;line-height:1.6">'
        f'<h1 style="font-size:18px;color:#111827;margin:0 0 12px">{title}</h1>{body_html}{btn}</div>'
        '<div style="padding:14px 24px;border-top:1px solid #eef0f3;color:#9ca3af;font-size:12px">'
        'RailCall · local-first AI-agent governance · railcall.ai</div></div></div>'
    )


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
        # Multi-tenant team: orgs + members (org_members.email UNIQUE => one org per email, the v1
        # isolation primitive) + invites. Additive, own-tx, idempotent — safe on an existing DB.
        for ddl in (
            "CREATE TABLE IF NOT EXISTS orgs (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_email TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS org_members (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, email TEXT UNIQUE NOT NULL, role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS invites (token TEXT PRIMARY KEY, org_id TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, expires_at TEXT)",
            "CREATE TABLE IF NOT EXISTS password_resets (token TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)",
            # x402 agentic payments (dry-run/testnet): agents = pay-per-call modules; agent_payments = the ledger
            "CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, owner_email TEXT NOT NULL, name TEXT NOT NULL, price_atomic BIGINT NOT NULL DEFAULT 10000, pay_to TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS agent_payments (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, payer TEXT, amount_atomic BIGINT NOT NULL, network TEXT NOT NULL, tx_ref TEXT, status TEXT NOT NULL DEFAULT 'settled_dryrun', dryrun INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_org_members_org ON org_members (org_id)",
            "CREATE INDEX IF NOT EXISTS idx_invites_org ON invites (org_id)",
            "CREATE INDEX IF NOT EXISTS idx_resets_email ON password_resets (email)",
            "CREATE INDEX IF NOT EXISTS idx_agent_payments_agent ON agent_payments (agent_id)",
        ):
            try:
                cur.execute(ddl); conn.commit()
            except Exception:
                conn.rollback()
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
        try:
            cur.execute("ALTER TABLE consumers ADD COLUMN password_hash TEXT")
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
        return HTMLResponse("Payment successful — 1,000 flows added.", status_code=200)


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
        return {"total_runs_used": total, "est_revenue": round(total * 0.01, 2),
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
    then PROVISION it (credit runs + mint the rc_live_ key) right here, idempotently on
    the session id which is SHARED with the webhook so a payment is never double-credited.
    This means crediting works even with NO Stripe webhook configured. The success page
    polls this until status=='ready'. The unguessable session_id is the capability; we
    never provision or reveal a key for an unpaid or unknown session."""
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
    # WEBHOOK-FREE PROVISIONING: the session is verified PAID via the authenticated retrieve above, so
    # credit it right here — idempotently on the session id, which is SHARED with the webhook, so this can
    # never double-credit. Makes payment work even when the Stripe webhook endpoint isn't configured; a
    # buyer is never charged-but-uncredited just because a dashboard webhook wasn't wired.
    try:
        pconn = db_connect()
        _provision_paid_session(pconn, sess)   # no-op if already provisioned (webhook or an earlier poll)
        pconn.commit()
        pconn.close()
    except Exception:
        raise HTTPException(status_code=500, detail="provisioning failed")
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
                    'product_data': {'name': 'Railcall Developer Pass (1,000 Flows)'},
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


def _provision_paid_session(conn, session):
    """Credit runs + mint a fresh rc_live_ key for a PAID Checkout session, IDEMPOTENTLY.

    The idempotency key is the Checkout session id ("cs:<id>") — stable across Stripe webhook retries
    AND the success-page fallback — so the webhook and the success page can each call this and the
    payment is still credited EXACTLY once (whichever runs first wins; the other is a no-op). Accepts a
    dict (webhook JSON payload) or a Stripe object (success-page retrieve). Returns the raw rc_live_ key
    on a FRESH provision, or None if already provisioned / no usable amount or email. Caller owns commit."""
    def g(o, k):
        return o.get(k) if isinstance(o, dict) else getattr(o, k, None)
    sid = g(session, "id")
    if not sid:
        return None
    cd = g(session, "customer_details")
    email = (g(cd, "email") if cd else None) or g(session, "customer_email")
    if not email:
        return None
    cur = conn.cursor()
    # Shared idempotency: first writer for this session id wins; any later caller is a no-op.
    cur.execute(ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                   "ON CONFLICT (event_id) DO NOTHING"),
                ("cs:" + str(sid), datetime.now(timezone.utc).isoformat()))
    if cur.rowcount == 0:
        return None
    amount_total = g(session, "amount_total")          # Stripe sends CENTS; 1 cent = 1 run
    allocated_runs = amount_total if (isinstance(amount_total, int) and not isinstance(amount_total, bool)
                                      and 0 < amount_total <= 10_000_000) else 0
    if allocated_runs <= 0:
        return None
    raw_key = "rc_live_" + uuid.uuid4().hex[:20]
    key_hash = _hash_key(raw_key)
    cur.execute(ph(CONSUMER_UPSERT),
                ("usr_" + uuid.uuid4().hex[:20], email, datetime.now(timezone.utc).isoformat(),
                 key_hash, key_hash, raw_key, allocated_runs, allocated_runs, g(session, "customer")))
    return raw_key


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
                # Idempotent on the session id, SHARED with the success-page fallback, so a payment is
                # credited exactly once no matter which path runs (or both). Stripe retrying the same
                # event hits the same session id -> same no-op.
                raw_key = _provision_paid_session(conn, session)
                conn.commit()
                if raw_key:
                    print(f"✅ Webhook: provisioned for {email} (session {session.get('id')})")
                else:
                    print(f"↪ Webhook: session {session.get('id')} already provisioned / no amount — no-op")
            except Exception:
                # No silent 200. Roll back (un-marks the session row in the same txn) + return 500 so
                # Stripe retries, and log the full traceback to Render. The crash is surfaced, never masked.
                conn.rollback()
                print(f"❌ Webhook provisioning error for {email} (event {event_id}):\n"
                      f"{traceback.format_exc()}", flush=True)
                raise HTTPException(status_code=500, detail="provisioning failed — will retry")
            finally:
                conn.close()

    _sweep_pending_keys()  # A5-TTL: opportunistically purge unclaimed transient keys between restarts
    return {"status": "success"}


# ------------------------------------------------------- free-tier signup + CLI auth
FREE_TIER_RUNS = 100  # matches the landing page + pricing hero ("100 free flows, no card")


# ASCII-only, exactly one @ with a NON-EMPTY local part and a real dotted TLD. fullmatch (not a '$'
# regex) so a trailing newline / CRLF cannot slip past. Rejects @b.com (empty local part),
# <script>...@x.com (angle brackets), and CRLF/whitespace-injected addresses the old "@ in e" accepted.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}")


def _valid_email(e):
    return (isinstance(e, str) and 3 < len(e) < 255 and e.isascii()
            and not any(c.isspace() for c in e) and bool(_EMAIL_RE.fullmatch(e)))


# Best-effort in-memory signup throttle: a per-client-IP sliding window. State is per-process (resets on
# a Render redeploy/restart) and NOT shared across instances, so it is a flood brake, not a hard quota.
# Behind Render's proxy the real client is the first hop of X-Forwarded-For; fall back to the socket peer.
_SIGNUP_HITS = {}          # ip -> list[epoch_seconds] inside the window
_SIGNUP_WINDOW_S = 60.0
_SIGNUP_MAX_PER_WINDOW = 10


def _client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", "") or "unknown"


def _signup_rate_ok(ip):
    now = datetime.now(timezone.utc).timestamp()
    hits = [t for t in _SIGNUP_HITS.get(ip, ()) if t > now - _SIGNUP_WINDOW_S]
    if len(hits) >= _SIGNUP_MAX_PER_WINDOW:
        _SIGNUP_HITS[ip] = hits          # persist the trimmed window; reject this attempt
        return False
    hits.append(now)
    _SIGNUP_HITS[ip] = hits
    if len(_SIGNUP_HITS) > 10000:        # bound memory growth from one-off IPs
        _SIGNUP_HITS.clear()
    return True


async def _body(request):
    try:
        return await request.json()
    except Exception:
        try:
            return dict(await request.form())
        except Exception:
            return {}


# ============================ SOCIAL LOGIN (OAuth) ============================
# ONE registered app per provider, SHARED with the matching integration: Google login uses the same
# OAuth app as Gmail/Sheets/Drive; GitHub login == the github connector; Discord login == the discord
# connector. Credentials are read from env (never hardcoded). If a provider's env vars are absent its
# button is simply OFF (503, no crash). The provider VERIFIES the email, so an OAuth account is
# email-verified by construction. SCAFFOLD: needs the real keys + a live round-trip to be a working login.
_OAUTH = {
    "google": {"auth": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token",
               "userinfo": "https://www.googleapis.com/oauth2/v2/userinfo",
               "scope": "openid email profile",
               "cid": "GOOGLE_OAUTH_CLIENT_ID", "csec": "GOOGLE_OAUTH_CLIENT_SECRET"},
    "github": {"auth": "https://github.com/login/oauth/authorize",
               "token": "https://github.com/login/oauth/access_token",
               "userinfo": "https://api.github.com/user",
               "emails": "https://api.github.com/user/emails",   # email can be private -> fetch primary
               "scope": "read:user user:email",
               "cid": "GITHUB_OAUTH_CLIENT_ID", "csec": "GITHUB_OAUTH_CLIENT_SECRET"},
    "discord": {"auth": "https://discord.com/oauth2/authorize",
                "token": "https://discord.com/api/oauth2/token",
                "userinfo": "https://discord.com/api/users/@me",
                "scope": "identify email",
                "cid": "DISCORD_OAUTH_CLIENT_ID", "csec": "DISCORD_OAUTH_CLIENT_SECRET"},
}
_OAUTH_STATES = {}   # state -> epoch ; in-memory CSRF guard (per-instance, 10-min TTL)


def _oauth_redirect_uri(provider):
    return DOMAIN_URL.rstrip("/") + "/v1/auth/oauth/" + provider + "/callback"


def _oauth_configured(provider):
    p = _OAUTH.get(provider)
    return bool(p and cfg(p["cid"]) and cfg(p["csec"]))


def _http_json(url, post=None, bearer=None):
    """Tiny JSON HTTP helper. post=dict -> form-encoded POST; bearer -> Authorization header. JSON in/out."""
    hdr = {"Accept": "application/json", "User-Agent": "railcall-gateway"}
    if bearer:
        hdr["Authorization"] = "Bearer " + bearer
    body = None
    if post is not None:
        body = urllib.parse.urlencode(post).encode()
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=("POST" if post is not None else "GET"), headers=hdr)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_or_create_free(email, source):
    """Get-or-create a free account by a provider-VERIFIED email. Returns the raw rc_ key to hand the
    browser: a fresh key for a new account, the existing clear key if we still hold one, else None."""
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT api_key, pending_key, plan FROM consumers WHERE email = ?"), (email,))
        row = cur.fetchone()
        if row:
            return row["pending_key"] or (row["api_key"] if _looks_raw(row["api_key"]) else None)
        key = "rc_free_" + uuid.uuid4().hex[:20]
        kh = _hash_key(key)
        cur.execute(ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, pending_key, "
                       "plan, free_runs_remaining, allocated_runs, runs_used, status, source) "
                       "VALUES (?, ?, ?, ?, ?, ?, 'free', ?, ?, 0, 'active', ?)"),
                    ("usr_" + uuid.uuid4().hex[:20], email, datetime.now(timezone.utc).isoformat(),
                     kh, kh, key, FREE_TIER_RUNS, FREE_TIER_RUNS, source))
        conn.commit()
        return key
    finally:
        conn.close()


@app.get("/v1/auth/oauth/{provider}/start")
async def oauth_start(provider: str):
    """Kick off 'Log in with <provider>'. 503 if that provider's keys aren't in the env yet (button off)."""
    if provider not in _OAUTH:
        raise HTTPException(status_code=404, detail="unknown provider")
    if not _oauth_configured(provider):
        raise HTTPException(status_code=503, detail=provider + " login is not configured")
    p = _OAUTH[provider]
    state = uuid.uuid4().hex
    now = datetime.now(timezone.utc).timestamp()
    _OAUTH_STATES[state] = now
    for s, t in list(_OAUTH_STATES.items()):          # prune expired + bound memory
        if now - t > 600 or len(_OAUTH_STATES) > 5000:
            _OAUTH_STATES.pop(s, None)
    params = urllib.parse.urlencode({
        "client_id": cfg(p["cid"]), "redirect_uri": _oauth_redirect_uri(provider),
        "response_type": "code", "scope": p["scope"], "state": state})
    return RedirectResponse(url=p["auth"] + "?" + params, status_code=302)


@app.get("/v1/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str = "", state: str = "", error: str = ""):
    """Provider redirects back here: verify state, swap code->token, pull the verified email, get-or-create
    the account, hand the key to the dashboard via the URL FRAGMENT (# is never sent to the server/logs)."""
    if provider not in _OAUTH or not _oauth_configured(provider):
        raise HTTPException(status_code=404, detail="unknown or unconfigured provider")
    if error:
        return RedirectResponse(url="/?login_error=" + urllib.parse.quote(error[:40]), status_code=302)
    if not code or state not in _OAUTH_STATES:
        raise HTTPException(status_code=400, detail="invalid or expired login state")
    _OAUTH_STATES.pop(state, None)
    p = _OAUTH[provider]
    try:
        tok = _http_json(p["token"], post={
            "client_id": cfg(p["cid"]), "client_secret": cfg(p["csec"]), "code": code,
            "grant_type": "authorization_code", "redirect_uri": _oauth_redirect_uri(provider)})
        access = tok.get("access_token")
        if not access:
            raise ValueError("no access_token in token response")
        info = _http_json(p["userinfo"], bearer=access)
        email = (info.get("email") or "").strip().lower()
        if not email and provider == "github":            # GitHub: email may be private -> /user/emails
            for e in (_http_json(p["emails"], bearer=access) or []):
                if isinstance(e, dict) and e.get("primary") and e.get("verified"):
                    email = (e.get("email") or "").strip().lower(); break
    except Exception:
        return RedirectResponse(url="/?login_error=oauth_exchange_failed", status_code=302)
    if not _valid_email(email):
        return RedirectResponse(url="/?login_error=no_verified_email", status_code=302)
    key = _get_or_create_free(email, "oauth_" + provider)
    return RedirectResponse(url="/dashboard" + (("#key=" + key) if key else "#existing"), status_code=302)


@app.get("/v1/auth/oauth/status")
async def oauth_status():
    """Which providers are login-ready (both env vars present) — BOOLEANS ONLY, never the values. Drives
    the login UI (show only configured buttons) and is a safe diagnostic for 'why is my login 503'."""
    out = {}
    for prov, p in _OAUTH.items():
        out[prov] = {"configured": _oauth_configured(prov),
                     "id_present": bool(cfg(p["cid"])), "secret_present": bool(cfg(p["csec"]))}
    return {"redirect_base": DOMAIN_URL, "providers": out}


@app.post("/v1/auth/register")
async def register(request: Request):
    """Email + password signup. NEW email -> create a free account (password PBKDF2-hashed) and return the
    key once. EXISTING email -> 409 (never leak the account; tell them to log in). Rate-limited. The
    confirm-password match is enforced client-side; the server only needs the chosen password."""
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="enter a valid email")
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down and retry shortly")
    if not (8 <= len(password) <= 200):
        raise HTTPException(status_code=400, detail="password must be 8–200 characters")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT id FROM consumers WHERE email = ?"), (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="an account with this email already exists — log in instead")
        key = "rc_free_" + uuid.uuid4().hex[:20]
        kh = _hash_key(key)
        cur.execute(ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, pending_key, "
                       "password_hash, plan, free_runs_remaining, allocated_runs, runs_used, status, source) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, 'free', ?, ?, 0, 'active', 'register')"),
                    ("usr_" + uuid.uuid4().hex[:20], email, datetime.now(timezone.utc).isoformat(),
                     kh, kh, key, _hash_password(password), FREE_TIER_RUNS, FREE_TIER_RUNS))
        conn.commit()
        return {"api_key": key, "tier": "free", "allocated_runs": FREE_TIER_RUNS, "used_runs": 0,
                "remaining_runs": FREE_TIER_RUNS, "redirect": "/dashboard"}
    finally:
        conn.close()


# ----------------------------------------------------------------- Multi-tenant team
# One email = one org (org_members.email UNIQUE) is the v1 isolation primitive. EVERY team endpoint
# derives the org from the CALLER's api_key via _team_caller, so a caller can only ever see or touch
# their OWN org. Accept is scoped by the invite token (which carries its org_id). No endpoint takes an
# org_id from the client.
_TEAM_ROLES = ("admin", "developer", "auditor")
_SITE_URL = os.environ.get("SITE_URL", "https://railcall.ai")


def _ensure_org(cur, email):
    """Return (org_id, role) for `email`, lazily creating their own org (as owner) on first use, so
    accounts created before this feature get one the first time they touch /v1/team."""
    cur.execute(ph("SELECT org_id, role FROM org_members WHERE email = ?"), (email,))
    row = cur.fetchone()
    if row:
        return row["org_id"], row["role"]
    org_id = "org_" + uuid.uuid4().hex[:20]
    now = datetime.now(timezone.utc).isoformat()
    name = (email.split("@")[0] or "My") + "'s Team"
    cur.execute(ph("INSERT INTO orgs (id, name, owner_email, created_at) VALUES (?, ?, ?, ?)"),
                (org_id, name, email, now))
    cur.execute(ph("INSERT INTO org_members (id, org_id, email, role, status, created_at) "
                   "VALUES (?, ?, ?, 'owner', 'active', ?)"),
                ("mem_" + uuid.uuid4().hex[:20], org_id, email, now))
    return org_id, "owner"


def _team_caller(cur, api_key):
    """api_key -> (email, org_id, role). 401 on an unknown key. The single source of org scoping."""
    row = _consumer_by_key(cur, api_key, "email")
    if not row:
        raise HTTPException(status_code=401, detail="unknown api_key")
    email = row["email"]
    org_id, role = _ensure_org(cur, email)
    return email, org_id, role


@app.post("/v1/team/members")
async def team_members(request: Request):
    """List the CALLER's org members + pending invites — strictly scoped to the caller's org_id."""
    body = await _body(request)
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        caller_email, org_id, role = _team_caller(cur, body.get("api_key"))
        cur.execute(ph("SELECT m.email, m.role, m.status, m.created_at, c.source "
                       "FROM org_members m LEFT JOIN consumers c ON c.email = m.email "
                       "WHERE m.org_id = ? ORDER BY m.created_at"), (org_id,))
        members = [{"email": r["email"], "role": r["role"], "status": r["status"],
                    # identity provenance for the Team UI — 'oauth_github' → GitHub-verified badge
                    "via": ("github" if (r["source"] or "").startswith("oauth_github")
                            else ("google" if (r["source"] or "").startswith("oauth_google") else "email")),
                    "you": r["email"] == caller_email}
                   for r in cur.fetchall()]
        cur.execute(ph("SELECT email, role, created_at FROM invites WHERE org_id = ? AND status = 'pending' ORDER BY created_at"), (org_id,))
        pending = [{"email": r["email"], "role": r["role"], "invited_at": r["created_at"]} for r in cur.fetchall()]
        conn.commit()
        return {"org_id": org_id, "your_role": role, "members": members, "pending": pending}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.post("/v1/team/invite")
async def team_invite(request: Request):
    """Owner/admin invites a NEW email to the caller's org; returns an accept link. v1 invites NEW
    people only (joining an existing account is a later feature)."""
    body = await _body(request)
    invitee = str(body.get("email") or "").strip().lower()
    role = str(body.get("role") or "developer").strip().lower()
    if role not in _TEAM_ROLES:
        role = "developer"
    if not _valid_email(invitee):
        raise HTTPException(status_code=400, detail="enter a valid email to invite")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        caller_email, org_id, caller_role = _team_caller(cur, body.get("api_key"))
        if caller_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only an owner or admin can invite")
        # Rank guard: admins manage regular members, but only the OWNER may grant the admin role —
        # otherwise one admin could mint co-admins and escalate/contest control of the org.
        if role == "admin" and caller_role != "owner":
            raise HTTPException(status_code=403, detail="only the owner can invite an admin")
        if invitee == caller_email:
            raise HTTPException(status_code=400, detail="you're already on the team")
        cur.execute(ph("SELECT 1 FROM org_members WHERE email = ?"), (invitee,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="that email is already on a RailCall team")
        cur.execute(ph("SELECT 1 FROM consumers WHERE email = ?"), (invitee,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="that email already has a RailCall account — joining an existing account is coming soon")
        cur.execute(ph("UPDATE invites SET status='revoked' WHERE org_id = ? AND email = ? AND status='pending'"), (org_id, invitee))
        token = "inv_" + uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        cur.execute(ph("INSERT INTO invites (token, org_id, email, role, status, created_at, expires_at) "
                       "VALUES (?, ?, ?, ?, 'pending', ?, ?)"),
                    (token, org_id, invitee, role, now.isoformat(), (now + timedelta(days=14)).isoformat()))
        conn.commit()
        invite_url = _SITE_URL + "/accept.html?token=" + token
        cur.execute(ph("SELECT name FROM orgs WHERE id = ?"), (org_id,))
        orow = cur.fetchone()
        org_name = (orow["name"] if orow else None) or "a RailCall team"
        email_sent = _send_email(
            invitee, f"You're invited to join {org_name} on RailCall",
            _email_shell(
                f"Join {org_name} on RailCall",
                f"<p><b>{caller_email}</b> invited you to join <b>{org_name}</b> as <b>{role}</b> on "
                f"RailCall — the local-first AI-agent governance platform.</p>"
                f"<p>Set your password to get your own API key and 100 free flows. This invite expires in 14 days.</p>",
                "Accept your invite", invite_url))
        return {"status": "invited", "email": invitee, "role": role, "invite_url": invite_url, "email_sent": email_sent}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.post("/v1/team/accept")
async def team_accept(request: Request):
    """An invitee accepts via the token + a chosen password. Scoped entirely by the invite's org_id:
    creates their account, joins the inviting org with the invited role, marks the invite accepted."""
    body = await _body(request)
    token = str(body.get("token") or "")
    password = str(body.get("password") or "")
    if not token.startswith("inv_"):
        raise HTTPException(status_code=400, detail="invalid invite")
    if not (8 <= len(password) <= 200):
        raise HTTPException(status_code=400, detail="password must be 8–200 characters")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT org_id, email, role, status, expires_at FROM invites WHERE token = ?"), (token,))
        inv = cur.fetchone()
        if not inv or inv["status"] != "pending":
            raise HTTPException(status_code=404, detail="this invite is no longer valid")
        if inv["expires_at"] and inv["expires_at"] < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=410, detail="this invite has expired")
        email, org_id, role = inv["email"], inv["org_id"], inv["role"]
        cur.execute(ph("SELECT 1 FROM consumers WHERE email = ?"), (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="that email already has an account — log in instead")
        cur.execute(ph("SELECT 1 FROM org_members WHERE email = ?"), (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="that email is already on a team")
        key = "rc_free_" + uuid.uuid4().hex[:20]
        kh = _hash_key(key)
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, pending_key, "
                       "password_hash, plan, free_runs_remaining, allocated_runs, runs_used, status, source) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, 'free', ?, ?, 0, 'active', 'team_invite')"),
                    ("usr_" + uuid.uuid4().hex[:20], email, now, kh, kh, key, _hash_password(password),
                     FREE_TIER_RUNS, FREE_TIER_RUNS))
        cur.execute(ph("INSERT INTO org_members (id, org_id, email, role, status, created_at) "
                       "VALUES (?, ?, ?, ?, 'active', ?)"),
                    ("mem_" + uuid.uuid4().hex[:20], org_id, email, role, now))
        cur.execute(ph("UPDATE invites SET status='accepted' WHERE token = ?"), (token,))
        conn.commit()
        return {"api_key": key, "tier": "free", "allocated_runs": FREE_TIER_RUNS, "used_runs": 0,
                "remaining_runs": FREE_TIER_RUNS, "redirect": "/dashboard"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.post("/v1/team/remove")
async def team_remove(request: Request):
    """Owner/admin removes a member or cancels a pending invite — only within the caller's own org."""
    body = await _body(request)
    target = str(body.get("email") or "").strip().lower()
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        caller_email, org_id, caller_role = _team_caller(cur, body.get("api_key"))
        if caller_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only an owner or admin can remove members")
        if target == caller_email:
            raise HTTPException(status_code=400, detail="you can't remove yourself")
        cur.execute(ph("SELECT role FROM org_members WHERE org_id = ? AND email = ?"), (org_id, target))
        m = cur.fetchone()
        if m:
            if m["role"] == "owner":
                raise HTTPException(status_code=403, detail="the owner can't be removed")
            # Rank guard: an admin can remove regular members, but only the OWNER may remove a fellow
            # admin — otherwise a single rogue admin could evict every other admin and seize the org.
            if m["role"] == "admin" and caller_role != "owner":
                raise HTTPException(status_code=403, detail="only the owner can remove an admin")
            cur.execute(ph("DELETE FROM org_members WHERE org_id = ? AND email = ?"), (org_id, target))
        else:
            cur.execute(ph("UPDATE invites SET status='revoked' WHERE org_id = ? AND email = ? AND status='pending'"), (org_id, target))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="that person isn't on your team")
        conn.commit()
        return {"status": "removed", "email": target}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.get("/v1/team/invite_info")
async def team_invite_info(token: str = ""):
    """Public display info for an invite link (so the accept page can show what you're joining). The
    token IS the capability; this returns only the invitee's own email + the org name + role — no secrets."""
    if not token.startswith("inv_"):
        return {"valid": False}
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT i.email, i.role, i.status, i.expires_at, o.name AS org_name "
                       "FROM invites i JOIN orgs o ON o.id = i.org_id WHERE i.token = ?"), (token,))
        r = cur.fetchone()
        if not r or r["status"] != "pending":
            return {"valid": False}
        if r["expires_at"] and r["expires_at"] < datetime.now(timezone.utc).isoformat():
            return {"valid": False, "expired": True}
        return {"valid": True, "email": r["email"], "role": r["role"], "org_name": r["org_name"]}
    except Exception:
        return {"valid": False}
    finally:
        conn.close()


@app.post("/v1/auth/login")
async def login(request: Request):
    """Email + password login. Verifies the PBKDF2 hash in CONSTANT TIME and returns the account's key +
    balance. A single generic 401 on bad email-or-password (no user enumeration). Rate-limited. NOTE: if
    the key was already claimed (hashed-only, no clear copy left), we can't re-reveal it — the dashboard
    falls back to the locally-saved key; true key regeneration lands with the API-keys page later."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down and retry shortly")
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT api_key, pending_key, password_hash, plan, free_runs_remaining, runs_used, "
                       "allocated_runs FROM consumers WHERE email = ?"), (email,))
        row = cur.fetchone()
        if not row or not row["password_hash"] or not _verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="incorrect email or password")
        raw = row["pending_key"] or (row["api_key"] if _looks_raw(row["api_key"]) else None)
        resp = {"tier": row["plan"],
                "allocated_runs": row["allocated_runs"] or (row["free_runs_remaining"] + row["runs_used"]),
                "used_runs": row["runs_used"], "remaining_runs": row["free_runs_remaining"], "redirect": "/dashboard"}
        if raw:
            resp["api_key"] = raw
        else:
            resp["existing_account"] = True
        return resp
    finally:
        conn.close()


@app.post("/v1/auth/regenerate_key")
async def regenerate_key(request: Request):
    """Authenticated key recovery. Email + password (verified against the PBKDF2 hash) mints a FRESH key
    for an account whose old key can no longer be revealed (hash-at-rest leaves no clear copy). Preserves
    tier + balance EXACTLY — only the key rotates; the prior key stops authenticating. Returns the new key
    ONCE (never persisted in the clear). Same generic 401 as login (no enumeration) and the same per-IP
    rate limit. This is the recovery path the login flow promises for hashed-only accounts."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down and retry shortly")
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT id, password_hash, plan, free_runs_remaining, runs_used, "
                       "allocated_runs FROM consumers WHERE email = ?"), (email,))
        row = cur.fetchone()
        if not row or not row["password_hash"] or not _verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="incorrect email or password")
        # Preserve the tier prefix: a paid account keeps an rc_live_ key, a free account an rc_free_ key.
        prefix = "rc_live_" if (row["plan"] or "free") == "paid" else "rc_free_"
        key = prefix + uuid.uuid4().hex[:20]
        kh = _hash_key(key)   # store ONLY the hash; the raw is returned once below, never persisted clear
        # Overwrite BOTH key columns (canonical api_key_hash + legacy plaintext fallback) and drop any
        # transient pending_key, so the OLD key stops authenticating. Tier + balance columns are untouched —
        # this never downgrades a paid account or resets runs.
        cur.execute(ph("UPDATE consumers SET api_key = ?, api_key_hash = ?, pending_key = NULL WHERE id = ?"),
                    (kh, kh, row["id"]))
        conn.commit()
        return {"api_key": key, "tier": row["plan"],
                "allocated_runs": row["allocated_runs"] or (row["free_runs_remaining"] + row["runs_used"]),
                "used_runs": row["runs_used"], "remaining_runs": row["free_runs_remaining"], "redirect": "/dashboard"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="key regeneration failed")
    finally:
        conn.close()


@app.post("/v1/auth/signup")
async def signup(request: Request):
    """Email-only, card-free Free-Tier onboarding. Get-or-create: a known email returns its EXISTING key
    + tier untouched (idempotent, never downgrades a paid user); a new email gets an rc_free_ key with 100
    runs. The web console redirects to /dashboard with the returned key."""
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="valid email required")
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many signups from your network; slow down and retry shortly")
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


@app.post("/v1/auth/request_reset")
async def request_reset(request: Request):
    """Start a password reset. ALWAYS returns the same 200 (no account enumeration). If the email has an
    account, mint a 1-hour token and email a reset link. Rate-limited by IP."""
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()
    generic = {"status": "ok", "message": "If an account exists for that email, a reset link is on its way."}
    if not _valid_email(email):
        return generic
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many requests — slow down and retry shortly")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT 1 FROM consumers WHERE email = ?"), (email,))
        if cur.fetchone():
            token = "rst_" + uuid.uuid4().hex
            now = datetime.now(timezone.utc)
            cur.execute(ph("INSERT INTO password_resets (token, email, created_at, expires_at, used) "
                           "VALUES (?, ?, ?, ?, 0)"),
                        (token, email, now.isoformat(), (now + timedelta(hours=1)).isoformat()))
            conn.commit()
            reset_url = _SITE_URL + "/reset.html?token=" + token
            _send_email(
                email, "Reset your RailCall password",
                _email_shell(
                    "Reset your password",
                    "<p>We received a request to reset your RailCall password. This link expires in "
                    "1 hour. If you didn't ask for this, you can safely ignore this email — nothing changes.</p>",
                    "Set a new password", reset_url))
        return generic
    except Exception:
        conn.rollback()
        return generic
    finally:
        conn.close()


@app.post("/v1/auth/reset")
async def do_reset(request: Request):
    """Finish a password reset: {token, password}. Validates the token (exists, unused, unexpired), sets the
    new PBKDF2 hash, marks the token used. Generic 400 on any invalid/expired/used token."""
    body = await _body(request)
    token = str(body.get("token") or "").strip()
    password = str(body.get("password") or "")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT email, expires_at, used FROM password_resets WHERE token = ?"), (token,))
        row = cur.fetchone()
        if not row or row["used"] or not row["expires_at"]:
            raise HTTPException(status_code=400, detail="this reset link is invalid or already used")
        if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
            raise HTTPException(status_code=400, detail="this reset link has expired — request a new one")
        cur.execute(ph("UPDATE consumers SET password_hash = ? WHERE email = ?"),
                    (_hash_password(password), row["email"]))
        cur.execute(ph("UPDATE password_resets SET used = 1 WHERE token = ?"), (token,))
        conn.commit()
        return {"status": "ok", "message": "Password updated — you can now log in.", "redirect": "/dashboard"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="reset failed")
    finally:
        conn.close()


# ───────────────────────────── x402 agentic crypto payments (DRY-RUN / TESTNET) ─────────────────────────────
# Lets AI agents pay per call in USDC over the x402 (HTTP 402) protocol. SAFETY: testnet only, dry-run by
# default — with no X402_FACILITATOR configured, /invoke records a testnet reference and moves NO real funds;
# the smart-wallet contracts stay mainnet-locked until audited. This is first-pass scaffolding to finalize later.

def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _cdp_jwt(method, url):
    """A short-lived (120s) CDP v2 Bearer JWT (EdDSA/Ed25519) scoped to one request, per Coinbase's
    auth spec. Returns None when creds are absent or crypto is unavailable — the caller then sends no
    Authorization header (fine for an unauthenticated/open facilitator; the CDP facilitator will 401,
    which surfaces honestly rather than silently faking a settle)."""
    if not (CDP_API_KEY_NAME and CDP_API_KEY_SECRET):
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed = base64.b64decode(CDP_API_KEY_SECRET)[:32]   # 64-byte CDP secret = 32B seed + 32B pubkey
        key = Ed25519PrivateKey.from_private_bytes(seed)
        parsed = urllib.parse.urlparse(url)
        now = int(datetime.now(timezone.utc).timestamp())
        header = {"alg": "EdDSA", "typ": "JWT", "kid": CDP_API_KEY_NAME, "nonce": uuid.uuid4().hex}
        # CDP v2 Ed25519 REST JWT (matches Coinbase's official SDK): claim is `uris` (an ARRAY),
        # `aud` optional, `sub`/`kid` = api_key_id (bare UUID or the full organizations/.../apiKeys/...
        # name both work). Testnet base-sepolia can settle via the open x402.org facilitator (no JWT);
        # the CDP facilitator supports base-sepolia too but stays behind X402_MAINNET_AUDITED for real funds.
        claims = {"sub": CDP_API_KEY_NAME, "iss": "cdp",
                  "nbf": now, "iat": now, "exp": now + 120,
                  "uris": ["%s %s%s" % (method.upper(), parsed.netloc, parsed.path)]}
        signing_input = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + \
            _b64url(json.dumps(claims, separators=(",", ":")).encode())
        sig = key.sign(signing_input.encode())
        return signing_input + "." + _b64url(sig)
    except Exception:
        return None


def _x402_requirements(agent, resource):
    """The paymentRequirements the facilitator verifies the payer's proof against — mirrors the 402 challenge."""
    return {
        "scheme": "exact", "network": X402_NETWORK,
        "maxAmountRequired": str(agent["price_atomic"]),
        "resource": resource, "description": "Pay-per-call: %s" % agent["name"],
        "mimeType": "application/json", "payTo": agent["pay_to"],
        "maxTimeoutSeconds": 60, "asset": X402_USDC_ASSET,
        # name/version let the facilitator rebuild the USDC EIP-712 domain to verify the signature.
        "extra": {"builderBps": X402_BUILDER_BPS, "name": X402_USDC_NAME, "version": X402_USDC_VERSION},
    }


def _x402_is_testnet():
    n = (X402_NETWORK or "").lower()
    return ("sepolia" in n) or ("testnet" in n) or ("goerli" in n)


def _x402_facilitator_call(kind, requirements, payment):
    """POST to the CDP facilitator's /verify or /settle. Raises on transport/HTTP error so a failed
    settle NEVER silently reads as paid. Returns the parsed JSON verdict."""
    url = X402_FACILITATOR.rstrip("/") + "/" + kind
    body = json.dumps({"x402Version": 1, "paymentPayload": payment,
                       "paymentRequirements": requirements}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "RailCall-x402/1"})
    jwt = _cdp_jwt("POST", url)
    if jwt:
        req.add_header("Authorization", "Bearer " + jwt)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode() or "{}")


def _x402_challenge(agent, resource):
    """Spec-shaped x402 '402 Payment Required' body (the client reads `accepts` and pays, then retries)."""
    return {
        "x402Version": 1,
        "accepts": [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": str(agent["price_atomic"]),
            "resource": resource,
            "description": f"Pay-per-call: {agent['name']}",
            "mimeType": "application/json",
            "payTo": agent["pay_to"],
            "maxTimeoutSeconds": 60,
            "asset": X402_USDC_ASSET,
            "extra": {"builderBps": X402_BUILDER_BPS, "dryRun": not bool(X402_FACILITATOR),
                      "name": X402_USDC_NAME, "version": X402_USDC_VERSION},
        }],
    }


@app.post("/v1/agent/register")
async def agent_register(request: Request):
    """Register a pay-per-call agent/module. Owner = the caller key's account. price_atomic = USDC atomic
    units (6 decimals; 10000 = $0.01). pay_to = the builder's 0x address."""
    if not X402_ENABLED:
        raise HTTPException(status_code=503, detail="x402 payments are not enabled on this gateway")
    body = await _body(request)
    name = str(body.get("name") or "").strip()
    pay_to = str(body.get("pay_to") or "").strip()
    price = str(body.get("price_atomic") or "10000").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not (pay_to.startswith("0x") and len(pay_to) == 42):
        raise HTTPException(status_code=400, detail="a valid 0x pay_to address is required")
    if not price.isdigit() or int(price) <= 0:
        raise HTTPException(status_code=400, detail="price_atomic must be a positive integer (USDC atomic units)")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        email, _org, _role = _team_caller(cur, body.get("api_key"))   # 401 if the key is unknown
        aid = "agt_" + uuid.uuid4().hex[:16]
        cur.execute(ph("INSERT INTO agents (id, owner_email, name, price_atomic, pay_to, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)"),
                    (aid, email, name, int(price), pay_to, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return {"agent_id": aid, "name": name, "price_atomic": int(price), "pay_to": pay_to,
                "network": X402_NETWORK, "dryrun": not bool(X402_FACILITATOR),
                "invoke_url": _SITE_URL + f"/v1/agent/{aid}/invoke"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()


@app.get("/v1/agent/{agent_id}")
async def agent_get(agent_id: str):
    """Public agent info (name + price) so a paying agent knows what it owes before invoking."""
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT id, name, price_atomic, pay_to FROM agents WHERE id = ?"), (agent_id,))
        a = cur.fetchone()
        if not a:
            raise HTTPException(status_code=404, detail="agent not found")
        return {"agent_id": a["id"], "name": a["name"], "price_atomic": a["price_atomic"],
                "pay_to": a["pay_to"], "network": X402_NETWORK, "asset": X402_USDC_ASSET}
    finally:
        conn.close()


@app.post("/v1/agent/{agent_id}/invoke")
async def agent_invoke(agent_id: str, request: Request):
    """x402-gated call. No `X-Payment` header → HTTP 402 + the payment challenge. With a proof header → verify
    (dry-run/testnet) → record the payment → return the result. DRY-RUN moves NO real funds."""
    if not X402_ENABLED:
        raise HTTPException(status_code=503, detail="x402 payments are not enabled on this gateway")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute(ph("SELECT id, name, price_atomic, pay_to, owner_email FROM agents WHERE id = ?"), (agent_id,))
        agent = cur.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="agent not found")
        resource = f"/v1/agent/{agent_id}/invoke"
        proof = request.headers.get("X-Payment") or request.headers.get("x-payment")
        if not proof:
            return JSONResponse(status_code=402, content=_x402_challenge(agent, resource))
        # DRY-RUN (no facilitator): accept the testnet reference, record it, settle NOTHING on-chain.
        dryrun = not bool(X402_FACILITATOR)
        payer_hint = (request.headers.get("X-Payer") or "")[:64]
        pid = "pay_" + uuid.uuid4().hex[:16]
        if dryrun:
            cur.execute(ph("INSERT INTO agent_payments (id, agent_id, payer, amount_atomic, network, tx_ref, status, dryrun, created_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, 'settled_dryrun', 1, ?)"),
                        (pid, agent_id, payer_hint, agent["price_atomic"],
                         X402_NETWORK, ("dryrun:" + proof)[:80], datetime.now(timezone.utc).isoformat()))
            conn.commit()
            return JSONResponse(status_code=200, content={
                "paid": True, "dryRun": True, "paymentId": pid, "network": X402_NETWORK,
                "amountAtomic": str(agent["price_atomic"]), "payTo": agent["pay_to"],
                "result": {"status": "ok", "note": "DRY-RUN: access granted, no real funds moved"},
            })
        # REAL settle via the CDP facilitator. Mainnet is refused until the audit sign-off flag is set,
        # even here — codifying the "mainnet only post-audit" rule so a stray facilitator URL can't move
        # real funds on its own.
        if not _x402_is_testnet() and not X402_MAINNET_AUDITED:
            raise HTTPException(status_code=403,
                                detail="mainnet settlement is gated pending the security audit — set X402_MAINNET_AUDITED=1 only after sign-off")
        requirements = _x402_requirements(agent, resource)
        # The x402 `X-Payment` header is base64(JSON) of the payer's signed authorization; tolerate a raw
        # string so a non-standard client still reaches the facilitator (which will reject it if invalid).
        try:
            payment = json.loads(base64.b64decode(proof).decode())
        except Exception:
            payment = {"raw": proof}
        try:
            verdict = _x402_facilitator_call("verify", requirements, payment)
        except Exception:
            raise HTTPException(status_code=502, detail="facilitator /verify unreachable — not settled")
        if not verdict.get("isValid"):
            return JSONResponse(status_code=402, content={
                "x402Version": 1, "error": "payment invalid",
                "reason": verdict.get("invalidReason"), "accepts": [requirements]})
        try:
            settled = _x402_facilitator_call("settle", requirements, payment)
        except Exception:
            raise HTTPException(status_code=502, detail="facilitator /settle unreachable — not settled")
        if not settled.get("success"):
            raise HTTPException(status_code=402,
                                detail="settlement failed: %s" % (settled.get("errorReason") or "unknown"))
        tx = str(settled.get("transaction") or settled.get("txHash") or "")[:80]
        cur.execute(ph("INSERT INTO agent_payments (id, agent_id, payer, amount_atomic, network, tx_ref, status, dryrun, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, 'settled', 0, ?)"),
                    (pid, agent_id, (settled.get("payer") or payer_hint)[:64], agent["price_atomic"],
                     X402_NETWORK, tx, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return JSONResponse(status_code=200, content={
            "paid": True, "dryRun": False, "paymentId": pid, "network": X402_NETWORK,
            "txHash": tx, "amountAtomic": str(agent["price_atomic"]), "payTo": agent["pay_to"],
            "result": {"status": "ok", "note": "settled on-chain via the CDP facilitator"},
        })
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise HTTPException(status_code=500, detail="payment error")
    finally:
        conn.close()


@app.post("/v1/agent/{agent_id}/earnings")
async def agent_earnings(agent_id: str, request: Request):
    """Owner-only earnings: settled payment count, gross, and the builder's 70% share."""
    if not X402_ENABLED:
        raise HTTPException(status_code=503, detail="x402 payments are not enabled on this gateway")
    body = await _body(request)
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        email, _org, _role = _team_caller(cur, body.get("api_key"))
        cur.execute(ph("SELECT owner_email FROM agents WHERE id = ?"), (agent_id,))
        a = cur.fetchone()
        if not a:
            raise HTTPException(status_code=404, detail="agent not found")
        if a["owner_email"] != email:
            raise HTTPException(status_code=403, detail="not your agent")
        cur.execute(ph("SELECT COUNT(*) AS n, COALESCE(SUM(amount_atomic), 0) AS total FROM agent_payments WHERE agent_id = ?"), (agent_id,))
        row = cur.fetchone()
        n = int(row["n"] or 0); total = int(row["total"] or 0)
        return {"agent_id": agent_id, "payments": n, "grossAtomic": str(total),
                "builderAtomic": str(total * X402_BUILDER_BPS // 10000), "builderBps": X402_BUILDER_BPS,
                "network": X402_NETWORK, "dryRun": not bool(X402_FACILITATOR)}
    except HTTPException:
        conn.rollback(); raise
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
# Layer-2 liveness: the last time a Layer-2 client (CLI/Studio) handshook with THIS instance via
# /meter. The gateway can't observe a client's local loopback channel directly — but every governed
# run pings /meter, so recent /meter activity is the real "clients are actively syncing" signal.
# In-memory + per-instance + since-boot (resets on redeploy); surfaced read-only on /health.
LAYER2_SYNC_WINDOW_SEC = 900   # 15 min
_LAST_METER_AT = None


@app.post("/meter")
async def meter(request: Request):
    """Book a governed-run ping against the consumer's prepaid balance: runs_used += N,
    free_runs_remaining -= N.

    BLIND by design. A client may send only {key_hash, nonce, action}: the SHA-256 of its api_key (so
    the RAW key never traverses the wire), a one-time nonce (replay protection), and the action. No run
    data, schema, log, or business variable is ever sent to or accepted by this endpoint — it is a
    metering register, not a data sink. Legacy clients sending {api_key, run_count, idempotency_key}
    keep working unchanged. Deduped on the nonce via the SAME processed_events table the Stripe webhook
    uses, so a retry can't double-bill. One source of truth — the consumers row that /v1/balance reads
    and get_metering() sums."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    api_key = body.get("api_key")                           # legacy: raw key (still accepted)
    key_hash = body.get("key_hash")                         # blind: SHA-256 of the api_key — preferred
    run_count = body.get("run_count")
    if run_count is None and body.get("action") == "decrement_run":
        run_count = 1                                       # blind handshake: the action implies one run
    nonce = body.get("nonce") or body.get("idempotency_key")    # one-time replay/dedup token
    # Resolve the lookup hash: prefer the client-supplied key_hash (blind path); else hash the raw key.
    if isinstance(key_hash, str) and key_hash.strip():
        lookup_hash = key_hash.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", lookup_hash):
            raise HTTPException(status_code=400, detail="invalid key_hash")
    elif isinstance(api_key, str) and api_key:
        lookup_hash = _hash_key(api_key)
    else:
        raise HTTPException(status_code=400, detail="missing key_hash")
    if isinstance(run_count, bool) or not isinstance(run_count, int) or run_count <= 0 or run_count > 100000:
        raise HTTPException(status_code=400, detail="invalid run_count")
    if not isinstance(nonce, str) or not (1 <= len(nonce) <= 200):
        # The nonce becomes a primary-key row in processed_events, so bound its length — an unbounded
        # client string is needless index/storage pressure. uuid4 hex is 32 chars; 200 is generous.
        raise HTTPException(status_code=400, detail="invalid nonce")
    global _LAST_METER_AT   # a well-formed meter IS a Layer-2 handshake — mark liveness
    _LAST_METER_AT = datetime.now(timezone.utc)
    conn = db_connect()
    try:
        cur = conn.cursor()
        # Replay/idempotency: dedup on the nonce SCOPED to the caller's key + the meter namespace, not the
        # bare client string. processed_events is shared with the Stripe webhook (which writes "cs:<id>");
        # a global nonce let one key's token collide with another key's — or with a cs:<id> — and
        # short-circuit to authorized WITHOUT a decrement (a cross-key / cross-namespace free pass).
        # Binding the row to lookup_hash fixes that: same (key, nonce) → same scoped id, so an
        # at-least-once retry of ONE run still dedups to exactly one charge; a DIFFERENT key sending the
        # same nonce string is a distinct row that books against its own balance. Blind-safe — built only
        # from key_hash + nonce, both already on the wire. And because the insufficient-balance path below
        # rolls back WITHOUT burning the scoped id, the only outcome a scoped id can ever record is a
        # SUCCESSFUL booking — so a duplicate here is, by construction, THIS key's own already-authorized
        # run, never a fresh free pass. (No outcome column needed unless that rollback policy changes.)
        scoped_event = "meter:" + lookup_hash + ":" + nonce
        cur.execute(ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                       "ON CONFLICT (event_id) DO NOTHING"),
                    (scoped_event, datetime.now(timezone.utc).isoformat()))
        if cur.rowcount == 0:
            conn.commit()
            return {"status": "success", "note": "duplicate ignored", "authorized": True}
        # MARGIN VAULT (A5): atomic conditional deduction — book ONLY if the prepaid balance covers it
        # (floor in the WHERE clause, so concurrent runs can never drive a key below zero). The blind
        # path matches by api_key_hash alone (no raw key sent); the legacy raw-key path keeps the
        # `api_key` OR fallback for any row that predates the hash backfill.
        if isinstance(api_key, str) and api_key:
            cur.execute(ph("UPDATE consumers SET runs_used = runs_used + ?, "
                           "free_runs_remaining = free_runs_remaining - ? "
                           "WHERE (api_key_hash = ? OR api_key = ?) AND (allocated_runs - runs_used) >= ?"),
                        (run_count, run_count, lookup_hash, api_key, run_count))
        else:
            cur.execute(ph("UPDATE consumers SET runs_used = runs_used + ?, "
                           "free_runs_remaining = free_runs_remaining - ? "
                           "WHERE api_key_hash = ? AND (allocated_runs - runs_used) >= ?"),
                        (run_count, run_count, lookup_hash, run_count))
        if cur.rowcount == 0:
            # Nothing booked → DON'T burn the nonce (a retry after a top-up must succeed). Roll back,
            # then disambiguate: unknown key (401) vs known key with insufficient balance (402).
            conn.rollback()
            c2 = conn.cursor()
            c2.execute(ph("SELECT 1 FROM consumers WHERE api_key_hash = ?"), (lookup_hash,))
            if not c2.fetchone():
                raise HTTPException(status_code=401, detail="unknown key")
            raise HTTPException(status_code=402, detail="insufficient flows — top up to continue")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="database error")
    finally:
        conn.close()
    return {"status": "success", "runs_recorded": run_count, "authorized": True}


# ---- hosted compose: the Builder's default brain ----------------------------
# The Studio's describe→chat/build runs on the PLATFORM's Groq key by default
# (groq_key()'s contract: "PLATFORM-powered, never BYOK"). The key lives ONLY in
# this process's env — it never ships inside the .app, where it would be
# extractable. Each call is one governed flow, booked with the SAME atomic
# guarded decrement as /meter, and REFUNDED if the model call fails (saga).
# ZERO RETENTION: messages are proxied, never persisted, never logged.
_COMPOSE_MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")   # allowlist, smallest surface


# sha256 of the operator's rc_ key — a HASH, not a secret (preimage-resistant;
# committing it grants nothing). Possession of the matching raw key = operator.
_PLATFORM_OWNER_KEY_HASHES = {
    "ede45f40908768b369464fcc3b2723ef294d399c0146079d1c1e3eda14d6985b",
}


@app.post("/v1/admin/bootstrap_model_key")
def bootstrap_model_key(request: Request, body: dict = Body(...)):
    """Owner-only, terminal-first provisioning of the hosted engine's model key —
    exists so the platform key can be set/rotated WITHOUT a dashboard session.
    Auth = possession of the operator rc_ key whose sha256 is pinned above,
    compared constant-time. The Groq key is shape-validated, stored in
    platform_config, never logged, never echoed back by any endpoint."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down")
    ch = _hash_key(body.get("api_key"))
    if not ch or not any(hmac.compare_digest(ch, h) for h in _PLATFORM_OWNER_KEY_HASHES):
        raise HTTPException(status_code=403, detail="not the operator key")
    gk = body.get("groq_api_key")
    if not (isinstance(gk, str) and gk.startswith("gsk_") and 20 <= len(gk) <= 256
            and gk.isascii() and gk.isprintable() and not any(c.isspace() for c in gk)):
        raise HTTPException(status_code=400, detail="that does not look like a Groq key (gsk_…)")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute("CREATE TABLE IF NOT EXISTS platform_config (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        # THE LOCK: an existing key is SET-ONCE. Overwriting it demands the owner
        # key AND an explicit {"confirm_rotate": true} — a re-run, a script replay,
        # or a fat-fingered second call can never drift the platform default.
        cur.execute(ph("SELECT v FROM platform_config WHERE k = ?"), ("GROQ_API_KEY",))
        row = cur.fetchone()
        existing = (row["v"] if row and not isinstance(row, tuple) else (row[0] if row else None))
        if existing and existing.strip() and body.get("confirm_rotate") is not True:
            raise HTTPException(status_code=409,
                                detail="platform key is LOCKED — pass confirm_rotate:true to rotate it deliberately")
        c2 = conn.cursor()
        c2.execute(ph("INSERT INTO platform_config (k, v) VALUES (?, ?) "
                      "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v"), ("GROQ_API_KEY", gk))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "locked": True,
            "note": "hosted engine key %s — locked as the platform default"
                    % ("rotated" if existing else "set")}


@app.post("/v1/admin/bootstrap_email_key")
def bootstrap_email_key(request: Request, body: dict = Body(...)):
    """Owner-only, terminal-first provisioning of the transactional-email creds —
    same shape as bootstrap_model_key, so RESEND_API_KEY + EMAIL_FROM can be set
    WITHOUT a Render dashboard session. Auth = possession of the operator rc_ key
    whose sha256 is pinned in _PLATFORM_OWNER_KEY_HASHES, compared constant-time.
    Stored in platform_config; _send_email reads it there first. Never logged,
    never echoed back. Re-runnable: email creds are set-or-update (no set-once
    lock — a rotated Resend key should just take effect)."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down")
    ch = _hash_key(body.get("api_key"))
    if not ch or not any(hmac.compare_digest(ch, h) for h in _PLATFORM_OWNER_KEY_HASHES):
        raise HTTPException(status_code=403, detail="not the operator key")
    rk = body.get("resend_api_key")
    if not (isinstance(rk, str) and rk.startswith("re_") and 20 <= len(rk) <= 256
            and rk.isascii() and rk.isprintable() and not any(c.isspace() for c in rk)):
        raise HTTPException(status_code=400, detail="that does not look like a Resend key (re_…)")
    ef = body.get("email_from") or EMAIL_FROM
    if not (isinstance(ef, str) and 3 <= len(ef) <= 200 and "@" in ef and ef.isprintable()):
        raise HTTPException(status_code=400, detail="email_from must be a sender like 'RailCall <noreply@railcall.ai>'")
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute("CREATE TABLE IF NOT EXISTS platform_config (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        c2 = conn.cursor()
        for k, v in (("RESEND_API_KEY", rk), ("EMAIL_FROM", ef)):
            c2.execute(ph("INSERT INTO platform_config (k, v) VALUES (?, ?) "
                          "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v"), (k, v))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "email_from": ef,
            "note": "transactional email activated — RESEND_API_KEY stored, reset/invite emails now send"}


def _cell(row, key, idx):
    """Read one column across both DB backends (RealDict on PG, tuple/Row on SQLite)."""
    if row is None:
        return None
    if isinstance(row, tuple):
        return row[idx]
    try:
        return row[key]
    except Exception:
        return row[idx]


@app.post("/v1/admin/overview")
def admin_overview(request: Request, body: dict = Body(...)):
    """Owner-only command center: unifies SIGNUPS (from the consumers table — every account,
    free and paid) with MONEY (from Stripe, the source of truth for revenue). Auth = the operator
    rc_ key whose sha256 is pinned in _PLATFORM_OWNER_KEY_HASHES, constant-time compared — the same
    gate as the bootstrap endpoints. Read-only. Never returns api_keys or password hashes."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down")
    ch = _hash_key(body.get("api_key"))
    if not ch or not any(hmac.compare_digest(ch, h) for h in _PLATFORM_OWNER_KEY_HASHES):
        raise HTTPException(status_code=403, detail="not the operator key")

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cut_24h = (now - timedelta(hours=24)).isoformat()
    cut_7d = (now - timedelta(days=7)).isoformat()

    signups = {"total": 0, "free": 0, "paid": 0, "last_24h": 0, "last_7d": 0}
    recent = []
    conn = db_connect()
    try:
        cur = db_cursor(conn)
        cur.execute("SELECT count(*) AS n FROM consumers")
        signups["total"] = int(_cell(cur.fetchone(), "n", 0) or 0)
        cur.execute("SELECT plan, count(*) AS n FROM consumers GROUP BY plan")
        for r in cur.fetchall():
            plan = (_cell(r, "plan", 0) or "free")
            n = int(_cell(r, "n", 1) or 0)
            if plan == "free":
                signups["free"] += n
            else:
                signups["paid"] += n
        cur.execute(ph("SELECT count(*) AS n FROM consumers WHERE created_at >= ?"), (cut_24h,))
        signups["last_24h"] = int(_cell(cur.fetchone(), "n", 0) or 0)
        cur.execute(ph("SELECT count(*) AS n FROM consumers WHERE created_at >= ?"), (cut_7d,))
        signups["last_7d"] = int(_cell(cur.fetchone(), "n", 0) or 0)
        cur.execute("SELECT email, plan, free_runs_remaining, runs_used, status, source, "
                    "stripe_customer_id, created_at FROM consumers ORDER BY created_at DESC LIMIT 50")
        for r in cur.fetchall():
            recent.append({
                "email": _cell(r, "email", 0),
                "plan": _cell(r, "plan", 1),
                "flows_remaining": _cell(r, "free_runs_remaining", 2),
                "flows_used": _cell(r, "runs_used", 3),
                "status": _cell(r, "status", 4),
                "source": _cell(r, "source", 5),
                "paying": bool(_cell(r, "stripe_customer_id", 6)),
                "created_at": _cell(r, "created_at", 7),
            })
    finally:
        conn.close()

    # MONEY — Stripe is the source of truth. Best-effort; if the key/call fails, signups still return.
    revenue = {"available": False}
    try:
        charges = stripe.Charge.list(limit=100)
        paid = [c for c in charges.auto_paging_iter()] if hasattr(charges, "auto_paging_iter") else charges.get("data", [])
        succeeded = [c for c in paid if getattr(c, "paid", False) and getattr(c, "status", "") == "succeeded" and not getattr(c, "refunded", False)]
        gross = sum(int(getattr(c, "amount", 0)) for c in succeeded)
        revenue = {
            "available": True,
            "gross_usd": round(gross / 100.0, 2),
            "payments": len(succeeded),
            "recent": [{
                "amount_usd": round(int(getattr(c, "amount", 0)) / 100.0, 2),
                "email": (getattr(c, "billing_details", None) or {}).get("email") if isinstance(getattr(c, "billing_details", None), dict) else getattr(getattr(c, "billing_details", None), "email", None),
                "created": getattr(c, "created", None),
                "status": getattr(c, "status", None),
            } for c in succeeded[:20]],
        }
    except Exception as e:
        revenue = {"available": False, "note": "Stripe read unavailable: %s" % str(e)[:120]}

    return {"ok": True, "generated_at": now.isoformat(), "signups": signups,
            "recent_signups": recent, "revenue": revenue}


def _platform_model_key():
    """Resolve the hosted engine's model key. THE LOCKED ROW WINS: once the
    operator has set the platform key (owner-gated bootstrap), it IS the default
    — no exceptions, no drifting. A stray/wrong env var cannot silently override
    it; env is only the fallback when no locked row exists (first boot). The key
    lives in the same private Postgres that already holds billing state; no
    endpoint ever echoes it. Rotation = owner key + confirm_rotate:true, only."""
    try:
        conn = db_connect()
        cur = db_cursor(conn)
        cur.execute("CREATE TABLE IF NOT EXISTS platform_config (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        cur.execute(ph("SELECT v FROM platform_config WHERE k = ?"), ("GROQ_API_KEY",))
        row = cur.fetchone()
        conn.close()
        if row:
            v = row["v"] if not isinstance(row, tuple) else row[0]
            if (v or "").strip():
                return v.strip()          # the locked platform default
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", "").strip()   # first-boot fallback only


def _groq_complete(messages, model):
    """One bounded chat completion against Groq with the platform key. stdlib only."""
    gk = _platform_model_key()
    if not gk:
        raise HTTPException(status_code=503,
                            detail="hosted engine not configured (GROQ_API_KEY unset)")
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload, method="POST",
        # Groq sits behind Cloudflare, which 403s (error 1010) the default
        # "Python-urllib" client signature — an explicit UA is REQUIRED.
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + gk,
                 "User-Agent": "RailCall/1.0 (+https://railcall.ai)"},
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        out = json.loads(r.read().decode())
    return (out.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


@app.post("/v1/compose")
def compose(request: Request, body: dict = Body(...)):
    """{api_key, messages, model?, nonce?} -> {ok, reply, model, flows_remaining}.
    Sync def on purpose: FastAPI threadpools it, so the blocking Groq call can't
    stall the event loop. Books 1 flow BEFORE the model call; refunds on failure."""
    if not _signup_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts — slow down and retry shortly")
    api_key = body.get("api_key")
    messages = body.get("messages")
    model = body.get("model") or _COMPOSE_MODELS[0]
    if model not in _COMPOSE_MODELS:
        raise HTTPException(status_code=400, detail="unknown model")
    if not isinstance(messages, list) or not messages or len(messages) > 40:
        raise HTTPException(status_code=400, detail="messages: non-empty list, max 40")
    clean = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
            raise HTTPException(status_code=400, detail="bad message role")
        c = m.get("content")
        if not isinstance(c, str) or len(c) > 24000:
            raise HTTPException(status_code=400, detail="bad message content (max 24k chars)")
        clean.append({"role": m["role"], "content": c})
    nonce = body.get("nonce")
    if nonce is not None and (not isinstance(nonce, str) or not (1 <= len(nonce) <= 200)):
        raise HTTPException(status_code=400, detail="invalid nonce")
    conn = db_connect()
    booked = False
    lookup_hash = None
    try:
        cur = db_cursor(conn)
        row = _consumer_by_key(cur, api_key, "id, api_key_hash, allocated_runs, runs_used")
        if not row:
            raise HTTPException(status_code=401, detail="unknown key — sign up free at railcall.ai")
        lookup_hash = row["api_key_hash"] or _hash_key(api_key)
        if nonce:  # optional client idempotency (a timeout retry must not double-bill)
            scoped_event = "compose:" + lookup_hash + ":" + nonce
            c2 = conn.cursor()
            c2.execute(ph("INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?) "
                          "ON CONFLICT (event_id) DO NOTHING"),
                       (scoped_event, datetime.now(timezone.utc).isoformat()))
            if c2.rowcount == 0:
                conn.commit()
                raise HTTPException(status_code=409, detail="duplicate compose nonce — already served")
        # book the flow FIRST (atomic floor guard — concurrency can't drive below zero)
        c3 = conn.cursor()
        c3.execute(ph("UPDATE consumers SET runs_used = runs_used + 1, "
                      "free_runs_remaining = free_runs_remaining - 1 "
                      "WHERE api_key_hash = ? AND (allocated_runs - runs_used) >= 1"),
                   (lookup_hash,))
        if c3.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=402, detail="no flows remaining — top up at railcall.ai/dashboard")
        conn.commit()
        booked = True
        try:
            reply = _groq_complete(clean, model)   # content proxied only — never stored, never logged
        except Exception as e:
            # ANY failure after booking — incl. the 503 key-unset HTTPException —
            # compensates first (saga refund), THEN surfaces honestly.
            try:
                c5 = conn.cursor()
                c5.execute(ph("UPDATE consumers SET runs_used = runs_used - 1, "
                              "free_runs_remaining = free_runs_remaining + 1 "
                              "WHERE api_key_hash = ?"), (lookup_hash,))
                conn.commit()
            except Exception:
                pass
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=502, detail="hosted engine call failed — flow refunded, try again")
        c4 = db_cursor(conn)
        c4.execute(ph("SELECT (allocated_runs - runs_used) AS rem FROM consumers WHERE api_key_hash = ?"),
                   (lookup_hash,))
        rem = c4.fetchone()
        remaining = rem["rem"] if rem else None
        return {"ok": True, "reply": reply, "model": model, "flows_remaining": remaining}
    finally:
        conn.close()


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
    # Layer-2 sync liveness: true iff a client (CLI/Studio) handshook via /meter within the window.
    # Honest scope: per-instance, in-memory, since boot — reflects incoming client meter-pings, NOT a
    # literal loopback probe (the gateway can't reach a client's local loopback).
    layer2 = (_LAST_METER_AT is not None
              and (datetime.now(timezone.utc) - _LAST_METER_AT).total_seconds() < LAYER2_SYNC_WINDOW_SEC)
    return {"status": "ONLINE",
            "db_mode": "PostgreSQL" if USE_PG else "SQLite",
            "consumers_registered": count,
            "layer2_sync_active": bool(layer2),
            "last_meter_at": _LAST_METER_AT.isoformat() if _LAST_METER_AT else None,
            "commit": os.environ.get("RENDER_GIT_COMMIT", "local")[:12],  # Render injects the deployed SHA at runtime → /health is SHA-verifiable
            "redirect_base": DOMAIN_URL}


if __name__ == "__main__":
    import uvicorn
    print(f"Railcall Cloud Gateway -> http://{HOST}:{PORT}  (db: {'postgres' if USE_PG else 'sqlite'})")
    print(f"  Stripe key: {'set' if STRIPE_SECRET_KEY else 'MISSING'}  |  webhook secret: {'set' if STRIPE_WEBHOOK_SECRET else 'MISSING'}")
    uvicorn.run(app, host=HOST, port=PORT)
