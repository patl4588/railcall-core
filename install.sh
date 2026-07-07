#!/bin/bash
# Railcall network installer.  Usage:
#   curl -fsSL https://raw.githubusercontent.com/patl4588/railcall-core/main/install.sh | bash
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}                 R A I L C A L L   I N S T A L L E R            ${NC}"
echo -e "${CYAN}================================================================${NC}"

# Primary source + a global-CDN fallback. raw.githubusercontent.com is blocked/throttled by some
# regional ISPs (a transparent proxy can even hand back a fake "200 OK" whose body is a 404 page);
# jsDelivr mirrors the SAME repo and stays reachable in most of those regions. We try raw, then the CDN.
RAW_BASE="https://raw.githubusercontent.com/patl4588/railcall-core/main"
CDN_BASE="https://cdn.jsdelivr.net/gh/patl4588/railcall-core@main"
RC_HOME="$HOME/.railcall"
RC_BIN="$RC_HOME/bin"
RC_CONF="$HOME/.config/railcall"
FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"

# Full disclosure BEFORE the first write — everything this installer touches, up front:
echo -e "${BLUE}This installer writes to:${NC}"
echo -e "${BLUE}  · $RC_HOME — the CLI, the 'railcall' launcher, and the Studio bundle (~22MB download)${NC}"
echo -e "${BLUE}  · $RC_CONF — your pre-login local trial token (token.json, owner-only chmod 600)${NC}"
echo -e "${BLUE}  · $HOME/Desktop — a double-click 'RailCall Studio.command' launcher (only if a Desktop folder exists)${NC}"
echo -e "${BLUE}  · your shell rc (.zshrc / .bashrc / .bash_profile) — one PATH line, only if one of those files exists${NC}"
echo -e "${BLUE}  · Python user packages — the 'cryptography' package via pip --user, announced below, only if missing${NC}"

mkdir -p "$RC_HOME" "$RC_BIN" "$RC_CONF"

# Pick a downloader (-f makes curl FAIL on a 404 instead of saving the error page).
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -q -O "$2" "$1"; }
else
    echo -e "${RED}Need curl or wget to install.${NC}"; exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}python3 is required and was not found on PATH.${NC}"; exit 1
fi

# If this installer is being run from a repo checkout (git clone / unzipped ZIP), the source files sit
# right next to it — use those first so a fully offline / region-blocked install just works.
SELF="${BASH_SOURCE[0]:-$0}"; LOCAL_DIR=""
case "$SELF" in */*) LOCAL_DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)";; esac

# Get + validate one file: try the local checkout, then raw GitHub, then the jsDelivr CDN. A file only
# counts if it is non-empty AND compiles as Python — so a proxy's fake "404: Not Found" body is rejected
# and we fall through to the next source.
fetch_valid() {
    f="$1"; dest="$RC_HOME/$f"
    if [ -n "$LOCAL_DIR" ] && [ -s "$LOCAL_DIR/$f" ] && python3 -m py_compile "$LOCAL_DIR/$f" 2>/dev/null; then
        cp "$LOCAL_DIR/$f" "$dest"; echo -e "${GREEN}  ✓ $f${BLUE} (local checkout)${NC}"; return 0
    fi
    for base in "$RAW_BASE" "$CDN_BASE"; do
        if fetch "$base/$f" "$dest" 2>/dev/null && [ -s "$dest" ] && python3 -m py_compile "$dest" 2>/dev/null; then
            case "$base" in *jsdelivr*) echo -e "${GREEN}  ✓ $f${BLUE} (via CDN mirror)${NC}";; *) echo -e "${GREEN}  ✓ $f${NC}";; esac
            return 0
        fi
        rm -f "$dest"
    done
    return 1
}

echo -e "${BLUE}Downloading CLI (raw.githubusercontent.com, CDN fallback) ...${NC}"
for f in $FILES; do
    if ! fetch_valid "$f"; then
        echo -e "${RED}✗ Could not fetch a valid $f from GitHub or the CDN mirror.${NC}"
        echo -e "${RED}  This is almost always a regional network block on raw.githubusercontent.com${NC}"
        echo -e "${RED}  (some ISPs return a fake page). Two ways around it:${NC}"
        echo -e "${BLUE}  1) Fix DNS (WSL/Linux):  echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf${NC}"
        echo -e "${BLUE}  2) Install from a clone: git clone https://github.com/patl4588/railcall-core${NC}"
        echo -e "${BLUE}                           cd railcall-core && bash install.sh${NC}"
        exit 1
    fi
done
chmod +x "$RC_HOME/railcall_cli.py"

# Ed25519 receipt signing needs `cryptography`. Best-effort + NON-FATAL: without it the daemon still
# writes airlock-verified, SHA-256 receipts — just honestly UNSIGNED. With it, every receipt is signed.
# We VERIFY the import after each attempt (pip's exit code alone is not proof it's importable), and on
# an "externally-managed-environment" Python (PEP 668 — Homebrew python, Debian/Ubuntu system python)
# a plain `pip install --user` is refused, so we retry with --break-system-packages (the supported
# escape hatch for a user-site install). If signing still can't be enabled we say so LOUDLY rather than
# leaving the user to discover unsigned receipts later.
crypto_ok() { python3 -c "import cryptography" >/dev/null 2>&1; }
if crypto_ok; then
    echo -e "${GREEN}  ✓ receipt signing available (Ed25519)${NC}"
else
    echo -e "${BLUE}  · installing the Python 'cryptography' package so receipts can be Ed25519-signed ...${NC}"
    PIP_USER="python3 -m pip install --user --quiet --disable-pip-version-check"
    $PIP_USER cryptography >/dev/null 2>&1 || true
    if ! crypto_ok; then
        # PEP 668 externally-managed-environment (Homebrew / Debian system python): retry with the escape hatch.
        $PIP_USER --break-system-packages cryptography >/dev/null 2>&1 || true
    fi
    if crypto_ok; then
        echo -e "${GREEN}  ✓ receipt signing enabled (installed cryptography)${NC}"
    else
        echo -e "${RED}  ! receipt signing is NOT enabled — receipts will be written UNSIGNED (airlock-verified, SHA-256 only).${NC}"
        echo -e "${RED}    'cryptography' could not be installed automatically (usually PEP 668 on a Homebrew/system Python).${NC}"
        echo -e "${BLUE}    Turn on signing with ONE of these, then re-run this installer:${NC}"
        echo -e "${CYAN}      python3 -m pip install --user --break-system-packages cryptography${NC}"
        echo -e "${CYAN}      pipx install cryptography${NC}    ${BLUE}# if you use pipx${NC}"
        echo -e "${BLUE}    (verify with:  python3 -c \"import cryptography\"  — no output means it's ready)${NC}"
    fi
fi

# ---- Studio (the visual builder) — fetch + unpack the station bundle (one-time, ~22MB) ----
STATION_URL="https://github.com/patl4588/railcall-core/releases/download/station-v0.1/railcall_station.tar.gz"
STATION_DIR="$RC_HOME/station"
echo -e "${BLUE}Downloading the RailCall Studio (one-time, ~22MB) ...${NC}"
if fetch "$STATION_URL" "$RC_HOME/station.tar.gz"; then
    mkdir -p "$STATION_DIR"
    if tar -xzf "$RC_HOME/station.tar.gz" -C "$STATION_DIR" 2>/dev/null && [ -f "$STATION_DIR/workbench/studio_server.py" ]; then
        rm -f "$RC_HOME/station.tar.gz"
        echo -e "${GREEN}  ✓ Studio installed — run 'railcall studio' to open it in your browser.${NC}"
    else
        rm -f "$RC_HOME/station.tar.gz"
        echo -e "${RED}  ✗ Studio archive downloaded but failed to unpack (CLI still works; re-run the installer for the Studio).${NC}"
    fi
else
    echo -e "${RED}  ✗ Could not download the Studio bundle (CLI still works; re-run the installer to retry the Studio).${NC}"
fi

# Pre-login LOCAL trial token. REAL enforcement state: the CLI reads token["runs_remaining"],
# decrements it per build, and hard-blocks at 0. Re-running never resets an existing token.
# The rc_local_ prefix is a LOCAL sentinel the engine allowlists — it must NEVER touch the gateway.
TOKEN_FILE="$RC_CONF/token.json"
chmod 700 "$RC_CONF" 2>/dev/null || true
if [ ! -f "$TOKEN_FILE" ]; then
    echo '{"api_key": "rc_local_trial_100", "tier": "free", "runs_remaining": 100}' > "$TOKEN_FILE"
    echo -e "${GREEN}Provisioned a pre-login LOCAL trial of 100 flows — enforced by the CLI on this machine only, never a hosted balance.${NC}"
    echo -e "${GREEN}It is replaced by your account balance the moment you run 'railcall login <key>' (free accounts include 100 flows).${NC}"
else
    echo -e "${GREEN}Existing token kept (not reset).${NC}"
fi
chmod 600 "$TOKEN_FILE" 2>/dev/null || true   # BYOK token file must be owner-only

# Thin wrapper: forward EVERY command + arg straight to the real CLI. No fake telemetry.
cat > "$RC_BIN/railcall" << 'WRAP'
#!/bin/bash
exec python3 "$HOME/.railcall/railcall_cli.py" "$@"
WRAP
chmod +x "$RC_BIN/railcall"

# Double-click launcher (macOS): a clickable "RailCall Studio" on the Desktop that opens the Studio.
if [ -d "$HOME/Desktop" ]; then
    LAUNCHER="$HOME/Desktop/RailCall Studio.command"
    printf '#!/bin/bash\nexec "%s" studio\n' "$RC_BIN/railcall" > "$LAUNCHER"
    chmod +x "$LAUNCHER"
    echo -e "${GREEN}  ✓ Double-click 'RailCall Studio' on your Desktop to open the Studio anytime.${NC}"
fi

# Add the bin dir to PATH (once), picking the user's shell rc.
SHELL_CONFIG=""
if [ -f "$HOME/.zshrc" ]; then SHELL_CONFIG="$HOME/.zshrc";
elif [ -f "$HOME/.bashrc" ]; then SHELL_CONFIG="$HOME/.bashrc";
elif [ -f "$HOME/.bash_profile" ]; then SHELL_CONFIG="$HOME/.bash_profile"; fi
if [ -n "$SHELL_CONFIG" ] && ! grep -q "$RC_BIN" "$SHELL_CONFIG" 2>/dev/null; then
    echo "export PATH=\"\$PATH:$RC_BIN\"" >> "$SHELL_CONFIG"
    echo -e "${GREEN}Added $RC_BIN to PATH in $SHELL_CONFIG${NC}"
fi

echo -e "${GREEN}✅ Installed.${NC}  LOCAL · BYOK · DRY-RUN · NO SENDS — everything runs on 127.0.0.1, nothing fires without your approval."
echo -e "${CYAN}================================================================${NC}"
if [ -n "$SHELL_CONFIG" ]; then
    echo -e "${CYAN}  IMPORTANT — one step so the ${NC}${GREEN}railcall${NC}${CYAN} command is found in THIS shell:${NC}"
    echo -e "${CYAN}     open a NEW terminal, ${NC}${CYAN}or run:${NC}  ${GREEN}source $SHELL_CONFIG${NC}"
    echo -e "${BLUE}     (skip this and you'll get \"railcall: command not found\" until you reopen the terminal)${NC}"
else
    echo -e "${CYAN}  IMPORTANT — no shell rc file was found, so PATH was NOT changed.${NC}"
    echo -e "${CYAN}  Paste this into your terminal now (and into your shell startup file to keep it):${NC}"
    echo -e "${GREEN}     export PATH=\"\$PATH:$RC_BIN\"${NC}"
fi
echo -e "${CYAN}================================================================${NC}"
echo -e "${GREEN}Then run:${NC}"
echo -e "${CYAN}   railcall studio${NC}  — open the visual Studio in your browser (127.0.0.1:8799)"
echo -e "${CYAN}   railcall${NC}         — the terminal dashboard (key, flows, commands)"
