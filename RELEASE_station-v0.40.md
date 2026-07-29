# station-v0.40

Full ship of Shweta's 4-item integrations honesty batch — the punch
list she surfaced in the vault/status thread that also produced the
sandbox bug fixed in v0.37.

## What ships

### #1 — Unified integration status per provider

`integrations_list()` reads both credential stores (legacy
`keys.local.json` + Phase-2 `credentials.local.json`), resolves to
ONE state per provider using the same order `_vault_get` uses at
runtime, and returns `resolved_via ∈ {legacy, named,
named_no_default, none}`. Studio's Integrations card now shows one
line per provider instead of two competing states side-by-side.

### #2 — Honest "credential on file — needs verify" copy

New terminal status `credential_present_untested` — commands remain
gated (same enforcement as `not_configured` for runtime purposes),
but the UI label is honest: **"Needs verify"** instead of the
misleading "Not set". Operators know Test/Mark-Configured is what
unblocks them, not another credential save.

### #3 — Split Test button into Test (live) and Mark Configured

For providers whose live test isn't wired (NO_DRIVER / OAUTH_FLOW),
the old Test button silently flipped status to `key_present` while
labeling the result "test not wired yet." Operators used Test as an
activation ceremony instead of what it says on the tin.

Now:

- `/api/integration_test` returns `test_not_wired` for these
  providers **without persisting** the status flip.
- New `/api/integration/mark_configured` endpoint provides explicit
  trust ceremony that flips status to `key_present` and records
  `marked_configured_untested=true` for the audit trail.
- Studio renders **"Mark Configured"** button (instead of Test) for
  the affected providers. Confirm dialog spells out the trust
  tradeoff.

### #4 — Dynamic VAULT_ALLOWLIST from module registry

Was: 11 first-party providers hardcoded inside a request handler.
Any published module (Zoho, HubSpot custom fields, etc.) got refused
with "provider not in vault allowlist" when the operator tried to
save credentials.

Now: `_VAULT_ALLOWLIST_BUILTIN` lives at module scope +
`_module_credential_specs()` merges `credential_spec` blocks from
loaded modules' manifests. Publishers declare in `module.json`:

```json
"credential_spec": {
  "provider":   "zoho",
  "category":   "crm",
  "name":       "Zoho CRM",
  "required":   ["client_id", "client_secret", "refresh_token", "domain"],
  "optional":   ["custom_module_prefix", "org_id"],
  "shape":      "dict",
  "risk":       "high",
  "read_write": "write"
}
```

Field filtering now keeps `required ∪ optional` — handler-needed
extras aren't stripped between UI form and vault (Shweta's specific
Zoho pain point).

## Regression sweep (7 bands, all green)

- **A/B/C/D**: `command_registry` — legacy SET input still works
  (5/5), new DICT input resolves 3/3 new states, `configured_providers`
  returns correct shape for both call signatures, new terminal
  status registered.
- **E**: v0.37 sandbox — Studio's real `os.makedirs` +
  `subprocess.check_output` untouched after install, handler ns still
  blocked.
- **F**: v0.39 for_each spend gate — 10/10 estimator test cases
  still pass.
- **G**: v0.36 multi-file module — CLI + engine `tree_manifest_bytes`
  byte-identical (244 bytes for the test fixture).
- **H**: v0.38 receipts.js — signature-unpack logic present.
- **I**: v0.35 module loader — uses `mdir` not `dirname(handler_path)`,
  zero references to the old wrong path.
- **J**: v0.40 features — all 4 items smoke-test cleanly (4 resolved_via
  states, module spec merge, mark_configured audit, Needs-verify label).

## Files changed

- `workbench/studio_server.py` — integrations_list unified status,
  _VAULT_ALLOWLIST_BUILTIN module-scope, _module_credential_specs
  merger, /api/integration/mark_configured endpoint, test_integration
  returns test_not_wired for NO_DRIVER + OAUTH_FLOW, /api/integration_test
  gates persist on non-test_not_wired
- `workbench/command_registry.py` — credential_present_untested
  terminal status, configured_providers dual-shape return,
  resolve_status accepts both set and dict
- `workbench/studio/scripts/views/integrations.js` — resolvedLine,
  testActionsHTML, TEST_NOT_WIRED_PROVIDERS, mark_configured
  click handler
- `workbench/studio/scripts/ui/components.js` — Needs-verify label
- `workbench/studio/scripts/api.js` — integrationMarkConfigured

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=67903b37c8a46590aedc461728b23e80ea8b4b5516f4973844a2c6f45177e612
```

## Credit

**Shweta** — one thread, four fixes across two releases (sandbox
in v0.37, this whole batch in v0.40). Best contributor of the
month.
