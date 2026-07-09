#!/usr/bin/env bash
FILES="railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py"
for f in $FILES; do
    hash=$(shasum -a 256 "$f" | awk '{print $1}')
    sed -i.bak -E "s/([[:space:]]*)$f\) echo [a-f0-9]{64}/\1$f) echo $hash/" install.sh
    echo "updated $f → $hash"
done
rm -f install.sh.bak
