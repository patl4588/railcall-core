# RailCall Station v0.31 — CLI: module sign + verify

**Status:** cut. CLI-only release. The station tarball is unchanged from
v0.30 (STATION_URL still points at the v0.30 GitHub release + mirror);
the only user-facing change is two new `railcall` subcommands.

## What's new

Two subcommands publishers have referenced in FAQ + reply threads since
v0.22 (modules system) but that until v0.31 required an external
Ed25519 signer:

```
railcall market module sign   <module-dir>
railcall market module verify <module-dir>
```

### `sign`

Signs a module bundle (`module.json` + `handlers/handler.py`) with the
local publisher keypair and writes `module.sig` into the bundle dir.

- **Idempotent** — re-running against an unmodified bundle produces an
  identical `module.sig` (Ed25519 is deterministic).
- **Publisher-pubkey guard** — refuses if the manifest names a
  different pubkey than the local publisher key. `--force` overrides:
  auto-rewrites `manifest.publisher_pubkey` before signing.
- **Signature contract** matches `workbench/studio_server._verify_module_signature`
  byte-for-byte:
  `canonical(module.json without "signature") || b"\n" || handler.py bytes`
  where canonical = `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

### `verify`

Verifies an existing `module.sig` against the manifest's embedded
`publisher_pubkey`. Zero network. Uses the SAME recipe the station
loader uses at install time — so a green result guarantees a buyer's
station will accept the module on load (subject to trust allowlist +
license checks which apply separately).

- **Ownership annotation** — prints "✓ signed by your local key" when
  the signer matches your local publisher, or a neutral "signed by a
  DIFFERENT key" when it doesn't. No judgment either way.
- **Failure diagnosis** — enumerates the three common causes when a
  signature is invalid (post-signing edit, wrong key, mismatched
  manifest pubkey) and points at `sign` as the fix.

## Cross-verified

The CLI's `sign` output is accepted byte-for-byte by the station's
`_verify_module_signature` — confirmed via a synthetic bundle whose
CLI-produced `module.sig` was verified with the actual station code
imported inline.

## Coordinates

- **Tag:** `station-v0.31`
- **Station tarball:** unchanged from v0.30 (SHA
  `34dc3a40a4d9b5f1dc770303ecbc60e3b7263eca2cb3577ec140358a59037370`,
  STATION_URL still points at v0.30 release)
- **CLI SHA (`railcall_cli.py`):** `4a6ce9383e752995e3ea0c41ea5adb742140de985b63922f23c39b06ad488bcd`
- **install.sh:** CLI pin bumped + telemetry version → `0.31.0`
- **Mirror:** `https://railcall.ai/cli/railcall_cli.py` updated

## Upgrade path

`curl -fsSL railcall.ai/install.sh | sh` will fetch the new CLI. No
tarball re-download needed — install.sh short-circuits when the
already-installed station SHA matches the pin.

## What's NOT here (deferred)

- Admin dispute-resolution UI for private-delivery escrows (backend
  `refundOnDispute` method exists; admin surface to trigger it does
  not).
- Seller-side "publish private delivery" first-class UI (the
  `visibility=private_delivery` + `source_request_id` +
  `authorized_buyer_ids` fields work via CLI or hand-crafted publish
  JSON; a dedicated form on the request detail page is polish).
