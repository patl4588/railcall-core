#!/usr/bin/env bash
# Build a clean railcall_station.tar.gz suitable for fresh installs.
# Excludes all internal specs, attack corpora, audit telemetry, test files,
# dev sources (ui/src), node_modules, logs, caches, user workspaces.
#
# Usage (from repo root or with STATION_SRC):
#   STATION_SRC="$HOME/.railcall/station" ./scripts/build_station_tar.sh
# Output: /tmp/railcall_station.tar.gz
set -euo pipefail

STATION_SRC="${STATION_SRC:-$HOME/.railcall/station}"
OUT="${OUT:-/tmp/railcall_station.tar.gz}"

if [[ ! -d "$STATION_SRC/workbench" ]]; then
  echo "ERROR: $STATION_SRC does not look like a station tree (missing workbench/)" >&2
  exit 1
fi

echo "Packaging clean station from: $STATION_SRC"
echo "Output: $OUT"

# Ensure minimal required dirs for Bug 47 (transaction_runs + workflows for non-empty TRUSTED_REUSE)
mkdir -p "$STATION_SRC/transaction_runs" "$STATION_SRC/workflows"
touch "$STATION_SRC/transaction_runs/.gitkeep" "$STATION_SRC/workflows/.gitkeep"

# One trusted example so /api/workflows is not empty on fresh install
if [[ ! -f "$STATION_SRC/workflows/signup_to_sheet.json" ]]; then
  cat > "$STATION_SRC/workflows/signup_to_sheet.json" <<'J'
{
  "id": "signup_to_sheet",
  "title": "signup_to_sheet",
  "tag": "outbound rail",
  "desc": "Customer signup lands in webhook_in → RailCall formats a row → appends it to your Google Sheet. (TRUSTED_REUSE of audited library)",
  "nodes": 3,
  "steps": ["webhook_in", "format_row", "google_sheets.append_row"],
  "integrity_root": "sha256:trusted0",
  "result": "TRUSTED_REUSE"
}
J
fi

cd "$STATION_SRC"
# workbench/mcp_server.py ships AS-IS from the source tree (engine main's
# airlock MCP since v1 §4 / engine PR #15). The pre-v1 line that copied
# mcp_capoff_server.py over it is gone — it silently clobbered the airlock in
# the first v0.4 cut. mcp_capoff_server.py still ships under its OWN name:
# the cap-off #16 workflow (primitives/mcp_loopback.py) spawns it by filename.
if ! grep -q 'railcall-airlock' workbench/mcp_server.py 2>/dev/null; then
  echo "ERROR: workbench/mcp_server.py is not the airlock MCP (engine main)." >&2
  echo "       Overlay engine main's workbench/ into STATION_SRC before building." >&2
  exit 1
fi

tar --exclude='tests' \
    --exclude='ui/node_modules' \
    --exclude='ui/src' \
    --exclude='ui/package.json' \
    --exclude='ui/package-lock.json' \
    --exclude='ui/*.config.*' \
    --exclude='ui/tsconfig*' \
    --exclude='ui/eslint*' \
    --exclude='ui/*.tsbuildinfo' \
    --exclude='ui/*.md' \
    --exclude='workbench/CONSTITUTION.md' \
    --exclude='workbench/ENTERPRISE_CONSOLE_SPEC.md' \
    --exclude='workbench/PHASE6_BYOK_SPEC.md' \
    --exclude='workbench/competitor_redteam_corpus.json' \
    --exclude='workbench/fresh_attacks.json' \
    --exclude='workbench/adversarial_verify_findings.json' \
    --exclude='workbench/layer2_audit_telemetry.json' \
    --exclude='workbench/wire_groq.py' \
    --exclude='workbench/layer2_fortress_audit.py' \
    --exclude='workbench/*test*.py' \
    --exclude='workbench/*.bak*' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.log' \
    --exclude='.railcall_workspace' \
    --exclude='studio_relaunch.log' \
    -czf "$OUT" .

ls -lh "$OUT"
echo "Done. Verify with: tar -tzf $OUT | grep -E '(CONSTITUTION|test_|node_modules|wire_groq)' || echo 'clean (no matches)'"
