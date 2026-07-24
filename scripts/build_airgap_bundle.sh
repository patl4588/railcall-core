#!/usr/bin/env bash
# Build a self-contained RailCall air-gap install bundle.
#
# The bundle contains every file `install.sh` normally downloads, plus a
# MANIFEST + verifier + README. The customer moves it to a network-isolated
# host, runs `./verify.sh` (refuses if any byte drifted from the pinned
# sha), then `./install.sh` — which prefers the local bundle over any
# network fetch and enforces the SAME sha pins on the local files.
#
# Usage (from railcall-core repo root):
#   STATION_TARBALL="/tmp/railcall_station.tar.gz" \
#   OUT="/tmp/railcall_airgap_v0.25.tar.gz" \
#   ./scripts/build_airgap_bundle.sh
#
# STATION_TARBALL defaults to /tmp/railcall_station.tar.gz (matches the
# output of build_station_tar.sh). Version tag is derived from install.sh's
# STATION_URL to keep the two artifacts in lockstep.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATION_TARBALL="${STATION_TARBALL:-/tmp/railcall_station.tar.gz}"
OUT="${OUT:-/tmp/railcall_airgap.tar.gz}"

if [[ ! -f "$STATION_TARBALL" ]]; then
    echo "ERROR: station tarball not found at $STATION_TARBALL" >&2
    echo "       build it first with: ./scripts/build_station_tar.sh" >&2
    exit 1
fi

# Extract the release tag from install.sh so the bundle name matches
# what the CLI expects (e.g. station-v0.25 → railcall_airgap_v0.25).
RELEASE_TAG=$(grep -oE 'station-v[0-9.]+' "$REPO_ROOT/install.sh" | head -1)
RELEASE_TAG="${RELEASE_TAG:-station-vDEV}"
VERSION="${RELEASE_TAG#station-}"

STAGE="$(mktemp -d)/railcall_airgap_${VERSION}"
mkdir -p "$STAGE"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT

# ---- Copy the files install.sh would fetch --------------------------------
FILES=(
    railcall_cli.py
    railcall_companion_daemon.py
    vault_io.py
    receipt_signer.py
)
GOV_FILES=(
    governance/__init__.py
    governance/policy_engine.py
    governance/policy_schema.py
    governance/receipt_v2.py
    governance/defaults/__init__.py
    governance/defaults/governance.default.yml
)
for f in "${FILES[@]}" "${GOV_FILES[@]}"; do
    if [[ ! -f "$REPO_ROOT/$f" ]]; then
        echo "ERROR: missing source file $f" >&2
        exit 1
    fi
    mkdir -p "$STAGE/$(dirname "$f")"
    cp "$REPO_ROOT/$f" "$STAGE/$f"
done

# The installer itself. Its LOCAL_DIR logic + the station_get patch prefer
# these local files over any network fetch — the whole point of the bundle.
cp "$REPO_ROOT/install.sh" "$STAGE/install.sh"

# The station tarball.
cp "$STATION_TARBALL" "$STAGE/railcall_station.tar.gz"

# ---- Manifest: sha256 of every shipped file -------------------------------
# The verifier walks this. If any file drifts even one byte, verify.sh
# refuses AND install.sh refuses (same STATION_SHA + pin_for() gate). Two
# independent checks — belt and suspenders.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
    elif command -v shasum  >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}';
    else echo ""; fi
}
{
    echo "# RailCall air-gap bundle · $VERSION · $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# sha256  path"
    (
        cd "$STAGE"
        # Walk every file (skip MANIFEST + verify since they're generated
        # after) and emit "SHA  RELATIVE_PATH" pairs sorted for stable output.
        # Bash 3 (macOS default) has no readarray; use a plain while loop.
        find . -type f ! -name MANIFEST.txt ! -name verify.sh | sort | while IFS= read -r p; do
            s=$(sha256_of "$p")
            [ -z "$s" ] && { echo "ERROR: no sha256 tool available" >&2; exit 1; }
            printf "%s  %s\n" "$s" "$p"
        done
    )
} > "$STAGE/MANIFEST.txt"

# ---- verify.sh: refuses on any drift --------------------------------------
cat > "$STAGE/verify.sh" <<'VERIFY'
#!/usr/bin/env bash
# Walks MANIFEST.txt and refuses if any bundled file's sha256 has drifted.
# Run this BEFORE install.sh — a clean verify says the bundle is exactly
# what was published; install.sh's own pin gates catch anything verify.sh
# missed (defense in depth).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if command -v sha256sum >/dev/null 2>&1; then hasher="sha256sum";
elif command -v shasum >/dev/null 2>&1; then hasher="shasum -a 256";
else
    echo "ERROR: no sha256sum or shasum tool available." >&2
    exit 2
fi

fails=0
count=0
while IFS= read -r line; do
    case "$line" in ""|"#"*) continue;; esac
    want="${line%% *}"
    path="${line#*  }"
    if [[ ! -f "$path" ]]; then
        echo "  ✗ MISSING  $path"
        fails=$((fails + 1))
        continue
    fi
    got=$($hasher "$path" | awk '{print $1}')
    if [[ "$got" != "$want" ]]; then
        echo "  ✗ MISMATCH $path"
        echo "      wanted $want"
        echo "      got    $got"
        fails=$((fails + 1))
    else
        count=$((count + 1))
    fi
done < MANIFEST.txt

if [[ "$fails" -gt 0 ]]; then
    echo ""
    echo "REFUSED: $fails file(s) failed verification." >&2
    echo "         Do NOT run install.sh — this bundle has been altered." >&2
    exit 1
fi
echo ""
echo "  ✓ verified $count file(s) against MANIFEST.txt"
echo "  ✓ bundle integrity intact — safe to run ./install.sh"
VERIFY
chmod +x "$STAGE/verify.sh"

# ---- README ----------------------------------------------------------------
cat > "$STAGE/README.md" <<README
# RailCall air-gap install bundle · ${VERSION}

Self-contained offline installer for RailCall. Contains every byte
\`install.sh\` normally downloads over the network, pre-verified against
its sha256 pin. Move this whole directory (or the tarball you got it in)
onto a network-isolated host and install without any outbound
connectivity.

## Contents

| Path | What it is |
|-|-|
| \`install.sh\` | The stock RailCall installer. Its local-first logic uses everything in this dir before touching the network. |
| \`railcall_cli.py\` + \`railcall_companion_daemon.py\` + \`vault_io.py\` + \`receipt_signer.py\` | The CLI + supporting Python files, all sha256-pinned inside install.sh. |
| \`governance/\` | The pinned policy engine + defaults. |
| \`railcall_station.tar.gz\` | The Studio + workbench bundle (~5MB). Same file the online install downloads from GitHub, same sha. |
| \`MANIFEST.txt\` | sha256 of every file in this bundle. |
| \`verify.sh\` | Refuses if any file drifted from the manifest. |

## Install steps

\`\`\`bash
# 1. Verify the bundle. Refuses on any byte-level drift.
./verify.sh

# 2. Run the installer. It will detect the local files + prefer them over
#    any network fetch. Same sha pin gates apply on the local copies —
#    the bundle can't smuggle in a different CLI or station than what
#    install.sh was minted for.
./install.sh
\`\`\`

That's it. No outbound network needed. The install script writes to
\`~/.railcall/\` (or wherever \`RC_HOME\` points), sets up the launcher
in \`~/.railcall/bin/railcall\`, unpacks the station bundle to
\`~/.railcall/station/\`, and refuses if any pinned file's sha is off.

## What it does NOT do

- **No modules pre-installed.** Modules (HubSpot, Salesforce, etc.) are
  published on the marketplace and installed on demand. For an air-gap
  environment, you'll need to acquire specific module bundles separately
  and drop them into \`~/.railcall/station/modules/<slug>/\`. The
  publisher trust allowlist + Ed25519 signature verification apply
  identically to those modules — no runtime does.
- **No online license activation.** For paid-module DRM, the license
  file must be obtained separately (email attachment, USB) and
  installed with \`railcall license activate <path>\`. Verification is
  fully offline; the license just has to reach the target machine
  somehow.
- **No calling home.** Once installed the station operates entirely on
  127.0.0.1 by default. LLM inference through Studio + any external
  API call from a workflow use YOUR credentials + your outbound
  network only.

## Verification chain

1. \`verify.sh\` hashes every bundled file against \`MANIFEST.txt\`.
2. \`install.sh\`'s \`pin_for()\` function has its own sha256 pin per
   CLI file, hardcoded at build time. It refuses if the local copy
   doesn't match — same as it does for network downloads.
3. The station tarball is pinned by \`STATION_SHA\` in \`install.sh\`.
4. Each module bundle a customer installs later carries a publisher
   Ed25519 signature, verified by the module loader at load time.

Four independent checks. All are offline. Nothing trusts the network.

## Getting help

If any step fails: capture the exact output + email sales@railcall.ai
with the file that failed verification.
README

# ---- Package + report -----------------------------------------------------
OUT_DIR=$(dirname "$OUT")
mkdir -p "$OUT_DIR"
tar -C "$(dirname "$STAGE")" -czf "$OUT" "$(basename "$STAGE")"
BUNDLE_SIZE=$(du -h "$OUT" | cut -f1)
BUNDLE_SHA=$(sha256_of "$OUT")

cat <<REPORT
✓ air-gap bundle built
  version: $VERSION
  path:    $OUT
  size:    $BUNDLE_SIZE
  sha256:  $BUNDLE_SHA

next steps:
  gh release upload $RELEASE_TAG "$OUT" --repo patl4588/railcall-core
  # then point customers at:
  #   https://github.com/patl4588/railcall-core/releases/download/$RELEASE_TAG/$(basename "$OUT")
REPORT
