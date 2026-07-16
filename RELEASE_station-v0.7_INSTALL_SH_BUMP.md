# install.sh v0.7 bump — ready-to-apply edits

Two edits, both mechanical. Do them **after** the v0.7 tarball is uploaded to GitHub releases and the SHA is measured against the published asset (not the local file — always verify against the live URL to catch any upload corruption).

## Edit 1 — `STATION_SHA` (install.sh:21)

```diff
- STATION_SHA="ea89076ddeb1dbf046202ac55781a876b79e3c3a86f2504db9256b794592353f"
+ STATION_SHA="<sha256 of the published v0.7 tarball>"
```

Measure it from the published asset (not local — this catches upload corruption):

```bash
curl -fsSL https://github.com/patl4588/railcall-core/releases/download/station-v0.7/railcall_station.tar.gz \
  | shasum -a 256 | awk '{print $1}'
```

## Edit 2 — `STATION_URL` (install.sh:202)

```diff
- STATION_URL="https://github.com/patl4588/railcall-core/releases/download/station-v0.6/railcall_station.tar.gz"
+ STATION_URL="https://github.com/patl4588/railcall-core/releases/download/station-v0.7/railcall_station.tar.gz"
```

## Order matters

The release asset **must exist** before install.sh v0.7 lands on `main`, otherwise a live `curl … | bash` would 404 on the tarball fetch and half-install the CLI without the Studio. Sequence:

1. Build tarball locally, verify sha, upload as `station-v0.7` release asset.
2. `curl` the published URL, confirm the sha matches what you're about to pin.
3. Apply the two edits above on a branch.
4. Merge to `main`.

## Optional but recommended — regen the CLI-file pins if any changed

`pin_for()` at install.sh:76 hashes `railcall_cli.py`, `railcall_companion_daemon.py`, `vault_io.py`, `receipt_signer.py`, and the six governance files. If any of these changed since v0.6, regen the pins per the comment at install.sh:71:

```bash
cd /Users/macbook/raill/railcall-core
for f in railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py; do
  printf '        %-30s echo %s ;;\n' "$f)" "$(shasum -a 256 "$f" | awk '{print $1}')"
done
```

Paste output over the case arms 78-81 (and repeat with the six governance files for arms 82-87). A `git diff main..HEAD -- railcall_cli.py railcall_companion_daemon.py vault_io.py receipt_signer.py governance/` will tell you if any changed since v0.6.
