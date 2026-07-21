#!/bin/bash
# Railcall network installer.  Usage:
#   curl -fsSL https://raw.githubusercontent.com/patl4588/railcall-core/main/install.sh | bash
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}                 R A I L C A L L   I N S T A L L E R            ${NC}"
echo -e "${CYAN}================================================================${NC}"

# SOURCES. Every byte from every source is verified against the sha256 pinned below, so a
# mirror can never inject anything — that is the entire point of pinning, and it is why
# adding one is safe. We ship TWO because raw.githubusercontent.com is blocked or
# transparently proxied on some networks (corporate MITM, national filtering, hotel/ISP
# captive portals): those return a *different body* that fails the pin, which is the gate
# working correctly, not a bad pin. railcall.ai is our own origin and serves byte-identical
# copies, so it is a fallback we control rather than a third-party CDN.
RAW_BASE="https://raw.githubusercontent.com/patl4588/railcall-core/main"
MIRROR_BASE="https://railcall.ai/cli"
RC_HOME="$HOME/.railcall"
RC_BIN="$RC_HOME/bin"
RC_CONF="$HOME/.config/railcall"
FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"
GOVERNANCE_FILES="governance/__init__.py governance/policy_engine.py governance/policy_schema.py governance/receipt_v2.py governance/defaults/__init__.py governance/defaults/governance.default.yml"
STATION_SHA="d33df65f0e8a53e87e0d4eb304d19d18f150ec3148e3d1ed4424acb122217c31"

# Full disclosure BEFORE the first write — everything this installer touches, up front:
echo -e "${BLUE}This installer writes to:${NC}"
echo -e "${BLUE}  · $RC_HOME — the CLI, the 'railcall' launcher, and the Studio bundle (~5MB download)${NC}"
echo -e "${BLUE}  · $RC_CONF — your pre-login local trial token (token.json, owner-only chmod 600)${NC}"
echo -e "${BLUE}  · $HOME/Desktop — a double-click 'RailCall Studio.command' launcher (only if a Desktop folder exists)${NC}"
echo -e "${BLUE}  · your shell rc (.zshrc / .bashrc / .bash_profile) — one PATH line, only if one of those files exists${NC}"
echo -e "${BLUE}  · Python user packages — the 'cryptography' package via pip --user, announced below, only if missing${NC}"

mkdir -p "$RC_HOME" "$RC_BIN" "$RC_CONF"
mkdir -p "$HOME/.railcall/transaction_runs"
mkdir -p "$HOME/.railcall/library/promotions"
mkdir -p "$HOME/.railcall/library/promotions"
cp -f library/promotions/governed_legos_registry.json "$HOME/.railcall/library/promotions/" 2>/dev/null || echo '{"governed_legos": [], "version": "1.0", "note": "Add promoted workflow legos here"}' > "$HOME/.railcall/library/promotions/governed_legos_registry.json"

# Pick a downloader (-f makes curl FAIL on a 404 instead of saving the error page).
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -q -O "$2" "$1"; }
else
    echo -e "${RED}Need curl or wget to install.${NC}"; exit 1
fi

# Resolve ONE Python 3 interpreter, used consistently below (py_compile validation, cryptography,
# the launcher). Windows Git-Bash often ships only 'python' — accept it if it is Python 3.
PY=""
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1 && python -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" >/dev/null 2>&1; then
    PY=python
fi
if [ -z "$PY" ]; then
    echo -e "${RED}Python 3 is required and was not found on PATH (looked for 'python3', then 'python').${NC}"; exit 1
fi

# If this installer is being run from a repo checkout (git clone / unzipped ZIP), the source files sit
# right next to it — use those first so a fully offline / region-blocked install just works.
# dirname of a bare 'install.sh' is '.' → the invoker's cwd; that is safe even for piped installs
# (curl|bash) because fetch_valid only trusts a local file that exists non-empty AND py_compiles.
SELF="${BASH_SOURCE[0]:-$0}"
LOCAL_DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)" || LOCAL_DIR=""

# ---- Supply-chain integrity pins ------------------------------------------------------------------
# Every core file is verified against a sha256 that is PINNED into this installer. This stops a
# compromised 'main' (or a MITM proxy that swaps the body) from injecting code that merely happens to
# compile — a file whose bytes do not match its pin is REFUSED and never installed, even if py_compile
# passes. The hash gate is ADDITIONAL to the existing non-empty + py_compile checks, not a replacement.
#
# Regenerate these pins after an INTENTIONAL change to the core files, from a repo checkout, with:
#   for f in railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py; do \
#     printf '        %-30s echo %s ;;\n' "$f)" "$(shasum -a 256 "$f" | awk '{print $1}')"; done
#   # (on Linux use `sha256sum "$f"` instead of `shasum -a 256 "$f"`)
# then paste the printed lines over the case arms in pin_for() below.
pin_for() {
    case "$1" in
        railcall_cli.py)                          echo 45f2e8a6ea4910ecf2a878098d60905f8b1071f2e9ac9f328a7f40320fb5a3bc ;;
        railcall_companion_daemon.py)             echo 6a40af4c5bfdf34b706496eea2889488d563acb35d5c9b7484dd2ae8a7c80805 ;;
        vault_io.py)                              echo 17b0e644a93c773d3f7b5e5e8b046ea39472364b532b545846f3c617433792f8 ;;
        receipt_signer.py)                        echo 36b84579880db9bf78c9bc21cd40c6976094ae8ea978c939f2feef4f97041b9e ;;
        governance/__init__.py)                   echo a039118f68adec79c887c26f3a7218b0096da47bb18c7efb13e52f06af94cedd ;;
        governance/policy_engine.py)              echo 6518840af666c2bcffe53b8bc73c19d7ad3c933fdede5bdc6c7dfe9dfdc831fb ;;
        governance/policy_schema.py)              echo 943b777cef4c8a776490a0e5950885180f8d2e815bdeee4c7866c4022ee9410a ;;
        governance/receipt_v2.py)                 echo fad0581fe6e6780608c78fec9a124eb1a833159067107f4ff313c6ba459971c6 ;;
        governance/defaults/__init__.py)          echo 5d16591a5456de8b492aa701a1f7b989040995513fc813600d0d445b24131e34 ;;
        governance/defaults/governance.default.yml) echo ff56072e81ed4908ea91f567741238b387e536cd1f5974513ee18df0d5c575b9 ;;
        *) echo "" ;;
    esac
}

# Portable sha256 of a file → stdout. Linux ships sha256sum; macOS/BSD ship shasum. Empty if neither.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
    elif command -v shasum  >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}';
    else echo ""; fi
}

# Verify a file on disk against its pin. Non-zero (with a LOUD security refusal) on any mismatch,
# an unpinned filename, or when no sha256 tool exists — we would rather refuse than install unverified
# code. A pass here means the bytes are exactly what we published.
pin_ok() {
    f="$1"; path="$2"; want="$(pin_for "$f")"
    if [ -z "$want" ]; then
        echo -e "${RED}  ✗ SECURITY: $f has no integrity pin in this installer — refusing to install unpinned code.${NC}"; return 1
    fi
    got="$(sha256_of "$path")"
    if [ -z "$got" ]; then
        echo -e "${RED}  ✗ SECURITY: cannot hash $f — no sha256sum/shasum tool found. Refusing to install unverified code.${NC}"; return 1
    fi
    if [ "$got" != "$want" ]; then
        # QUIET per source. Trying the next source is the normal recovery path, so a
        # SUCCESSFUL install would otherwise print a red SECURITY block followed by a
        # green tick — which reads as a breach and led a user to conclude the pins were
        # stale. The loud message belongs in the caller, once, only if EVERY source fails.
        LAST_PIN_FAIL="$f expected $want got $got"
        return 1
    fi
    return 0
}

# Get + validate one file: try the local checkout, then raw GitHub only (CDN removed).
# A file only counts if it is non-empty AND compiles as Python AND matches its pinned sha256 —
# so a proxy's fake "404: Not Found" body is rejected (fails compile) and any tampered-but-compiling
# body is refused by the pin. No fallback sources.
fetch_valid() {
    f="$1"; dest="$RC_HOME/$f"; LAST_PIN_FAIL=""
    if [ -n "$LOCAL_DIR" ] && [ -s "$LOCAL_DIR/$f" ] && "$PY" -m py_compile "$LOCAL_DIR/$f" 2>/dev/null; then
        if pin_ok "$f" "$LOCAL_DIR/$f"; then
            cp "$LOCAL_DIR/$f" "$dest"; echo -e "${GREEN}  ✓ $f${BLUE} (local checkout)${NC}"; return 0
        fi
    fi
    for base in "$RAW_BASE" "$MIRROR_BASE"; do
        if fetch "$base/$f" "$dest" 2>/dev/null && [ -s "$dest" ] && "$PY" -m py_compile "$dest" 2>/dev/null && pin_ok "$f" "$dest"; then
            if [ "$base" = "$MIRROR_BASE" ]; then
                echo -e "${GREEN}  ✓ $f${BLUE} (via railcall.ai — your network altered the GitHub copy)${NC}"
            else
                echo -e "${GREEN}  ✓ $f${NC}"
            fi
            return 0
        fi
        rm -f "$dest"
    done
    return 1
}

echo -e "${BLUE}Downloading CLI (pinned + sha256-verified; falls back to railcall.ai) ...${NC}"
for f in $FILES; do
    if ! fetch_valid "$f"; then
        echo -e "${RED}✗ Could not fetch a valid $f from GitHub (raw).${NC}"
        echo -e "${RED}  (If a SECURITY integrity-pin refusal printed above, STOP — do not work around it; the${NC}"
        echo -e "${RED}   published bytes did not match this installer's pin. Otherwise this is almost always a${NC}"
        echo -e "${RED}   regional network block on raw.githubusercontent.com${NC}"
        echo -e "${RED}  (some ISPs return a fake page). Two ways around it:${NC}"
        echo -e "${BLUE}  1) Fix DNS (WSL/Linux):  echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf${NC}"
        echo -e "${BLUE}  2) Install from a clone: git clone https://github.com/patl4588/railcall-core${NC}"
        echo -e "${BLUE}                           cd railcall-core && bash install.sh${NC}"
        exit 1
    fi
done
chmod +x "$RC_HOME/railcall_cli.py"

# Phase 1: governance package — install alongside the CLI files so the policy engine is available.
echo -e "${BLUE}Installing governance policy engine (Phase 1) ...${NC}"
mkdir -p "$RC_HOME/governance/defaults"
for f in $GOVERNANCE_FILES; do
    dest="$RC_HOME/$f"; LAST_PIN_FAIL=""
    if [ -n "$LOCAL_DIR" ] && [ -s "$LOCAL_DIR/$f" ] && pin_ok "$f" "$LOCAL_DIR/$f"; then
        cp "$LOCAL_DIR/$f" "$dest"; echo -e "${GREEN}  ✓ $f${BLUE} (local checkout)${NC}"; continue
    fi
    _got=""
    for base in "$RAW_BASE" "$MIRROR_BASE"; do
        if fetch "$base/$f" "$dest" 2>/dev/null && [ -s "$dest" ] && pin_ok "$f" "$dest"; then
            if [ "$base" = "$MIRROR_BASE" ]; then
                echo -e "${GREEN}  ✓ $f${BLUE} (via railcall.ai)${NC}"
            else
                echo -e "${GREEN}  ✓ $f${NC}"
            fi
            _got=1; break
        fi
        rm -f "$dest"
    done
    [ -n "$_got" ] && continue
    [ -n "$LAST_PIN_FAIL" ] && echo -e "${RED}  ✗ $f — every source returned bytes not matching our published hash (${LAST_PIN_FAIL}). Your network is probably modifying downloads; the check is working. Do NOT edit the pins.${NC}"
    echo -e "${RED}✗ Could not fetch a valid $f — governance policy engine will not be available.${NC}"
    echo -e "${RED}  Receipts will still be written but policy gating is disabled on this install.${NC}"
done

# Ed25519 receipt signing needs `cryptography`. Best-effort + NON-FATAL: without it the daemon still
# writes airlock-verified, SHA-256 receipts — just honestly UNSIGNED. With it, every receipt is signed.
# We VERIFY the import after each attempt (pip's exit code alone is not proof it's importable), and on
# an "externally-managed-environment" Python (PEP 668 — Homebrew python, Debian/Ubuntu system python)
# a plain `pip install --user` is refused, so we retry with --break-system-packages (the supported
# escape hatch for a user-site install). If signing still can't be enabled we say so LOUDLY rather than
# leaving the user to discover unsigned receipts later.
crypto_ok() { "$PY" -c "import cryptography" >/dev/null 2>&1; }
if crypto_ok; then
    echo -e "${GREEN}  ✓ receipt signing available (Ed25519)${NC}"
else
    echo -e "${BLUE}  · installing the Python 'cryptography' package so receipts can be Ed25519-signed ...${NC}"
    PIP_USER="$PY -m pip install --user --quiet --disable-pip-version-check"
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
        echo -e "${CYAN}      $PY -m pip install --user --break-system-packages cryptography${NC}"
        echo -e "${CYAN}      pipx install cryptography${NC}    ${BLUE}# if you use pipx${NC}"
        echo -e "${BLUE}    (verify with:  $PY -c \"import cryptography\"  — no output means it's ready)${NC}"
    fi
fi

# ---- Studio (the visual builder) — fetch + unpack the station bundle (one-time, ~22MB) ----
STATION_URL="https://github.com/patl4588/railcall-core/releases/download/station-v0.16/railcall_station.tar.gz"
# Mirror on our own origin. The tarball had ONE source, so a network that rewrites or
# blocks github.com failed the install outright even after the CLI files recovered.
# STATION_SHA is enforced identically on whichever source answers, so the mirror cannot
# substitute a different bundle.
STATION_URL_MIRROR="https://railcall.ai/railcall_station.tar.gz"
STATION_DIR="$RC_HOME/station"
echo -e "${BLUE}Downloading the RailCall Studio (one-time, ~22MB) ...${NC}"
station_get() {
    for u in "$STATION_URL" "$STATION_URL_MIRROR"; do
        fetch "$u" "$RC_HOME/station.tar.gz" || continue
        a=$(sha256_of "$RC_HOME/station.tar.gz")
        if [ "$a" = "$STATION_SHA" ]; then
            [ "$u" = "$STATION_URL_MIRROR" ] && echo -e "${BLUE}  · fetched via railcall.ai (GitHub was unreachable or altered)${NC}"
            return 0
        fi
        STATION_GOT="$a"
        rm -f "$RC_HOME/station.tar.gz"
    done
    return 1
}
if station_get; then
    mkdir -p "$STATION_DIR"
    if tar -xzf "$RC_HOME/station.tar.gz" -C "$STATION_DIR" 2>/dev/null && [ -f "$STATION_DIR/workbench/studio_server.py" ]; then
        rm -f "$RC_HOME/station.tar.gz"
        echo -e "${GREEN}  ✓ Studio installed — run 'railcall studio' to open it in your browser.${NC}"
    else
        rm -f "$RC_HOME/station.tar.gz"
        echo -e "${RED}  ✗ Studio archive downloaded but failed to unpack (CLI still works; re-run the installer for the Studio).${NC}"
    fi
else
    if [ -n "$STATION_GOT" ]; then
        echo -e "${RED}  ✗ SECURITY: the Studio bundle failed its integrity check from every source.${NC}"
        echo -e "${RED}      expected $STATION_SHA${NC}"
        echo -e "${RED}      got      $STATION_GOT${NC}"
        echo -e "${RED}      Your network is probably modifying downloads — the check is working.${NC}"
    else
        echo -e "${RED}  ✗ Could not download the Studio bundle (CLI still works; re-run the installer to retry the Studio).${NC}"
    fi
fi

# Pre-login LOCAL trial token. REAL enforcement state: the CLI reads token["runs_remaining"],
# decrements it per build, and hard-blocks at 0. Re-running never resets an existing token.
# The rc_local_ prefix is a LOCAL sentinel the engine allowlists — it must NEVER touch the gateway.
TOKEN_FILE="$RC_CONF/token.json"
chmod 700 "$RC_CONF" 2>/dev/null || true
if [ ! -f "$TOKEN_FILE" ]; then
    echo '{"api_key": "rc_local_trial_500", "tier": "free", "runs_remaining": 500}' > "$TOKEN_FILE"
    echo -e "${GREEN}Provisioned a pre-login LOCAL trial of 500 flows — enforced by the CLI on this machine only, never a hosted balance.${NC}"
    echo -e "${GREEN}It is replaced by your account balance the moment you run 'railcall login <key>' (free accounts include 500 flows, refilled monthly).${NC}"
else
    echo -e "${GREEN}Existing token kept (not reset).${NC}"
fi
chmod 600 "$TOKEN_FILE" 2>/dev/null || true   # BYOK token file must be owner-only

# Thin wrapper: forward EVERY command + arg straight to the real CLI. No fake telemetry.
# Bakes in the interpreter resolved above ($PY) so 'python'-only setups (Git-Bash) keep working.
cat > "$RC_BIN/railcall" << WRAP
#!/bin/bash
exec $PY "\$HOME/.railcall/railcall_cli.py" "\$@"
WRAP
chmod +x "$RC_BIN/railcall"

# Double-click launcher (macOS): a clickable "RailCall Studio" on the Desktop that opens the Studio.
if [ -d "$HOME/Desktop" ]; then
    LAUNCHER="$HOME/Desktop/RailCall Studio.command"
    printf '#!/bin/bash\nexec "%s" studio\n' "$RC_BIN/railcall" > "$LAUNCHER"
    chmod +x "$LAUNCHER"
    echo -e "${GREEN}  ✓ Double-click 'RailCall Studio' on your Desktop to open the Studio anytime.${NC}"
fi

# Add the bin dir to PATH persistently.
# Special handling for Git Bash / MINGW64 / MSYS on Windows (the environment the reporter
# used): interactive shells source ~/.bashrc, and the default Git Bash setup often relies
# on it. We force .bashrc for MINGW and also touch .bash_profile if it exists.
# This ensures the 'railcall' wrapper stays in PATH after closing the terminal.
SHELL_CONFIG=""
if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || -n "${MSYSTEM:-}" ]]; then
    # Windows Git Bash / MINGW64 / MSYS2
    SHELL_CONFIG="$HOME/.bashrc"
    # Also ensure .bash_profile exists and will source .bashrc (common Git Bash pattern)
    if [ ! -f "$HOME/.bash_profile" ]; then
        echo '# Git Bash default' > "$HOME/.bash_profile"
    fi
    if ! grep -q 'source ~/.bashrc' "$HOME/.bash_profile" 2>/dev/null; then
        echo 'if [ -f ~/.bashrc ]; then . ~/.bashrc; fi' >> "$HOME/.bash_profile"
    fi
elif [ -f "$HOME/.zshrc" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_CONFIG="$HOME/.bash_profile"
fi

if [ -n "$SHELL_CONFIG" ]; then
    mkdir -p "$(dirname "$SHELL_CONFIG")" 2>/dev/null || true
    if [ ! -f "$SHELL_CONFIG" ]; then
        touch "$SHELL_CONFIG"
    fi
    if ! grep -q "$RC_BIN" "$SHELL_CONFIG" 2>/dev/null; then
        echo "" >> "$SHELL_CONFIG"
        echo "# Added by Railcall installer (supports Git Bash/MINGW on Windows)" >> "$SHELL_CONFIG"
        echo "export PATH=\"\$PATH:$RC_BIN\"" >> "$SHELL_CONFIG"
        echo -e "${GREEN}Added $RC_BIN to PATH in $SHELL_CONFIG${NC}"
    fi
fi

echo -e "${GREEN}✅ Installed.${NC}  LOCAL · BYOK · DRY-RUN · NO SENDS — everything runs on 127.0.0.1, nothing fires without your approval."
echo -e "${CYAN}================================================================${NC}"
if [ -n "$SHELL_CONFIG" ]; then
    echo -e "${CYAN}  IMPORTANT — one step so the ${NC}${GREEN}railcall${NC}${CYAN} command is found in NEW terminals:${NC}"
    echo -e "${CYAN}     • Close this terminal and open a fresh one, OR${NC}"
    echo -e "${CYAN}     • Run: source $SHELL_CONFIG${NC}"
    echo -e "${BLUE}     (Git Bash / MINGW users: this writes to ~/.bashrc so it survives session close)${NC}"
else
    echo -e "${CYAN}  IMPORTANT — no shell rc file was found, so PATH was NOT changed.${NC}"
    echo -e "${CYAN}  Paste this into your terminal now (and into your shell startup file to keep it):${NC}"
    echo -e "${GREEN}     export PATH=\"\$PATH:$RC_BIN\"${NC}"
fi
echo -e "${CYAN}================================================================${NC}"
echo -e "${GREEN}Then run:${NC}"
echo -e "${CYAN}   railcall studio${NC}  — open the visual Studio in your browser (127.0.0.1:8799)"
echo -e "${CYAN}   railcall${NC}         — the terminal dashboard (key, flows, commands)"
