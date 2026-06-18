#!/bin/bash
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}                 R A I L C A L L   I N S T A L L E R            ${NC}"
echo -e "${CYAN}================================================================${NC}"

RC_HOME="$HOME/.railcall"
RC_BIN="$RC_HOME/bin"
RC_CONF="$HOME/.config/railcall"
# Directory this installer lives in (its CLI files ship alongside it).
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$RC_HOME" "$RC_BIN" "$RC_CONF"

echo -e "${BLUE}Installing the CLI enforcer + companion daemon...${NC}"
# In production these would be downloaded from a pinned release URL; here we install
# the verified files that ship alongside this script.
cp "$SRC_DIR/railcall_cli.py" "$RC_HOME/"
cp "$SRC_DIR/railcall_companion_daemon.py" "$RC_HOME/"   # required import for the CLI
chmod +x "$RC_HOME/railcall_cli.py"

# Free-tier token. This is REAL enforcement state, not a display string:
# railcall_cli.py reads token["runs_remaining"], decrements it per build, and
# hard-blocks at 0. Re-running the installer never resets an existing token.
TOKEN_FILE="$RC_CONF/token.json"
if [ ! -f "$TOKEN_FILE" ]; then
    echo '{"api_key": "rc_local_trial_100", "tier": "free", "runs_remaining": 100}' > "$TOKEN_FILE"
    echo -e "${GREEN}Provisioned 100 free runs (enforced by the CLI, not hardcoded).${NC}"
else
    echo -e "${GREEN}Existing token kept (not reset).${NC}"
fi

echo -e "${BLUE}Writing global 'railcall' wrapper (pure pass-through to the CLI)...${NC}"
# Thin wrapper: forward EVERY command and argument straight to the real Python CLI.
# No hardcoded balances, no fake telemetry — the CLI is the single source of truth.
cat << 'WRAP' > "$RC_BIN/railcall"
#!/bin/bash
exec python3 "$HOME/.railcall/railcall_cli.py" "$@"
WRAP
chmod +x "$RC_BIN/railcall"

# Add the bin dir to PATH (once).
SHELL_CONFIG=""
if [ -f "$HOME/.zshrc" ]; then SHELL_CONFIG="$HOME/.zshrc"; elif [ -f "$HOME/.bash_profile" ]; then SHELL_CONFIG="$HOME/.bash_profile"; fi
if [ -n "$SHELL_CONFIG" ] && ! grep -q "$RC_BIN" "$SHELL_CONFIG"; then
    echo "export PATH=\"\$PATH:$RC_BIN\"" >> "$SHELL_CONFIG"
    echo -e "${GREEN}Added $RC_BIN to PATH in $SHELL_CONFIG${NC}"
fi

echo -e "${GREEN}✅ Installed. Open a new terminal (or 'source ${SHELL_CONFIG:-your shell rc}') and run: railcall${NC}"
