# RailCall Station v0.32 — CLI: private-delivery publish flags

**Status:** cut. CLI-only release. Station tarball unchanged from v0.30
(STATION_URL still points at the v0.30 GitHub release + mirror).

## What's new

Three new flags on `railcall market publish`:

```
railcall market publish <module-dir> --type=module \
  --visibility=private_delivery \
  --source-request=<request-uuid> \
  --authorized-buyers=<user-uuid,user-uuid>
```

**When to use them:** you've been awarded a bespoke module request on the
marketplace and want to publish your delivery so only the buyer can
install. Values come pre-filled by the request detail page in-app
(there's a copy-to-clipboard cheatsheet you can grab them from), or you
can type them manually.

**Backend contract** (marketplace already shipped):

- `visibility=private_delivery` requires both `source_request_id` +
  `authorized_buyer_ids` — enforced server-side.
- Caller must be the awarded seller on the referenced request.
- `authorized_buyer_ids` must include the request's buyer (otherwise
  the seller could publish a private module the buyer can't install).
- Private-delivery listings skip the `pending_review` moderation queue —
  they're targeted to one buyer, invisible to the public browse.

Underscore aliases (`--source_request` / `--authorized_buyers`) accepted
too so the same command works whether the operator copied from the FAQ
(dashes) or hand-typed with underscores.

## Coordinates

- **Tag:** `station-v0.32`
- **Station tarball:** unchanged from v0.30 (SHA
  `34dc3a40a4d9b5f1dc770303ecbc60e3b7263eca2cb3577ec140358a59037370`,
  STATION_URL still points at v0.30 release)
- **CLI SHA (`railcall_cli.py`):** `534307cf07def96f94f7ec0e1ebd8695d6ff7a73320dccbde676721eee1bccea`
- **install.sh:** CLI pin bumped + telemetry version → `0.32.0`
- **Mirror:** `https://railcall.ai/cli/railcall_cli.py` updated

## Upgrade path

`curl -fsSL railcall.ai/install.sh | sh` fetches the new CLI. No tarball
re-download needed — install.sh short-circuits when the already-installed
station SHA matches the pin.

## Not here

- Admin dispute-resolution UI is now live at `railcall.ai/marketplace/admin/disputes`
  (marketplace + website changes; no CLI surface needed).
- Publisher analytics dashboard is at
  `railcall.ai/marketplace/dashboard/publisher` (same — no CLI surface).
- Phase 4 module sandbox — subprocess + network allowlist for module
  handlers — is the next station-tarball-affecting change; will be
  station-v0.33 when it lands.
