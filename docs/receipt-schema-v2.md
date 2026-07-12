# RailCall Receipt Schema — v2 (Phase 1)

## Overview

The **v2 receipt** layers three new top-level blocks (`flow`, `governance`, `execution`) plus a `receipt_version` tag on top of the existing v1 receipts. The change is **strictly additive**: every field a v1 receipt carries is still present, still signed, and still verifies with the exact same `receipt_signer.verify_payload(payload, signature, public_key_hex)` call — because the signer is payload-agnostic (it canonical-serializes whatever dict you hand it).

Files that participate:
- Emitters — `railcall_cli.py` (audit/build/interpret) and `railcall_companion_daemon.py` (/compile, /interpret)
- Verifier — `receipt_signer.py` (unchanged)
- Policy — `governance/policy_engine.py`, `governance/policy_schema.py`, `governance/receipt_v2.py`
- Default policy — `governance/defaults/governance.default.yml`

## Wire shape

```json
{
  "schema": "railcall_audit_receipt.v1",
  "ran_at": "2026-07-12T10:00:00",
  "network_audit": { "external_sockets_open": 0 },
  "result": "audited",

  "receipt_version": "v2",

  "flow": {
    "name": "audit",
    "action_type": "audit",
    "dry_run": true
  },

  "governance": {
    "policy_ref": "external_send",
    "policy_hash": "ff56072e81ed4908...",
    "approval_chain": [
      {
        "approver_pubkey": "9f2b...",
        "approver_authority_level": "L2",
        "approved_at": "2026-07-12T10:00:00Z",
        "auth_method": "byok_signature"
      }
    ],
    "risk_classification": "medium",
    "irreversible": true
  },

  "execution": {
    "input_sha256": "sha256:abc...",
    "output_sha256": "",
    "duration_ms": 42,
    "exit_code": 0
  },

  "signer_alg": "ed25519",
  "public_key_hex": "9f2b...",
  "signature_hex": "e6..."
}
```

## Field semantics

### `receipt_version`

Always the string `"v2"` when the v2 blocks are present. Absent from v1 receipts.

### `flow`

The identity of the flow that produced this receipt.

| Field         | Type   | Notes                                                                                       |
| ------------- | ------ | ------------------------------------------------------------------------------------------- |
| `name`        | string | Human name of the flow. **Omitted** when the emitter has none — never a placeholder.        |
| `action_type` | string | Machine-readable primitive (`build`, `audit`, `external_send`, ...). Omitted when unknown.  |
| `dry_run`     | bool   | Whether this run was a dry-run. Always present.                                             |

### `governance`

What the policy engine decided and (if applicable) who approved.

| Field                  | Type      | Notes                                                                                                                                                                                                                                                                     |
| ---------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `policy_ref`           | string    | Matched rule id, or `"none"` when the fallback applied.                                                                                                                                                                                                                   |
| `policy_hash`          | string    | `sha256(governance.yml file bytes)` — hex, or `""` when no policy file was loaded.                                                                                                                                                                                        |
| `approval_chain`       | list      | Populated only when an approval **actually occurred**. Empty (`[]`) for dry-runs, L1 auto-approve, and unmatched-fallback-allow flows.                                                                                                                                     |
| `risk_classification`  | string    | Derived directly from the matched rule's authority: `L3 → high`, `L2 → medium`, `L1 → low`, no match → `unknown`.                                                                                                                                                          |
| `irreversible`         | bool      | `true` for `external_send`, `file_delete`, `database_write`; `false` otherwise.                                                                                                                                                                                           |

Each entry in `approval_chain`:

| Field                       | Type   | Notes                                                                                        |
| --------------------------- | ------ | -------------------------------------------------------------------------------------------- |
| `approver_pubkey`           | string | Ed25519 public key hex, derived from the BYOK vault (`~/.railcall/keys.local.json`). NEVER empty. |
| `approver_authority_level`  | string | One of `L1`, `L2`, `L3`.                                                                     |
| `approved_at`               | string | ISO8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`).                                                        |
| `auth_method`               | string | Currently only `"byok_signature"` — expands when new methods ship.                            |

### `execution`

Post-run measurements.

| Field           | Type   | Notes                                                                                             |
| --------------- | ------ | ------------------------------------------------------------------------------------------------- |
| `input_sha256`  | string | `sha256:hex` of the input, or `""` when not applicable.                                           |
| `output_sha256` | string | Same, but for the output.                                                                         |
| `duration_ms`   | int    | Wall-clock milliseconds the flow took.                                                            |
| `exit_code`     | int    | Zero on success; nonzero when the primitive failed.                                               |

## Reserved fields (NOT emitted in Phase 1)

The following field names **must not appear** in a v2 receipt until the corresponding subsystems ship. Emitters MUST omit them entirely; verifiers should treat their presence as evidence of a forward-incompatible emitter (not a Phase 1 receipt).

- **`components`** — reserved. The component registry does not exist yet; emitters MUST omit this key until the component registry ships. Any `components` block found in a Phase 1 receipt is invalid.
- **`approver_identity`** — reserved. No identity-binding subsystem exists in Phase 1; approvals are attributed by BYOK pubkey only (via `approver_pubkey`).
- **`approver_role`** — reserved for the same reason as `approver_identity`.

## Backward compatibility

A v1 receipt (one **without** `receipt_version`) is signed and verified by the exact same call path as a v2 receipt, because `receipt_signer.py` is intentionally **payload-agnostic**: it canonical-serializes the entire dict passed to it (RFC 8785–style sorted-keys / tight-separators) and signs those bytes. The verifier does the same, so any well-formed JSON dict verifies as long as the canonical bytes match.

Concretely:

1. **Reading an old v1 receipt in a Phase 1 install**: works. The signer strips the three signer fields (`signer_alg`, `public_key_hex`, `signature_hex`), canonical-serializes the body, and checks the signature. The v2 blocks are absent, so the canonical body is exactly what was signed under v1.
2. **Reading a new v2 receipt in a pre-Phase-1 install**: works too — the signer still verifies, because the additional fields are present in both the input to sign() and the input to verify(). Pre-Phase-1 code that consumes the payload as JSON just sees three extra keys.

This is exercised by `tests/test_receipt_schema_v2.py::test_v1_receipt_still_verifies` and `::test_receipt_signer_is_payload_agnostic_across_versions`.

## Fields the policy engine does NOT match on (Phase 1)

The following YAML fields are recognized-but-ignored by `PolicyEngine`. Rules that mention them get one stderr warning at load time (`policy_engine: rule <id> uses unenforced field <name>; will not match in Phase 1`) and are otherwise loaded as if the field were absent:

- `estimated_cost_usd`
- `two_person_approval`
- `data_sensitivity` **when auto-detected**. The engine only matches on the `data_sensitivity` the CLI declares via `--data-sensitivity`; there is no auto-detection heuristic in Phase 1.

## CLI integration

Three commands gained a `--data-sensitivity` flag (one of `none|pii|phi|financial|secret`, default `none`):

- `railcall audit <file.csv> [--data-sensitivity …]`
- `railcall build [csv] [--data-sensitivity …]`
- `railcall interpret "<prompt>" [--data-sensitivity …]`

Each invocation:

1. Builds a `FlowContext(action_type, data_sensitivity, dry_run)`.
2. Calls `POLICY_ENGINE.evaluate(ctx)` — loaded once at CLI startup from `~/.railcall/governance.yml`, or `governance/defaults/governance.default.yml` if the user's file is missing.
3. On `Decision.allow == False`, prints a clear panel to stderr and exits 1 **before any compute or disk write**.
4. On `Decision.allow == True`, executes the flow. The receipt is grafted with v2 blocks before signing so the signature covers them.

## Daemon integration

The daemon loads the same `PolicyEngine` at startup (`_load_policy_engine()` in `railcall_companion_daemon.py`) and logs its state to stderr. Every `POST /compile` and `POST /interpret` request runs the policy gate — payloads may supply `data_sensitivity`, `dry_run`, and `action_type`. A rejected policy returns HTTP 403 with `{"status": "policy_rejected", "policy_ref": ..., "message": ...}`, and the receipt is never written.

`GET /governed` includes a `policy_engine` annotation on its response:
```json
{ "policy_engine": { "loaded": true, "policy_hash": "ff56...", "policy_path": "/…/governance.default.yml" } }
```
