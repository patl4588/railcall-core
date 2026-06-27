#!/bin/bash
# Boot a throwaway instance of the PRODUCTION gateway code on a fresh SQLite DB and run the
# metering + auth QA suites against its live HTTP surface. Zero prod impact. Re-runnable.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"; GW="$HERE/../cloud_gateway.py"; PORT="${PORT:-8911}"
QADIR="$(mktemp -d)"; cd "$QADIR"
HOST=127.0.0.1 PORT="$PORT" python3 "$GW" > gw.log 2>&1 & GWPID=$!
for i in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" 2>/dev/null && break; sleep 0.3; done
COMMIT="$(cd "$HERE/.." && git rev-parse --short HEAD 2>/dev/null || echo local)"
echo '########## METERING ($0.01/flow) ##########'
QA_BASE="http://127.0.0.1:$PORT" QA_EMAIL="qa-meter-$(date +%s)@railcall.ai" python3 "$HERE/qa_meter.py"; echo "METER_EXIT=$?"
echo; echo '########## SIGNUP / AUTH ##########'
QA_BASE="http://127.0.0.1:$PORT" python3 "$HERE/auth_qa.py"; echo "AUTH_EXIT=$?"
echo; echo "gateway commit under test: $COMMIT | db: fresh sqlite"
kill $GWPID 2>/dev/null; rm -rf "$QADIR"
