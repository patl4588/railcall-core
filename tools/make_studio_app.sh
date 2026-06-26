#!/bin/bash
# Builds "RailCall Studio.app" — an unsigned macOS launcher that boots the local Studio (loopback,
# 127.0.0.1:8799) in the browser. First run bootstraps the station via the network installer; after
# that, a double-click just opens the Studio. No bundled binary, no third-party deps — pure launcher.
set -euo pipefail
OUT="${1:-$PWD}"
APP="$OUT/RailCall Studio.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>RailCall Studio</string>
  <key>CFBundleDisplayName</key><string>RailCall Studio</string>
  <key>CFBundleIdentifier</key><string>ai.railcall.studio</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>RailCall Studio</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>LSBackgroundOnly</key><false/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/RailCall Studio" <<'LAUNCH'
#!/bin/bash
# RailCall Studio — double-click launcher (loopback Studio at 127.0.0.1:8799).
export PATH="$HOME/.railcall/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
STATION="$HOME/.railcall/station/workbench/studio_server.py"
notify(){ /usr/bin/osascript -e "display notification \"$1\" with title \"RailCall Studio\"" >/dev/null 2>&1 || true; }

if [ ! -f "$STATION" ]; then
  notify "First run — setting up RailCall Studio (one-time)…"
  /usr/bin/osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
  /usr/bin/osascript -e 'tell application "Terminal" to do script "curl -fsSL https://railcall.ai/install.sh | bash && echo && echo \"Setup complete — double-click RailCall Studio again to open it.\""' >/dev/null 2>&1 || true
  exit 0
fi

notify "Starting RailCall Studio…"
( STUDIO_PORT=8799 /usr/bin/env python3 "$STATION" --no-open >/tmp/railcall-studio.log 2>&1 & )
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  /usr/bin/curl -s -o /dev/null "http://127.0.0.1:8799/" 2>/dev/null && break
  sleep 0.5
done
/usr/bin/open "http://127.0.0.1:8799/v2" 2>/dev/null || /usr/bin/open "http://127.0.0.1:8799/" 2>/dev/null || true
LAUNCH
chmod +x "$APP/Contents/MacOS/RailCall Studio"

( cd "$OUT" && rm -f RailCall-Studio.zip && /usr/bin/zip -qry RailCall-Studio.zip "RailCall Studio.app" )
echo "built: $APP"
echo "zip:   $OUT/RailCall-Studio.zip"
