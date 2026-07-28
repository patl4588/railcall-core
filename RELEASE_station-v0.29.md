# RailCall Station v0.29 — contest-publisher unblock + Studio audit pass

**Status:** cut.

Two publisher-reported platform bugs land here alongside a full page-by-page
Studio pass. If you are Muhammad Akif Janjua (Linear Guard) or Rayan Mufeed
(Pipedrive) — v0.29 is the release your v1.4.0 / v1.1.0 modules need to work
against.

## Contest-publisher fixes

### 1. `vault_get()` now bridges the Phase-2 named-credential vault

Muhammad's Linear Guard v1.4.0 honored the Round-1 review (drop the direct
`credentials.local.json` fallback, use `vault_get("linear")` exclusively) —
but `vault_get()` only read the legacy `keys.local.json`, so a credential
saved through Studio → Integrations (which writes to `credentials.local.json`)
resolved to `None` for the module handler even after HTTP 200 test success.

Resolution order is now:
1. Legacy `keys.local.json` entry — wins byte-for-byte if present so no
   existing install changes behavior.
2. Phase-2 vault (`credentials.local.json`) — pick the provider's default
   credential (or the first alphabetically if no default) and return its
   `fields` dict. Same shape existing handlers accept.

**Impact:** Round-1-clean modules that read `vault_get("<provider>")` now
receive the Studio-saved credential without any manual bridging.

### 2. MCP `tools/list` includes installed modules

Rayan's Pipedrive v1.1 loaded fine in Studio but was invisible to
`tools/list` from any MCP host (Claude Desktop / VS Code / Cursor / MCP
Inspector). Root cause: `workbench/mcp_server.py` only advertised the
built-in TOOLS dict; module `commands[]` from `module.json` files were never
scanned.

`tools/list` now merges live module discovery on each call — a fresh
`railcall market install <module>` propagates on the very next `tools/list`
without an MCP-server restart. Tools are namespaced `<slug_tail>.<cid>`
(matches the Studio Modules-tab chips + Sends provider grouping).

`tools/call` for a namespaced module command returns an actionable pointer
at Studio's airlock + the exact `railcall airlock stage <name> --inputs
<json>` command (`isError: true` so hosts render it as a real failure the
operator can act on). Execution stays in the airlock — this is intentional,
not a bug: running a module handler needs the signature-verify + trust +
license + sandbox chain that lives in Studio.

**Impact:** MCP hosts see the same tools list a user sees in Studio Modules;
governed execution routes cleanly to the airlock for approval.

## Studio audit — 6-batch page-by-page pass

Every top-level Studio view got a targeted fix. All changes are additive over
v0.28 — existing callers hit the same paths byte-for-byte.

**Settings + fingerprint visibility.** Signing key card now iterates the real
`pubkey.public_key_hex || public_key || pubkey` fallback chain, so the key
+ `key_id` fingerprint appear consistently across Settings, sidebar, and Copy
button. Fingerprint is now a chip next to the key so the operator can compare
it to a receipt's `key_id` at a glance.

**Real safety-flags posture.** Settings → Safety flags no longer renders
hardcoded UI literals. New `/api/safety/flags` endpoint serves the actual
enforcement state (dry-run default, loopback-only, CSRF guard, dual-control)
sourced from the running server. The card iterates the flag map — so a new
guard added on the server surfaces without a UI change.

**Real audit-chain state.** Audit view now reads `chain_head`, `chain_height`,
`chain_intact`, `first_break`, `legacy_unchained`, `chain_note` from the
`audit_state()` endpoint. Chain-state chip flips red `BREAK@N` if
`audit_chain.verify()` finds tampering. "Honest scope" caveat is rendered
verbatim from the primitive rather than paraphrased in the UI.

**Batch receipt verifier.** Receipts view has a Verify-all button wired to
`/api/receipts/verify_all` (real batch call, not per-row spam). Every row
gets a per-verdict chip: `VERIFIED` / `VERIFIED_MOCK` / `UNSIGNED` /
`UNTRUSTED_KEY` / `FAIL_INTEGRITY` / `FAIL_AUDIT` / `FAIL_UNREADABLE` —
color-coded so an entire chain's health is visible without opening receipts
one at a time. Per-row Verify updates the same map so single-receipt checks
also light up the chip.

**Sends v2 layout.** Registered commands now group by provider (module),
uniform card height (`min-height: 132px` via CSS grid `auto-fill / minmax
320px 1fr`), and cap 3 cards per module by default with a "View all N →"
drilldown that filters via `#/sends?module=<slug>`. A first-run empty state
routes to marketplace + modules; a filtered-empty group renders a Clear-filter
control instead of hiding all commands.

**Canvas Save + Load round-trip.** New `POST /api/workflow/save` writes a
Canvas-authored rail to `WS/workflows/<id>.json` with `kind: "canvas"` and
a signed `RAIL_SAVED` receipt. Honesty gate refuses to overwrite a
compose_engine build sharing the id. `GET /api/workflow/spec?id=` rehydrates
the DAG. Canvas Save button + `#/canvas?open=<id>` deep link let a rail be
refreshed to the same URL and re-opened. `/api/flow/sources` extended to
surface canvas rails so Programs shows them.

**Programs Delete + Edit.** User-owned rails get a Delete button with typed-
name confirmation (matches the server contract at `/api/workflow/delete`).
Canvas rails additionally get an Edit button routing to
`#/canvas?open=<name>`. Compose builds don't get Edit — they can't rehydrate
into the DAG editor.

**Modules per-card Reload + View-in-Sends.** Each loaded module card now has
its own Reload button that reports per-slug outcome (green toast if the slug
came back loaded, red inline error with exact rejection reason if it failed,
warning if the slug vanished) — instead of one process-wide "Reload all"
that gave a generic count. A "View in Sends →" link jumps to the module's
registered commands in the airlock.

**Router UI.** Deterministic-floor banner at the top makes clear that
"unbound" is a legitimate first-class state, not an error — the engine's
pure-local floor runs with zero network on unbound roles. Per-role state chip
(green "✓ bound" / muted "floor") flips live on bind. Preflight moved inline
per row (was a single shared status line that got clobbered on multi-role
tests) with a color-coded left-border (info blue for floor, amber for BYOK).

---

## What's changed since v0.28

- `_vault_get()` bridges `credentials.local.json` (Muhammad's contest fix).
- `workbench/mcp_server.py` `tools/list` includes module commands + airlock
  pointer on `tools/call` (Rayan's contest fix).
- Studio: 6-batch audit pass (Settings, Safety flags, Audit chain, Receipts,
  Sends v2, Canvas Save/Load, Programs Delete/Edit, Modules per-card actions,
  Router deterministic-floor UI).
- Dead code removed from `server/mcp/runtime_mcp_v1.py` — the earlier
  attempted MCP fix went to the wrong file (cloud runtime MCP, not the
  station-shipped MCP host).

## Coordinates

- **Tag:** `station-v0.29`
- **Tarball:** `railcall_station.tar.gz` (5.4M)
- **SHA-256:** `eb2a5cbc55ab977cc96eba37573216c280d18b455e5eeac24439bb19600b10a1`
- **install.sh pin:** bumped to the SHA above with `STATION_URL` pointing at
  the v0.29 GitHub release + `STATION_URL_MIRROR` at railcall.ai.
- **Mirror:** `https://railcall.ai/railcall_station.tar.gz` (already updated
  in `railcall-contrib/website-v2/public/`).
