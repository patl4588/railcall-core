# RailCall Station v0.7 — airlock covers ALL send endpoints + HTTP route names the honest caller

**Status:** DRAFT — release notes body ready. Tarball cut is Sami's gate.

Continues the v0.6 arc. v0.6 closed *"discord/slack sends now go through the airlock, `approval.method` no longer lies at the library level."* v0.7 closes the remaining gap: **the other seven send endpoints** (teams, webhook, gsheets, gdocs, telegram, resend, notion) ship on the same airlock rail, and the **HTTP route** — not just the library — now propagates the caller channel honestly.

## What's new

**1. Seven more send endpoints on the airlock rail.** Before v0.7, `POST /api/{teams,webhook,gsheets,gdocs,telegram,resend,notion}/send` was raw urllib — no staging, no policy, no signature, no on-disk audit. From v0.7 they all route through the same `stage → policy → sign → approve → Saga → signed receipt` pipeline discord/slack got in v0.6. One generic primitive (`external_post`) + a per-provider adapter (~6 lines of config each) replaces seven near-identical stage/apply pairs. Naming: the send-post variants of `webhook`/`gsheets` register as `webhook_out`/`gsheets_out` because the plain keys already own the workflow-engine `fire_hook`/`variance` primitives shipping in the 133k library — no collision. Vault-key aliasing (`teams` reads legacy `msteams`; `webhook_out` reads `webhook`; `gsheets_out` reads `gsheets`) keeps every existing station config working with zero user action. Engine PR: patl4588/railcall-engine#41.

**2. HTTP route stops silently claiming "ui_click".** v0.6 fixed `studio_integration_send.approve()` at the library level to accept `approval_channel`, but the HTTP handler for `POST /api/integration/approve` never extracted the field from the request body — so every HTTP approve continued to mint receipts stamping `approval.method="ui_click"` regardless of what the caller sent (`vscode_chat`, `cli`, `mcp_tools_call`, …). v0.7 patches the route to forward the body's `approval_channel` verbatim; the auditor's allowlist from v0.6 covers it. Engine PR: patl4588/railcall-engine#42.

**3. `_airlock_send` no longer squashes unknown channels.** Related to #2, `_airlock_send` (the internal helper the `/api/*/send` endpoints call) used to squash any non-`cli`/`studio` source down to `"vscode_chat"`. v0.7 preserves the caller's explicit `approval_channel` (so `mcp_tools_call` passes through), and only falls back to User-Agent inference when the body doesn't specify. Shipped as part of #41.

**4. Dead-code fix: `/api/webhook/send`.** Discovered during v0.7 wiring: the pre-v0.7 route was **dead code on main** — the `webhook_in` ingest glob (`/api/webhook/<slot>`) runs earlier in `do_POST` and swallowed `/send` as slot `"send"`, answering `{"ok": true}` while no send ever fired. Carved the send route out of the ingest namespace; slot `send` now reserved on the ingest side. Shipped as part of #41.

## Also on the tarball (already on engine main, cosmetic for release)

- **PR #37** — `STATION_VERSION.json` schema alignment so the built manifest matches what the boot handshake expects.
- **PR #38** — regression test locking in the v0.6 `approval_channel` library fix.
- **PR #39** — reconcile: the live-station `/api/*/send` shape (discord/slack + `_airlock_send`) already shipping in the v0.6 tarball is now on engine `main` too, ending the engine-vs-live-station divergence.

## Verify

```
shasum -a 256 railcall_station.tar.gz
# bb69d817daf345f3ebdd2877f2502550d4fde110787a9bb2e6d1bbf141157088
```

This SHA will be pinned in `install.sh` (`STATION_SHA`) and enforced fail-closed by the installer.

## Coverage after v0.7

| /api/*/send endpoint | Airlock status |
|---|---|
| slack, discord | on airlock rail (v0.6) |
| teams, webhook, gsheets, gdocs, telegram, resend, notion | on airlock rail (v0.7) |
| github | still raw — reversible-verb primitive lives on a separate airlock path, own wiring later |

## Compat

- **No config-file changes required.** Vault-key aliasing keeps `msteams`, `webhook`, and `gsheets` entries working; the registry keys `teams`, `webhook_out`, `gsheets_out` are used internally.
- **Receipts** for the seven new providers land as `railcall_{provider}_apply_receipt.v1` in `<WS>/receipts/capoff/`. The VS Code extension's `RailCallReceiptsProvider` discovers them by suffix — zero UI edits needed.
- **URL paths unchanged.** Callers keep POSTing to `/api/teams/send`, `/api/webhook/send`, etc. Only the internal registry key and receipt filename differ for `webhook_out`/`gsheets_out`.

## Manifest shipped

```
{
  "release_tag": "station-v0.7",
  "built_at": "2026-07-16T20:08:53Z",
  "mcp_transport": "airlock",
  "registry_version": 1,
  "engine_commit": "bec1605e5",
  "core_commit": "1890420"
}
```

## Verification of THIS bundle (SHA `bb69d817…`; live :8799 never touched)

1. Built in a temp tree = installed station structure + engine-`main` `workbench/` overlaid, using the **hardened** build script (5 new factory-artifact excludes + extended fail-closed leak gate: `combinatorics|bulk_indexer|adapter_parity|MIGRATION`).
2. Leak gate: clean. Manifest diff vs published v0.6: nothing dropped; new files are `external_post.py` + the workflow-engine runtime set (`workflow_*.py`, `billing_telemetry.py` — all imported by `studio_server.py`).
3. Booted the unpacked tarball on throwaway `:8801`: `/api/version` announces `station-v0.7`, `/api/registry` → **22 ready of 23**, bundled airlock MCP announces **47 tools** (`railcall-airlock 1.0.0`).
4. Full governed round trip inside the bundle: legacy `msteams` vault key (proves `teams`→`msteams` aliasing) → `POST /api/teams/send` with `approval_channel: cli` → loopback mock got exactly one hit → `railcall_teams_apply_receipt.v1` on disk, `outcome: SENT`, `approval.method: cli`, Ed25519 signature **`signed_and_verified`** against the install pubkey.
5. Unconfigured provider → helpful 400 (`"Microsoft Teams not configured…"`) **before** staging, no raw send.

## To publish (Sami — this is the gate)

```bash
# 1. build the tarball from engine main @ bec1605e5 + patched build script
# 2. cut the release, uploading the exact verified tarball
gh release create station-v0.7 \
  ~/Desktop/railcall_station_v0.7.tar.gz#railcall_station.tar.gz \
  --repo patl4588/railcall-core \
  --title "station-v0.7 — airlock covers ALL send endpoints + HTTP route names the honest caller" \
  --notes-file RELEASE_station-v0.7.md

# 3. bump install.sh — one line + one URL:
#      STATION_SHA="<sha from step 1>"
#      STATION_URL=".../station-v0.7/railcall_station.tar.gz"
# 4. verify the published asset SHA matches install.sh
curl -fsSL https://github.com/patl4588/railcall-core/releases/download/station-v0.7/railcall_station.tar.gz \
  | shasum -a 256   # must equal STATION_SHA

# 5. merge the install.sh bump to main (install.sh v0.7 goes live only after the release asset exists)
```
