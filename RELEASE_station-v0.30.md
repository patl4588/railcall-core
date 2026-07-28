# RailCall Station v0.30 — MCP schema honesty + Modules tab rework

**Status:** cut. Follow-up on v0.29's contest-publisher unblock — deeper MCP
schema work + a full pass on the Modules tab UX.

## MCP audit — every tool now has an honest schema

The whole audit started when Rayan reported his Pipedrive module was
invisible in tools/list (v0.29 fixed that — tools appear now). Digging
deeper, v0.30 fixes the FOLLOW-ON gap: tools were visible but their
schemas were opaque or invalid.

### Batch 1 — schema derivation code

`tool_schema()` in integration_registry.py was punting: `required[]`
always empty, no per-property descriptions. Rewrote to derive both from
the SAME `arg_specs` the Studio form uses — single source of truth,
drift-impossible. Descriptions only emitted when they add information
the LLM couldn't infer from the field name (no fake "Team Id" for
`team_id`). Enums from `options`, defaults straight through.

Also: HTTP transport bearer compare now uses `hmac.compare_digest`
after length check — textbook constant-time hygiene, though the loopback-
only transport limits blast radius.

### Batch 2 + 3 — arg_schema on 24 first-party integrations

Every one of the 24 built-in `_plan` tools now carries a real
arg_schema:

- Linear, Twilio, GCal, S3, Intercom, Salesforce (batch 2)
- Airtable, HubSpot, Postgres, GSheets, Webhook, Discord, Code Patch,
  Checks (batch 3 standalones)
- The 7-integration external_post shim family (teams, webhook_out,
  gsheets_out, gdocs, telegram, resend, notion) — enriched the
  `_ep_entry()` factory once so all seven get identical documented
  schemas without seven copies to keep in sync (batch 3)

Every field's required-vs-optional was derived by READING the actual
plan_* signature — matched exactly what the primitive validates.

Coverage: 24/24 with per-prop descriptions, 21/24 with populated
required[] (postgres/webhook/discord honestly take zero required
inputs — every arg has a default in the primitive).

### Batch 4 — publisher input_schema → valid JSON Schema

The big latent bug: every one of the 27 module-declared tools that v0.29
started exposing was shipping an **invalid JSON Schema**. tools/list
surfaced them; tools/call from any conformant host would have been
silently refused — the shape didn't have `type: "object"`, didn't have a
`properties` wrapper.

Root cause: publishers write `input_schema` in Studio's arg_specs shape
(a flat `{field: {type, required, ...}}` dict), not JSON Schema. The
prior code passed it through untouched.

Fix: new `_normalize_module_input_schema()` in mcp_server.py detects the
shape and converts. Real JSON Schema (has `type` or `properties` at
top) passes through with a defensive type default. Publisher/Studio
shape gets wrapped in `{"type":"object","properties":{...},"required":[...]}`,
`'text'` → `'string'` normalized, description from `help`/`label`
surfaced.

Verified against every real installed module: 27/27 now emit valid JSON
Schema with correctly-derived required[]:

- discord: `['content']`
- github: `['title','body']`
- hubspot contact.create: `['email']`
- salesforce lead.create: `['last_name','company']`

## Modules tab — collapse + ownership + single-page detail

Complaint from live use: the Salesforce card (20 commands + full
description + full module_dir path + license + fingerprint) rendered as
one huge slab pushing other modules below the fold, with no visual cue
for "which of these did I publish myself?" vs "which am I subscribed
to?".

### Collapsed cards by default

Compact header row: `▸ <id> · v<version> · [✓ loaded] · [owner chip]
[Reload] [Sends] [Details]`. That's ~44px + license row instead of
~280px. Description, full command grid, publisher fingerprint,
module_dir path, and the (destructive) Uninstall button all move behind
an expand toggle. Body renders lazily on first click so a fleet of
installed modules paints fast.

### Ownership chip — three honest tiers

- `✎ owned by you` — the module's publisher_pubkey_fp starts with the
  user's local marketplace_publisher fingerprint. Definitive; the same
  key signed the bundle and the user's own publishes.
- `✓ your subscription` — a valid module license is bound to this
  install (`m.license.tier` present).
- (nothing) — bundled first-party or install without a publisher key
  minted. A chip would be noise, not signal.

### Single-page detail view at `#/modules?slug=<slug>`

Full page for one installed module, reached via the Details button on
each card (or bookmarkable). Shows: full title + ownership header,
at-a-glance strip (slug / commands count / license state / publisher
fp), full description, registered-commands list with per-row Sends
deep-link, install location, and a red-bordered Danger zone with
Uninstall.

Rejected modules get a real detail page too — rejection reason
full-width + Buy license / Activate CTAs when applicable. Missing slug
falls back to a small "no such module" pane with a link back to the list.

## What's changed since v0.29

- `_vault_get()` bridges Phase-2 credential vault (already in v0.29)
- `workbench/mcp_server.py` tools/list includes modules (already in v0.29)
- `tool_schema()` in integration_registry.py derives real
  required[]/descriptions
- arg_schema on all 24 first-party integrations
- Publisher input_schema normalized into valid JSON Schema for all
  installed modules
- HTTP transport bearer uses `hmac.compare_digest`
- Modules tab: collapsed cards + ownership chip + `?slug=` detail view
- `/api/modules/list` returns `local_publisher_pubkey_fp` for
  ownership detection

## Coordinates

- **Tag:** `station-v0.30`
- **Tarball:** `railcall_station.tar.gz` (5.4M)
- **SHA-256:** `34dc3a40a4d9b5f1dc770303ecbc60e3b7263eca2cb3577ec140358a59037370`
- **install.sh pin:** bumped; STATION_URL points at v0.30 GitHub release
- **Mirror:** `https://railcall.ai/railcall_station.tar.gz`
