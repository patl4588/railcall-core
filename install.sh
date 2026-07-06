#!/bin/bash
# Railcall network installer.  Usage:
#   curl -fsSL https://raw.githubusercontent.com/patl4588/railcall-core/main/install.sh | bash
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}                 R A I L C A L L   I N S T A L L E R            ${NC}"
echo -e "${CYAN}================================================================${NC}"

RAW_BASE="https://raw.githubusercontent.com/patl4588/railcall-core/main"
RC_HOME="$HOME/.railcall"
RC_BIN="$RC_HOME/bin"
RC_CONF="$HOME/.config/railcall"
FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"

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

echo -e "${BLUE}Downloading CLI from ${RAW_BASE} ...${NC}"
for f in $FILES; do
    if ! fetch "$RAW_BASE/$f" "$RC_HOME/$f"; then
        echo -e "${RED}✗ Failed to download $f${NC}"; exit 1
    fi
    # Validate: non-empty AND valid Python (a 404 body / HTML won't compile).
    if [ ! -s "$RC_HOME/$f" ] || ! python3 -m py_compile "$RC_HOME/$f" 2>/dev/null; then
        echo -e "${RED}✗ $f downloaded but is invalid (empty or not Python — bad URL?).${NC}"
        rm -f "$RC_HOME/$f"; exit 1
    fi
    echo -e "${GREEN}  ✓ $f${NC}"
done
chmod +x "$RC_HOME/railcall_cli.py"

# Ed25519 receipt signing needs `cryptography`. Best-effort + NON-FATAL: without it the daemon still
# writes airlock-verified, SHA-256 receipts — just honestly UNSIGNED. With it, every receipt is signed.
if python3 -c "import cryptography" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ receipt signing available (Ed25519)${NC}"
elif python3 -m pip install --quiet --disable-pip-version-check cryptography >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ receipt signing enabled (installed cryptography)${NC}"
else
    echo -e "${BLUE}  · receipts are airlock-verified; run 'python3 -m pip install cryptography' to also Ed25519-sign them${NC}"
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

# Free-tier token. REAL enforcement state: the CLI reads token["runs_remaining"],
# decrements it per build, and hard-blocks at 0. Re-running never resets an existing token.
TOKEN_FILE="$RC_CONF/token.json"
chmod 700 "$RC_CONF" 2>/dev/null || true
if [ ! -f "$TOKEN_FILE" ]; then
    echo '{"api_key": "rc_local_trial_100", "tier": "free", "runs_remaining": 100}' > "$TOKEN_FILE"
    echo -e "${GREEN}Provisioned 100 free flows (enforced by the CLI, not hardcoded).${NC}"
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

echo -e "${GREEN}✅ Installed. Open a new terminal (or 'source ${SHELL_CONFIG:-your shell rc}'), then run:${NC}"
echo -e "${CYAN}   railcall studio${NC}  — open the visual Studio in your browser (127.0.0.1:8799)"
echo -e "${CYAN}   railcall${NC}         — the terminal dashboard (key, flows, commands)"
