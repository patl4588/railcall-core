#!/usr/bin/env python3
"""
test_workflow.py — end-to-end CLI test for the RailCall workflow executor.

Usage:
  python3 test_workflow.py              # dry-run (no Discord key needed)
  python3 test_workflow.py --live       # real Discord send (needs webhook in vault)
  python3 test_workflow.py --csv /path/to/file.csv
  python3 test_workflow.py --live --csv mydata.csv

What it does:
  1. Creates a sample CSV (or uses --csv path)
  2. Runs: csv_read → message_template → discord_send
  3. Prints a step-by-step receipt

Add your Discord webhook in Studio → Integrate → discord (DISCORD_WEBHOOK_URL)
or pass DISCORD_WEBHOOK_URL as an environment variable.
"""
import os
import sys
import json
import tempfile

# ── Locate workflow_runner ────────────────────────────────────────────────────
WORKBENCH = os.path.expanduser("~/.railcall/station/workbench")
if WORKBENCH not in sys.path:
    sys.path.insert(0, WORKBENCH)

try:
    import workflow_runner as wr
except ImportError:
    print("ERROR: workflow_runner not found at", WORKBENCH)
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────
args      = sys.argv[1:]
live      = "--live" in args
csv_path  = None
if "--csv" in args:
    idx = args.index("--csv")
    if idx + 1 < len(args):
        csv_path = args[idx + 1]

# ── Sample CSV (used when no --csv given) ─────────────────────────────────────
SAMPLE_CSV = """\
name,email,role,joined
Sami Ben Chaalia,sami@railcall.ai,founder,2024-01-01
Ahmad Khalil,ahmad@railcall.ai,engineer,2024-03-15
Lena Park,lena@railcall.ai,qa,2024-06-01
Omar Khalil,omar@railcall.ai,designer,2024-07-10
""".strip()

tmp_csv = None
if not csv_path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, prefix="railcall_test_")
    tmp.write(SAMPLE_CSV)
    tmp.close()
    tmp_csv  = tmp.name
    csv_path = tmp_csv

# ── Vault (from keys.local.json) ─────────────────────────────────────────────
VAULT_PATH = os.path.expanduser("~/.railcall/station/.railcall_workspace/keys.local.json")
vault = {}
if os.path.exists(VAULT_PATH):
    try:
        vault = json.load(open(VAULT_PATH))
    except Exception:
        pass

# Allow env var override
if os.environ.get("DISCORD_WEBHOOK_URL"):
    vault.setdefault("discord", {})
    if isinstance(vault["discord"], dict):
        vault["discord"]["DISCORD_WEBHOOK_URL"] = os.environ["DISCORD_WEBHOOK_URL"]

# ── Workflow spec ─────────────────────────────────────────────────────────────
spec = {
    "name": "csv_to_discord",
    "steps": [
        {
            "id":     "read",
            "type":   "csv_read",
            "config": {"path": csv_path},
        },
        {
            "id":     "format",
            "type":   "message_template",
            "config": {
                "template": "🚂 **RailCall workflow** · {{name}} ({{role}}) · {{email}} · joined {{joined}}"
            },
        },
        {
            "id":     "send",
            "type":   "discord_send",
            "config": {},        # webhook_url resolved from vault
        },
    ],
}

dry_run = not live
mode    = "DRY-RUN" if dry_run else "LIVE"

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RailCall Workflow Executor — {mode}")
print(f"{'='*60}")
print(f"  Workflow : {spec['name']}")
print(f"  CSV      : {csv_path}")
print(f"  Steps    : {' → '.join(s['type'] for s in spec['steps'])}")
disc = vault.get("discord") or {}
has_key = bool((disc.get("DISCORD_WEBHOOK_URL") or disc.get("DISCORD_HOOK_URL") or "").strip()) if isinstance(disc, dict) else False
print(f"  Discord  : {'✓ webhook configured' if has_key else '✗ no webhook — will dry-run'}")
print()

result = wr.run(spec, vault=vault, dry_run=dry_run)

# ── Print receipt ─────────────────────────────────────────────────────────────
for sr in result["steps"]:
    status = "✓" if sr.get("ok") else "✗"
    label  = f"[{sr['id']}] {sr['type']}"
    ms     = sr.get("duration_ms", 0)

    if not sr.get("ok"):
        print(f"  {status} {label} — FAILED ({ms}ms)")
        print(f"      error: {sr.get('error')}")
        continue

    if sr["type"] == "csv_read":
        print(f"  {status} {label} — {sr.get('output_count', 0)} rows read ({ms}ms)")
        for row in (sr.get("sample") or [])[:2]:
            print(f"      → {dict(list(row.items())[:3])}")

    elif sr["type"] == "message_template":
        print(f"  {status} {label} — {sr.get('output_count', 0)} messages formatted ({ms}ms)")
        for msg in (sr.get("sample") or [])[:2]:
            print(f"      → {msg[:80]}")

    elif sr["type"] in ("discord_send", "slack_send"):
        out   = sr.get("output", {})
        n     = out.get("sent", 0)
        errs  = out.get("errors", [])
        drn   = out.get("dry_run", False)
        verb  = "would send" if drn else "sent"
        print(f"  {status} {label} — {n} message(s) {verb} ({ms}ms)")
        if errs:
            for err in errs[:3]:
                print(f"      ✗ {err}")
        for res in (out.get("results") or [])[:2]:
            if res.get("dry_run"):
                print(f"      [dry] {res.get('content', '')[:70]}")
            else:
                print(f"      [sent] id={res.get('message_id')} · {res.get('content', '')[:50]}")

print()
print(f"  run_id  : {result['run_id']}")
print(f"  result  : {'OK' if result['ok'] else 'FAILED'}")
print(f"  summary : {result['summary']}")
print(f"{'='*60}\n")

# cleanup temp file
if tmp_csv and os.path.exists(tmp_csv):
    os.unlink(tmp_csv)

if not result["ok"]:
    sys.exit(1)

if dry_run and not has_key:
    print("  To send for real:")
    print("  1. Open Studio → Integrate → discord → paste DISCORD_WEBHOOK_URL")
    print("  2. Re-run: python3 test_workflow.py --live")
    print()
