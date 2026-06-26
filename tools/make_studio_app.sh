#!/bin/bash
# Rebuilds RailCall-Studio.zip — a self-contained, unsigned "RailCall Studio.app" that bundles the station
# and double-clicks open the loopback Studio (127.0.0.1:8799/v2). No Terminal, no install step, no folder.
# Usage: tools/make_studio_app.sh [path/to/railcall-studio.tgz]   (defaults to ./railcall-studio.tgz)
set -euo pipefail
TGZ="${1:-$(cd "$(dirname "$0")/.." && pwd)/railcall-studio.tgz}"
SRC=$(mktemp -d); tar -xzf "$TGZ" -C "$SRC"; STATION="$SRC/railcall-studio"
OUT="$(cd "$(dirname "$0")/.." && pwd)"; APP="$OUT/RailCall Studio.app"; rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"; cp -R "$STATION" "$APP/Contents/Resources/station"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>RailCall Studio</string>
  <key>CFBundleDisplayName</key><string>RailCall Studio</string>
  <key>CFBundleIdentifier</key><string>ai.railcall.studio</string>
  <key>CFBundleVersion</key><string>0.2</string>
  <key>CFBundleShortVersionString</key><string>0.2</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>RailCall Studio</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/RailCall Studio" <<'LAUNCH'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"; BUNDLED="$HERE/../Resources/station"; HOME_STATION="$HOME/.railcall/station"; PORT=8799
notify(){ /usr/bin/osascript -e "display notification \"$1\" with title \"RailCall Studio\"" >/dev/null 2>&1 || true; }
if [ ! -f "$HOME_STATION/workbench/studio_server.py" ]; then /bin/mkdir -p "$HOME/.railcall" && /bin/cp -R "$BUNDLED" "$HOME_STATION" 2>/dev/null || true; fi
SERVER="$HOME_STATION/workbench/studio_server.py"; [ -f "$SERVER" ] || SERVER="$BUNDLED/workbench/studio_server.py"
if ! /usr/bin/curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  notify "Starting RailCall Studio…"
  ( cd "$(dirname "$(dirname "$SERVER")")" && STUDIO_PORT=$PORT /usr/bin/env python3 "$SERVER" --no-open >/tmp/railcall-studio.log 2>&1 & )
  for _ in $(seq 1 18); do /usr/bin/curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null && break; sleep 0.4; done
fi
/usr/bin/open "http://127.0.0.1:$PORT/v2" 2>/dev/null || /usr/bin/open "http://127.0.0.1:$PORT/" 2>/dev/null || true
LAUNCH
chmod +x "$APP/Contents/MacOS/RailCall Studio"
( cd "$OUT" && rm -f RailCall-Studio.zip && /usr/bin/zip -qry RailCall-Studio.zip "RailCall Studio.app" && rm -rf "RailCall Studio.app" )
rm -rf "$SRC"; echo "built $OUT/RailCall-Studio.zip"
