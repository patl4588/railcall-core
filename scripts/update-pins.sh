#!/usr/bin/env bash
FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"
for f in $FILES; do
    hash=$(shasum -a 256 "$f" | awk '{print $1}')
    sed -i.bak -E "s/([[:space:]]*)$f\) echo [a-f0-9]{64}/\1$f) echo $hash/" install.sh
    echo "updated $f → $hash"
done

# Recompute STATION_SHA from current clean tarball (run build_station_tar.sh first)
STATION_TAR="/tmp/railcall_station.tar.gz"
if [ -f "$STATION_TAR" ]; then
    hash=$(shasum -a 256 "$STATION_TAR" | awk '{print $1}')
    sed -i.bak -E 's/(STATION_SHA=")[a-f0-9]{64}(")/\1'"$hash"'\2/' install.sh
    echo "updated STATION_SHA → $hash"
else
    echo "STATION_TAR not found at $STATION_TAR — run scripts/build_station_tar.sh to update"
fi
rm -f install.sh.bak
