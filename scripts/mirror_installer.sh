#!/usr/bin/env bash
# Mirror install.sh from railcall-core to railcall-contrib/website-v2/public
# so `curl -sSL https://railcall.ai/install.sh | bash` serves the same bytes
# as `curl -sSL https://raw.githubusercontent.com/patl4588/railcall-core/main/install.sh | bash`.
#
# Root cause this exists to prevent:
#
#   Every station cut bumps install.sh here (STATION_SHA, STATION_URL, CLI
#   pin, telemetry version). If the copy in contrib/website-v2/public/
#   isn't refreshed at the same time, the site serves a stale install.sh
#   that pins yesterday's CLI SHA. When it runs, it correctly fetches the
#   NEW CLI from raw.githubusercontent, then refuses it because the on-disk
#   copy doesn't match the stale pin. Users see a scary SECURITY message
#   for what's actually a mirror rot bug.
#
# Run this as part of every station cut, right after bumping install.sh.
# Exits nonzero (loudly) if the mirror already matched — makes it easy to
# see when the release ritual missed the mirror step.

set -euo pipefail

CORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRIB_DIR="${RAILCALL_CONTRIB_DIR:-$(cd "$CORE_DIR/../railcall-contrib" 2>/dev/null && pwd || true)}"

if [ -z "$CONTRIB_DIR" ] || [ ! -d "$CONTRIB_DIR/website-v2/public" ]; then
  echo "✗ can't find railcall-contrib/website-v2/public" >&2
  echo "   expected at: $CORE_DIR/../railcall-contrib" >&2
  echo "   or set RAILCALL_CONTRIB_DIR=/path/to/railcall-contrib" >&2
  exit 1
fi

SRC="$CORE_DIR/install.sh"
DST="$CONTRIB_DIR/website-v2/public/install.sh"

if [ ! -f "$SRC" ]; then
  echo "✗ source not found: $SRC" >&2; exit 1
fi

if cmp -s "$SRC" "$DST"; then
  echo "  · install.sh mirror already matches — nothing to do"
  exit 0
fi

# Show the substantive diff before overwriting so the release-cutter
# sees exactly what's being mirrored (SHA bumps, URL bumps).
echo "→ mirroring $SRC → $DST"
echo "  diff:"
diff "$SRC" "$DST" | head -20 || true

cp "$SRC" "$DST"

echo ""
echo "  ✓ mirrored. Now:"
echo "    cd $CONTRIB_DIR"
echo "    git add website-v2/public/install.sh"
echo "    git commit -m 'chore: mirror install.sh (release cut)'"
echo "    git push"
echo ""
echo "  Then trigger a website redeploy so nginx serves the new bytes."
