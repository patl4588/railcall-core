"""test_receipt_schema_v2.py — Phase 1 v2 receipt schema gate.

Pins the additive-schema contract:
  - v1 receipts still verify (receipt_signer is payload-agnostic — signing/verify know nothing
    about the schema, they canonical-serialize whatever dict you hand them).
  - v2 receipts (with flow + governance + execution blocks) verify against the same signer.
  - An emitter that mints a v2-tagged receipt MUST include the governance block; the shape
    verifier here treats a missing governance block on a v2 receipt as invalid.
  - approver_pubkey is non-empty when approval_chain is populated (no placeholder pubkeys).
  - `components` block is absent from any Phase 1 v2 receipt (component registry not shipped).

Run: python3 -m pytest tests/test_receipt_schema_v2.py -v
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import receipt_signer  # noqa: E402
from governance import FlowContext, PolicyEngine, DEFAULT_POLICY_PATH  # noqa: E402
from governance import receipt_v2 as rv2  # noqa: E402


# ---- helpers ----------------------------------------------------------------------------------
def _new_seed_hex():
    """Fresh 32-byte Ed25519 seed for signing (never touches the vault)."""
    return os.urandom(32).hex()


def _shape_ok_v2(receipt):
    """Return (ok, reason). A v2 receipt MUST carry flow + governance + execution + receipt_version.
    Absent components block is REQUIRED in Phase 1 (component registry doesn't exist yet)."""
    if receipt.get("receipt_version") != "v2":
        return False, "receipt_version != 'v2'"
    if "governance" not in receipt:
        return False, "missing governance block"
    if "flow" not in receipt:
        return False, "missing flow block"
    if "execution" not in receipt:
        return False, "missing execution block"
    if "components" in receipt:
        return False, "Phase 1 forbids components block"
    if "approver_identity" in receipt.get("governance", {}):
        return False, "Phase 1 forbids approver_identity"
    return True, "ok"


# ==================================================================================================
def test_v1_receipt_still_verifies():
    """A minimal v1-shaped receipt round-trips through receipt_signer unchanged. This is the
    backward-compat guarantee: existing v1 receipts on disk MUST still verify after Phase 1."""
    seed = _new_seed_hex()
    pub = receipt_signer.public_key_hex(seed)
    receipt = {
        "schema": "railcall_audit_receipt.v1",
        "ran_at": "2026-01-01T00:00:00",
        "result": "audited",
        "network_audit": {"external_sockets_open": 0},
    }
    sig = receipt_signer.sign_payload(receipt, seed)
    assert receipt_signer.verify_payload(receipt, sig, pub) is True


def test_v2_receipt_round_trips():
    """A full v2 receipt (v1 fields + flow/governance/execution + receipt_version) signs + verifies."""
    seed = _new_seed_hex()
    pub = receipt_signer.public_key_hex(seed)
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    decision = e.evaluate(FlowContext(action_type="external_send", data_sensitivity=None, dry_run=False))
    fb = rv2.build_flow_block(FlowContext(action_type="external_send", dry_run=False), name="build")
    approval = rv2.build_approval_entry(
        approver_pubkey=pub, approver_authority_level="L2",
        approved_at="2026-01-01T00:00:00Z", auth_method="byok_signature",
    )
    gb = rv2.build_governance_block(decision, e.policy_hash, [approval], action_type="external_send")
    eb = rv2.build_execution_block(input_sha256="sha256:aa", output_sha256="", duration_ms=12, exit_code=0)

    receipt = {
        "schema": "railcall_audit_receipt.v1",
        "ran_at": "2026-01-01T00:00:00",
        "result": "audited",
    }
    rv2.graft_v2_blocks(receipt, fb, gb, eb)
    ok, reason = _shape_ok_v2(receipt)
    assert ok, reason
    sig = receipt_signer.sign_payload(receipt, seed)
    assert receipt_signer.verify_payload(receipt, sig, pub) is True


def test_v2_receipt_without_governance_fails_shape_validation():
    """A receipt tagged v2 but missing the governance block is invalid by our shape gate."""
    bad = {"receipt_version": "v2", "flow": {}, "execution": {}}
    ok, reason = _shape_ok_v2(bad)
    assert not ok
    assert "governance" in reason


def test_approver_pubkey_nonempty_when_approval_chain_populated():
    """rv2.build_approval_entry MUST refuse an empty pubkey — no placeholders in Phase 1."""
    import pytest
    with pytest.raises(ValueError):
        rv2.build_approval_entry(approver_pubkey="", approver_authority_level="L2",
                                 approved_at="2026-01-01T00:00:00Z")


def test_components_block_absent_from_v2_receipts():
    """A Phase 1 v2 receipt MUST NOT contain a components block."""
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    decision = e.evaluate(FlowContext(action_type="build"))
    fb = rv2.build_flow_block(FlowContext(action_type="build"), name="build")
    gb = rv2.build_governance_block(decision, e.policy_hash, [], action_type="build")
    eb = rv2.build_execution_block()
    receipt = {}
    rv2.graft_v2_blocks(receipt, fb, gb, eb)
    assert "components" not in receipt
    assert "approver_identity" not in receipt.get("governance", {})
    assert "approver_role" not in receipt.get("governance", {})


def test_irreversible_classification():
    """external_send / file_delete / database_write are irreversible; everything else is not."""
    for act in ("external_send", "file_delete", "database_write"):
        assert rv2.is_irreversible(act) is True
    for act in ("build", "audit", "interpret", "read", None):
        assert rv2.is_irreversible(act) is False


def test_v2_receipt_empty_approval_chain_for_dry_run():
    """Dry-run flows never have an approval yet — approval_chain must be []."""
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    decision = e.evaluate(FlowContext(action_type="build", dry_run=True))
    gb = rv2.build_governance_block(decision, e.policy_hash, [], action_type="build")
    assert gb["approval_chain"] == []


def test_v2_flow_block_omits_missing_primitives():
    """flow.name is omitted when the emitter has none; flow.action_type when there is none.
    That's the 'no aspirational fields' Phase 1 rule."""
    fb = rv2.build_flow_block(FlowContext(action_type=None, dry_run=False))
    assert "name" not in fb
    assert "action_type" not in fb
    assert fb["dry_run"] is False


def test_receipt_signer_is_payload_agnostic_across_versions():
    """The same seed should sign a v1 and a v2 receipt; both signatures verify with the same pubkey."""
    seed = _new_seed_hex()
    pub = receipt_signer.public_key_hex(seed)
    v1 = {"schema": "a.v1", "ran_at": "x"}
    v2 = {"schema": "a.v1", "ran_at": "x", "receipt_version": "v2",
          "flow": {"dry_run": True}, "governance": {"policy_ref": "none", "policy_hash": "",
                                                     "approval_chain": [],
                                                     "risk_classification": "unknown",
                                                     "irreversible": False},
          "execution": {"input_sha256": "", "output_sha256": "", "duration_ms": 0, "exit_code": 0}}
    for r in (v1, v2):
        sig = receipt_signer.sign_payload(r, seed)
        assert receipt_signer.verify_payload(r, sig, pub) is True
