#!/bin/bash
# Sign + notarize + staple "RailCall Studio.app" inside RailCall-Studio.zip so it opens with a normal
# one-click confirmation instead of the Gatekeeper "Apple cannot check it for malicious software" BLOCK.
#
# Operates on the already-built RailCall-Studio.zip (run tools/make_studio_app.sh first). Decoupled on
# purpose so the unsigned build keeps working and this only runs once your Apple cert + notary creds exist.
#
# ── ONE-TIME PREREQUISITES (Pat does these — they need Apple ID auth I cannot perform) ───────────────
#   1) A "Developer ID Application" certificate in your login keychain. Easiest path:
#        Xcode ▸ Settings ▸ Accounts ▸ (add your Apple ID) ▸ Manage Certificates… ▸ "+" ▸ Developer ID Application
#      (If that menu item is greyed out, your enrollment is still provisioning — wait a few hours, retry.)
#   2) Cache notary credentials under a keychain profile named "railcall-notary":
#        xcrun notarytool store-credentials "railcall-notary" \
#          --apple-id "YOUR_APPLE_ID_EMAIL" --team-id "YOUR_TEAM_ID" --password "APP_SPECIFIC_PASSWORD"
#      • YOUR_TEAM_ID: developer.apple.com ▸ Membership details ▸ Team ID (10 chars).
#      • APP_SPECIFIC_PASSWORD: appleid.apple.com ▸ Sign-In & Security ▸ App-Specific Passwords ▸ "+".
#        (NOT your normal Apple ID password. notarytool stores it in the keychain; this script never sees it.)
#
# Usage: tools/sign_and_notarize.sh [notary-profile]   (default profile: railcall-notary)
set -euo pipefail
PROFILE="${1:-${RAILCALL_NOTARY_PROFILE:-railcall-notary}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="$ROOT/RailCall-Studio.zip"
[ -f "$ZIP" ] || { echo "ERROR: $ZIP not found — run tools/make_studio_app.sh first."; exit 1; }

# 1) Resolve the Developer ID Application identity from the keychain — no hardcoded Team ID / cert name.
IDENTITY="$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: .*\)".*/\1/p' | head -1)"
if [ -z "$IDENTITY" ]; then
  echo "ERROR: no 'Developer ID Application' certificate found in your keychain."
  echo "       Create one: Xcode ▸ Settings ▸ Accounts ▸ Manage Certificates ▸ + ▸ Developer ID Application."
  echo "       (Currently: $(security find-identity -v -p codesigning | tail -1 | sed 's/^ *//'))"
  exit 1
fi
echo "Signing identity: $IDENTITY"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
ditto -x -k "$ZIP" "$WORK"                       # unzip preserving bundle structure
APP="$WORK/RailCall Studio.app"
[ -d "$APP" ] || { echo "ERROR: 'RailCall Studio.app' not inside the zip."; exit 1; }

# 2) Sign the bundle. No nested Mach-O here, so no --deep. Hardened runtime (--options runtime) + a secure
#    timestamp are MANDATORY for notarization. Script-app signatures live in xattrs — that's why we use
#    ditto (never plain zip) everywhere below, or the signature gets stripped in transit.
codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
codesign --verify --strict --verbose=2 "$APP"
echo "✓ signed + verified"

# 3) Notarize: submit a ditto archive and --wait for Apple's verdict (you submit a zip; you staple the app).
SUBMIT="$WORK/submit.zip"
ditto -c -k --keepParent "$APP" "$SUBMIT"
echo "Submitting to Apple notary service (profile: $PROFILE) — this can take a few minutes…"
xcrun notarytool submit "$SUBMIT" --keychain-profile "$PROFILE" --wait

# 4) Staple the ticket INTO the bundle so it verifies offline, then confirm Gatekeeper would accept it.
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl -a -t exec -vv "$APP" || true               # expect: accepted, source=Notarized Developer ID
echo "✓ notarized + stapled"

# 5) Repack with ditto so the signature/ticket survive; re-attach OPEN ME FIRST.txt (plain text, no xattrs).
rm -f "$ZIP"
( cd "$WORK" && ditto -c -k --sequesterRsrc --keepParent "RailCall Studio.app" "$ZIP" )
[ -f "$WORK/OPEN ME FIRST.txt" ] && ( cd "$WORK" && zip -gq "$ZIP" "OPEN ME FIRST.txt" )
echo "✓ wrote signed + notarized $ZIP ($(ls -la "$ZIP" | awk '{print $5}') bytes)"
echo "  Verify a clean open: unzip it somewhere, double-click — you should get a normal 'Open' dialog, no block."
