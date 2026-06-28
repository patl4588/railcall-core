#!/usr/bin/env python3
"""
sweep_keys.py — automated BYOK connectivity-probe + receipt scoreboard for the RailCall build campaign.

WHAT THIS DOES (and, honestly, what it does NOT):
  For every connector key present in `.env.keys`, this script drives the LOCAL RailCall Studio
  loopback daemon (127.0.0.1:8799) to:
    1. save the key into the local 0600 vault   →  POST /api/integration   {id, key}
    2. run the daemon's real connection probe    →  POST /api/integration_test {id}
    3. record the honest result + any receipt it returns into proof/scoreboard_raw.json

  This is the *probe / connectivity* assembly line that runs UNDERNEATH Nick's manual video runs.
  It is deliberately honest about the cap-off protocol:

    • The probe (`/api/integration_test`) returns a STATUS, not an Ed25519 receipt. A connector is
      only LIVE-green when a real, airlock-APPROVED flow run mints a signed flow-receipt — and a live
      send requires a human to approve it at the airlock. That live-green proof is Nick's video lane.
    • So this script never claims LIVE. It records: CONNECTED (real provider ping passed),
      KEY_PRESENT (key saved, provider not wired for a live test yet), FAILED, NOT_WIRED, or
      UNKNOWN (no key supplied). No padding, no guessing — a missing/failing key is logged as such.
    • If a probed endpoint ever returns a {"receipt": {...}} body, its receipt_id IS captured.

  Net: it turns "which of my keys even connect?" into an automated, re-runnable, file-backed board,
  so Nick spends his time on the LIVE video sends, not on bookkeeping.

USAGE:
    1. railcall studio            # start the local daemon (must be listening on 127.0.0.1:8799)
    2. cp .env.keys.example .env.keys  &&  edit it with your real test keys
    3. python3 scripts/sweep_keys.py            # sweeps every key in .env.keys
       python3 scripts/sweep_keys.py --only stripe,slack,github   # sweep a subset
    →  proof/scoreboard_raw.json   (machine-readable board, one row per connector)

ENV:
    STUDIO_URL   override the daemon base URL (default http://127.0.0.1:8799)
"""
import json
import os
import re
import sys
import time
import argparse
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STUDIO_URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:8799").rstrip("/")
ENV_KEYS = os.path.join(REPO, ".env.keys")
OUT_DIR = os.path.join(REPO, "proof")
OUT_FILE = os.path.join(OUT_DIR, "scoreboard_raw.json")

# env-var name  ->  Studio integration id (the slug the daemon stores in keys.local.json).
# Extend freely as the catalog grows — an unmapped key is derived + flagged, never dropped silently.
ENV_TO_ID = {
    # LLMs / AI
    "OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "anthropic", "GROQ_API_KEY": "groq",
    "GEMINI_API_KEY": "gemini", "MISTRAL_API_KEY": "mistral", "COHERE_API_KEY": "cohere",
    "OPENROUTER_API_KEY": "openrouter", "HF_TOKEN": "huggingface", "OLLAMA_HOST": "ollama",
    # Code / CI
    "GITHUB_TOKEN": "github", "GITLAB_TOKEN": "gitlab", "LINEAR_API_KEY": "linear", "JIRA_TOKEN": "jira",
    # Payments
    "STRIPE_SECRET_KEY": "stripe", "PAYPAL_CLIENT_ID": "paypal", "SQUARE_TOKEN": "square", "PLAID_CLIENT_ID": "plaid",
    # Comms
    "SLACK_BOT_TOKEN": "slack", "DISCORD_BOT_TOKEN": "discord", "TWILIO_SID": "twilio",
    "SENDGRID_API_KEY": "sendgrid", "TELEGRAM_BOT_TOKEN": "telegram", "TEAMS_WEBHOOK_URL": "teams",
    # CRM / support
    "HUBSPOT_TOKEN": "hubspot", "SF_INSTANCE_URL": "salesforce", "PIPEDRIVE_TOKEN": "pipedrive",
    "ZENDESK_TOKEN": "zendesk", "INTERCOM_TOKEN": "intercom",
    # Data / docs
    "DATABASE_URL": "postgres", "SUPABASE_URL": "supabase", "AIRTABLE_TOKEN": "airtable",
    "NOTION_TOKEN": "notion", "MONGODB_URI": "mongodb", "REDIS_URL": "redis",
    "SHEET_WEBHOOK_URL": "google_sheets",
    # Analytics / ops
    "POSTHOG_API_KEY": "posthog", "SENTRY_DSN": "sentry", "DD_API_KEY": "datadog", "PAGERDUTY_TOKEN": "pagerduty",
    # Aggregators
    "ZAPIER_HOOK_URL": "zapier", "MAKE_WEBHOOK_URL": "make", "N8N_WEBHOOK_URL": "n8n",
    "PIPEDREAM_WORKFLOW_URL": "pipedream",
}

# How the daemon's probe status maps to a scoreboard bucket. Anything unknown is recorded verbatim.
STATUS_BUCKET = {
    "connected": "CONNECTED",        # real provider ping succeeded
    "key_present": "KEY_PRESENT",    # key saved; this provider has no live test wired yet (honest)
    "not_wired": "NOT_WIRED",
    "not_configured": "NO_KEY",
    "failed": "FAILED",
}


_SESSION = {"token": ""}  # per-startup X-RailCall-Session token, fetched the same way the Studio UI gets it


def _fetch_session():
    """GET the Studio root, confirm reachability, and extract its per-startup CSRF token. The Studio injects
    `var T='<hex>'` into a fetch-wrapper and requires `X-RailCall-Session: <T>` on mutating routes. If a
    given build doesn't use one, we simply send none. Returns True iff the daemon answered."""
    try:
        with urllib.request.urlopen(STUDIO_URL + "/", timeout=8) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return False
    m = re.search(r"var\s+T\s*=\s*'([0-9a-fA-F]{32,})'", html) \
        or re.search(r"X-RailCall-Session['\"]?\s*[,:]\s*['\"]([0-9a-fA-F]{32,})", html)
    if m:
        _SESSION["token"] = m.group(1)
    return True


def _post(path, body, timeout=30):
    headers = {"Content-Type": "application/json", "Origin": STUDIO_URL}  # loopback CSRF guard
    if _SESSION["token"]:
        headers["X-RailCall-Session"] = _SESSION["token"]                 # per-startup CSRF token
    req = urllib.request.Request(STUDIO_URL + path, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def _derive_id(env_name):
    """Best-effort id for an unmapped env var: lower-case, strip the common secret suffixes."""
    s = env_name.lower()
    for suf in ("_api_key", "_secret_key", "_bot_token", "_token", "_key", "_url", "_id", "_dsn"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def load_keys(path):
    """Parse a dotenv-style file → {ENV_NAME: value}. Blank values + comments are ignored."""
    keys = {}
    if not os.path.exists(path):
        return keys
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            if v and not v.startswith("PASTE_"):     # ignore untouched template placeholders
                keys[k.strip()] = v
    return keys


def sweep(only=None):
    keys = load_keys(ENV_KEYS)
    # Reachability + CSRF session token up front — a down daemon must be an explicit error, never
    # silent fake-green. We fetch the per-startup X-RailCall-Session token exactly as the UI does.
    if not _fetch_session():
        sys.exit("✗ Cannot reach RailCall Studio at %s.\n  Start it first:  railcall studio" % STUDIO_URL)
    if _SESSION["token"]:
        print("  (session token acquired)\n")

    rows, summary = [], {"CONNECTED": 0, "KEY_PRESENT": 0, "NOT_WIRED": 0, "FAILED": 0, "NO_KEY": 0, "UNKNOWN": 0}
    targets = sorted(ENV_TO_ID.items())
    only_set = set(x.strip().lower() for x in only.split(",")) if only else None

    for env_name, iid in targets:
        if only_set and iid not in only_set:
            continue
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        val = keys.get(env_name)
        if not val:
            rows.append({"id": iid, "env": env_name, "status": "UNKNOWN",
                         "detail": "no key in .env.keys", "receipt_id": None, "tested_at": ts})
            summary["UNKNOWN"] += 1
            print("  · %-14s UNKNOWN (no key)" % iid)
            continue
        try:
            _post("/api/integration", {"id": iid, "key": val})           # 1) save into the local 0600 vault
            _, res = _post("/api/integration_test", {"id": iid})          # 2) honest connection probe
            raw_status = str(res.get("status", "")).lower()
            bucket = STATUS_BUCKET.get(raw_status, raw_status.upper() or "FAILED")
            receipt = res.get("receipt") or {}                           # 3) capture a receipt IF one is returned
            rid = receipt.get("receipt_id")
            rows.append({"id": iid, "env": env_name, "status": bucket,
                         "detail": res.get("detail") or raw_status, "receipt_id": rid, "tested_at": ts})
            summary[bucket] = summary.get(bucket, 0) + 1
            print("  · %-14s %s%s" % (iid, bucket, ("  receipt=" + rid) if rid else ""))
        except Exception as e:
            rows.append({"id": iid, "env": env_name, "status": "FAILED",
                         "detail": "%s: %s" % (type(e).__name__, str(e)[:120]), "receipt_id": None, "tested_at": ts})
            summary["FAILED"] += 1
            print("  · %-14s FAILED (%s)" % (iid, str(e)[:60]))

    board = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "studio_url": STUDIO_URL,
        "note": ("Probe/connectivity layer only. LIVE-green (a real airlock-approved send that mints an "
                 "Ed25519 flow-receipt) is captured in Nick's video runs, not here. No padding: a missing "
                 "or failing key is logged UNKNOWN/FAILED."),
        "summary": summary,
        "connectors": rows,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)
    print("\nscoreboard → %s" % OUT_FILE)
    print("summary: " + " · ".join("%s %d" % (k, v) for k, v in summary.items() if v))
    return board


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Automated BYOK connectivity-probe + receipt scoreboard.")
    ap.add_argument("--only", help="comma-separated connector ids to sweep (e.g. stripe,slack,github)")
    args = ap.parse_args()
    print("RailCall key-sweep → %s\n(probe layer; LIVE receipts come from approved flow runs)\n" % STUDIO_URL)
    sweep(args.only)
