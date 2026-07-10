#!/usr/bin/env bash
# Re-pin BOTH installers after an intentional change to the core files or the station bundle.
#
#   ./scripts/build_station_tar.sh     # rebuild /tmp/railcall_station.tar.gz first (optional)
#   ./scripts/update-pins.sh
#
# install.sh and install.ps1 each REFUSE any file whose sha256 does not match its pin, so a pin this
# script fails to write is not a cosmetic problem — it hard-fails installs on that OS. Every write is
# therefore read back and verified, and the script exits non-zero if any pin did not land.
set -uo pipefail

FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"
STATION_TAR="${STATION_TAR:-/tmp/railcall_station.tar.gz}"

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else shasum -a 256 "$1" | awk '{print $1}'; fi
}

fail=0

for f in $FILES; do
    hash=$(sha256 "$f")
    esc=${f//./\\.}   # a literal '.' in the filename must not act as regex any-char

    # install.sh:  "        railcall_cli.py)              echo <sha> ;;"  (alignment preserved)
    sed -i.bak -E "s/^([[:space:]]*${esc}\))([[:space:]]*)echo [a-f0-9]{64}/\1\2echo ${hash}/" install.sh
    # install.ps1: "    'railcall_cli.py'              = '<sha>'"        (alignment preserved)
    sed -i.bak -E "s/^([[:space:]]*'${esc}'[[:space:]]*= ')[a-f0-9]{64}(')/\1${hash}\2/" install.ps1

    got_sh=$(grep -E "^[[:space:]]*${esc}\)" install.sh  | grep -oE '[a-f0-9]{64}' | head -1)
    got_ps=$(grep -E "^[[:space:]]*'${esc}'"  install.ps1 | grep -oE '[a-f0-9]{64}' | head -1)
    if [ "$got_sh" = "$hash" ] && [ "$got_ps" = "$hash" ]; then
        echo "ok    $f → $hash"
    else
        echo "FAIL  $f — pin did not land (install.sh=$got_sh install.ps1=$got_ps want=$hash)"
        fail=1
    fi
done

# The station bundle is a RELEASE ASSET, not a repo file. Pin whatever build_station_tar.sh produced;
# that exact tarball is what must then be uploaded to the release, or installs break everywhere.
if [ -f "$STATION_TAR" ]; then
    hash=$(sha256 "$STATION_TAR")
    sed -i.bak -E "s/(STATION_SHA=\")[a-f0-9]{64}(\")/\1${hash}\2/" install.sh
    sed -i.bak -E "s/(\\\$StationSha = ')[a-f0-9]{64}(')/\1${hash}\2/" install.ps1

    got_sh=$(grep -E '^STATION_SHA=' install.sh   | grep -oE '[a-f0-9]{64}' | head -1)
    got_ps=$(grep -E '^\$StationSha'  install.ps1 | grep -oE '[a-f0-9]{64}' | head -1)
    if [ "$got_sh" = "$hash" ] && [ "$got_ps" = "$hash" ]; then
        echo "ok    STATION_SHA → $hash"
        echo
        echo "NEXT: upload THIS EXACT tarball, or the pin you just wrote refuses the published asset:"
        echo "  gh release upload station-v0.1 $STATION_TAR --repo patl4588/railcall-core --clobber"
    else
        echo "FAIL  STATION_SHA — pin did not land (install.sh=$got_sh install.ps1=$got_ps want=$hash)"
        fail=1
    fi
else
    echo "skip  STATION_SHA — no tarball at $STATION_TAR (run scripts/build_station_tar.sh to re-pin it)"
fi

rm -f install.sh.bak install.ps1.bak

if [ "$fail" != 0 ]; then
    echo
    echo "ERROR: at least one pin was NOT written. Do not commit — installs would break on that OS." >&2
    exit 1
fi
echo
echo "All pins written to install.sh AND install.ps1."
