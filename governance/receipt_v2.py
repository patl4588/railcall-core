"""receipt_v2.py — build the v2 governance / flow / execution blocks that get grafted onto a receipt.

The v2 receipt schema layers three NEW top-level blocks on top of whatever v1 fields the emitter
already writes. The emitter (CLI or daemon) is responsible for constructing everything else;
this module only guarantees the SHAPE of the three new blocks is consistent + honest.

Phase 1 ABSOLUTE RULES this module enforces:
  - No `components` block (component registry doesn't exist yet).
  - No `approver_identity` / `approver_role` (no identity binding yet).
  - Missing primitives ⇒ omit the field, never emit a placeholder.
  - `data_sensitivity` is USER-declared only; never auto-detected.

Shape emitted:

  {
    "receipt_version": "v2",
    "flow": {"name": ..., "action_type": ..., "dry_run": bool},
    "governance": {
      "policy_ref": "<rule id | 'none'>",
      "policy_hash": "<sha256 hex | ''>",
      "approval_chain": [ { approver_pubkey, approver_authority_level, approved_at, auth_method }, ...],
      "risk_classification": "low|medium|high|unknown",
      "irreversible": bool,
    },
    "execution": {"input_sha256": ..., "output_sha256": ..., "duration_ms": int, "exit_code": int},
  }
"""
from typing import Any, Dict, List, Optional

from .policy_schema import Decision, FlowContext

# actions where a mistake can't be undone by re-running — these show up in the receipt as
# irreversible=True regardless of the rule that matched.
_IRREVERSIBLE_ACTIONS = {"external_send", "file_delete", "database_write"}


def is_irreversible(action_type: Optional[str]) -> bool:
    """True iff `action_type` names an irreversible primitive. Anything else (including None) → False."""
    return isinstance(action_type, str) and action_type in _IRREVERSIBLE_ACTIONS


def build_flow_block(flow: FlowContext, name: Optional[str] = None) -> Dict[str, Any]:
    """The `flow` block: name (if the emitter knows one), action_type (if any), and dry_run.
    Fields with no primitive are omitted, not set to null — that's the "no aspirational fields" rule."""
    block: Dict[str, Any] = {"dry_run": bool(flow.dry_run)}
    if name:
        block["name"] = name
    if flow.action_type:
        block["action_type"] = flow.action_type
    return block


def build_governance_block(
    decision: Decision,
    policy_hash: str,
    approval_chain: Optional[List[Dict[str, Any]]] = None,
    action_type: Optional[str] = None,
) -> Dict[str, Any]:
    """The `governance` block. `approval_chain` is [] when no approval actually occurred (dry run,
    L1 auto-approve, unmatched fallback-allow). `policy_hash` is '' when no policy file was loaded."""
    return {
        "policy_ref": decision.matched_rule_id or "none",
        "policy_hash": policy_hash or "",
        "approval_chain": list(approval_chain or []),
        "risk_classification": decision.risk_classification or "unknown",
        "irreversible": is_irreversible(action_type),
    }


def build_execution_block(
    input_sha256: Optional[str] = None,
    output_sha256: Optional[str] = None,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
) -> Dict[str, Any]:
    """The `execution` block. Sha256 fields default to '' (not omitted — a v2 verifier expects the key).
    duration_ms/exit_code fall back to 0 for the same reason."""
    return {
        "input_sha256": input_sha256 or "",
        "output_sha256": output_sha256 or "",
        "duration_ms": int(duration_ms if duration_ms is not None else 0),
        "exit_code": int(exit_code if exit_code is not None else 0),
    }


def build_approval_entry(
    approver_pubkey: str,
    approver_authority_level: str,
    approved_at: str,
    auth_method: str = "byok_signature",
) -> Dict[str, Any]:
    """One entry in the governance.approval_chain. `approver_pubkey` MUST be a real hex pubkey
    (from the BYOK vault); this module refuses to insert an empty-string placeholder."""
    if not approver_pubkey:
        raise ValueError("approver_pubkey must be a non-empty hex string")
    if approver_authority_level not in ("L1", "L2", "L3"):
        raise ValueError("approver_authority_level must be one of L1|L2|L3")
    return {
        "approver_pubkey": approver_pubkey,
        "approver_authority_level": approver_authority_level,
        "approved_at": approved_at,
        "auth_method": auth_method,
    }


def graft_v2_blocks(
    receipt: Dict[str, Any],
    flow_block: Dict[str, Any],
    governance_block: Dict[str, Any],
    execution_block: Dict[str, Any],
) -> Dict[str, Any]:
    """Insert the v2 blocks into an existing receipt IN PLACE, tag receipt_version, and return it.
    Callers keep every v1 field they were already writing — this ONLY adds v2 fields, matching the
    "backward compat: v1 receipts still verify" guarantee in docs/receipt-schema-v2.md."""
    receipt["receipt_version"] = "v2"
    receipt["flow"] = flow_block
    receipt["governance"] = governance_block
    receipt["execution"] = execution_block
    return receipt
