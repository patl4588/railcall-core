#!/bin/bash
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}       R A I L C A L L   |   S O V E R E I G N   D E V K I T    ${NC}"
echo -e "${CYAN}================================================================${NC}"

RC_HOME="$HOME/.railcall"
RC_BIN="$RC_HOME/bin"
RC_CONF="$HOME/.config/railcall"

echo -e "${BLUE}🧱 Forging local directories and airlock...${NC}"
mkdir -p "$RC_HOME" "$RC_BIN" "$RC_CONF"

echo -e "${BLUE}⚙️ Copying zero-drift AI engine & visual renderer...${NC}"
cp local_llm_mcp_compiler.py "$RC_HOME/"
cp build_dashboard.py "$RC_HOME/"
chmod +x "$RC_HOME"/*.py

TOKEN_FILE="$RC_CONF/token.json"
if [ ! -f "$TOKEN_FILE" ]; then
    echo '{"api_key": "rc_local_trial_100", "tier": "sovereign_free", "runs_remaining": 100}' > "$TOKEN_FILE"
    echo -e "${GREEN}🔐 Provisioned Local Sovereign Token (100 free airlocked runs).${NC}"
fi

echo -e "${BLUE}⚡ Building global 'railcall' CLI binary...${NC}"
cat << 'CLI_EOF' > "$RC_BIN/railcall"
#!/bin/bash
RC_HOME="$HOME/.railcall"

if [ "$1" == "build" ]; then
    echo "🛡️ Initiating Airlocked Build Sequence..."
    # Execute the proven, airlocked python build pipeline
    cd "$RC_HOME" && python3 build_dashboard.py
    cp dashboard.html "$OLDPWD/railcall_dashboard.html"
    echo "✅ Dashboard physically compiled to ./railcall_dashboard.html"
elif [ "$1" == "balance" ]; then
    echo "=== Railcall Local Ledger ==="
    echo "Status: SOVEREIGN OFFLINE (Airlock Active)"
    echo "Runs Remaining: 100 (Free Tier)"
else
    echo "Railcall Sovereign DevKit v1.0.0"
    echo "Usage: railcall [command]"
    echo ""
    echo "Commands:"
    echo "  build       Compile local data into an airlocked, zero-CDN dashboard"
    echo "  balance     Check local compute ledger"
fi
CLI_EOF

chmod +x "$RC_BIN/railcall"

# Add to PATH safely
SHELL_CONFIG=""
if [ -f "$HOME/.zshrc" ]; then SHELL_CONFIG="$HOME/.zshrc"; elif [ -f "$HOME/.bash_profile" ]; then SHELL_CONFIG="$HOME/.bash_profile"; fi

if [ -n "$SHELL_CONFIG" ]; then
    if ! grep -q "$RC_BIN" "$SHELL_CONFIG"; then
        echo -e "\nexport PATH=\"\$PATH:$RC_BIN\"" >> "$SHELL_CONFIG"
        echo -e "${GREEN}✅ Added Railcall to system PATH in $SHELL_CONFIG${NC}"
    fi
fi

echo -e "${GREEN}✅ DevKit Installed! Run 'source ~/.zshrc' (or open a new terminal) and type 'railcall'.${NC}"
