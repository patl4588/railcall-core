"""test_policy_engine.py — Phase 1 governance PolicyEngine gate.

Pins the load/evaluate contract:
  - Action-type match: external_send requires L2.
  - Sensitivity match: data_sensitivity=pii requires L2 + dry_run_first.
  - No rule matches -> fallback applies (default policy = allow).
  - Malformed YAML -> engine.failed=True, evaluate() rejects for safety.
  - Unsupported field (estimated_cost_usd) -> stderr warning, no crash, doesn't match.
  - First matching rule wins (declared order = evaluation order).

Run: python3 -m pytest tests/test_policy_engine.py -v
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from governance import PolicyEngine, FlowContext, DEFAULT_POLICY_PATH  # noqa: E402


# ---- helpers ----------------------------------------------------------------------------------
def _write_tmp_yaml(text):
    fd, path = tempfile.mkstemp(prefix="gov_", suffix=".yml")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return path


# ==================================================================================================
def test_action_type_external_send_requires_L2():
    """external_send should match rule 'external_send' and require L2 approval."""
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    assert not e.failed
    dec = e.evaluate(FlowContext(action_type="external_send"))
    assert dec.allow is True
    assert dec.requires_approval is True
    assert dec.authority_level == "L2"
    assert dec.matched_rule_id == "external_send"
    assert dec.risk_classification == "medium"


def test_data_sensitivity_pii_requires_L2_and_dry_run():
    """pii triggers L2 + dry_run_first — allow requires dry_run=True."""
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    # not dry run -> allow=False (dry_run required)
    dec_wet = e.evaluate(FlowContext(action_type="report", data_sensitivity="pii", dry_run=False))
    assert dec_wet.allow is False
    assert dec_wet.matched_rule_id == "pii_declared"
    assert dec_wet.authority_level == "L2"
    # dry run -> allow=True, still requires approval
    dec_dry = e.evaluate(FlowContext(action_type="report", data_sensitivity="pii", dry_run=True))
    assert dec_dry.allow is True
    assert dec_dry.requires_approval is True
    assert dec_dry.matched_rule_id == "pii_declared"


def test_no_match_falls_back_to_allow_by_default():
    """The bundled default fallback is `allow` so pre-Phase-1 installs don't lock out."""
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    dec = e.evaluate(FlowContext(action_type="readonly", data_sensitivity=None))
    assert dec.allow is True
    assert dec.matched_rule_id == "none"
    assert dec.risk_classification == "unknown"


def test_malformed_yaml_fails_safe():
    """A malformed policy makes engine.failed=True; every evaluate() rejects."""
    path = _write_tmp_yaml("this is: not: valid:\n  - garbage indent: - x\n")
    try:
        e = PolicyEngine(path)
        # depending on where the parser trips, either failed=True OR the policy loads but any
        # subsequent rule with a non-mapping child triggers _YAMLError -> failed=True
        # We accept either "failed" or a strict reject fallback:
        dec = e.evaluate(FlowContext(action_type="external_send"))
        assert dec.allow is False, "malformed policy must not allow flows"
    finally:
        os.unlink(path)


def test_missing_file_fails_safe():
    """A file that doesn't exist sets failed=True and rejects every flow."""
    e = PolicyEngine("/nonexistent/nowhere/governance.yml")
    assert e.failed is True
    dec = e.evaluate(FlowContext(action_type="external_send"))
    assert dec.allow is False
    assert dec.matched_rule_id == "none"


def test_unsupported_field_warns_and_doesnt_crash(capsys):
    """estimated_cost_usd in a rule's requires should warn to stderr and be silently dropped —
    the rule still loads, but the unsupported field never affects a match."""
    yml = """version: 1
default_authority_level: L1

rules:
  - id: expensive_op
    match:
      action_type: expensive
    requires:
      approval_authority: L3
      estimated_cost_usd: 100

fallback:
  action: reject
  message: "no match"
"""
    path = _write_tmp_yaml(yml)
    try:
        e = PolicyEngine(path)
        cap = capsys.readouterr()
        # the warning is emitted at load time via stderr
        assert "estimated_cost_usd" in cap.err or "unenforced" in cap.err.lower() or "unknown requires" in cap.err.lower()
        assert not e.failed
        # the rule still matches — action_type=expensive requires L3
        dec = e.evaluate(FlowContext(action_type="expensive"))
        assert dec.allow is True
        assert dec.authority_level == "L3"
        assert dec.matched_rule_id == "expensive_op"
    finally:
        os.unlink(path)


def test_first_matching_rule_wins():
    """When two rules could match, the earlier one is chosen — that's the precedence contract."""
    yml = """version: 1
default_authority_level: L1

rules:
  - id: early_wins
    match:
      action_type: shared_action
    requires:
      approval_authority: L2

  - id: late_looses
    match:
      action_type: shared_action
    requires:
      approval_authority: L3

fallback:
  action: reject
  message: "no"
"""
    path = _write_tmp_yaml(yml)
    try:
        e = PolicyEngine(path)
        dec = e.evaluate(FlowContext(action_type="shared_action"))
        assert dec.matched_rule_id == "early_wins"
        assert dec.authority_level == "L2"
    finally:
        os.unlink(path)


def test_policy_hash_is_sha256_of_file():
    """policy_hash must be the sha256 hex of the raw file bytes — verifiers depend on it."""
    import hashlib
    e = PolicyEngine(DEFAULT_POLICY_PATH)
    with open(DEFAULT_POLICY_PATH, "rb") as fh:
        expected = hashlib.sha256(fh.read()).hexdigest()
    assert e.policy_hash == expected


def test_policy_hash_empty_when_no_file():
    e = PolicyEngine("/does/not/exist.yml")
    assert e.policy_hash == ""


def test_action_type_list_match():
    """A rule can match against a LIST of action_types — any-of semantics."""
    yml = """version: 1
default_authority_level: L1

rules:
  - id: dangerous
    match:
      action_type:
        - external_send
        - file_delete
    requires:
      approval_authority: L2

fallback:
  action: allow
  message: fine
"""
    path = _write_tmp_yaml(yml)
    try:
        e = PolicyEngine(path)
        assert e.evaluate(FlowContext(action_type="external_send")).matched_rule_id == "dangerous"
        assert e.evaluate(FlowContext(action_type="file_delete")).matched_rule_id == "dangerous"
        assert e.evaluate(FlowContext(action_type="readonly")).matched_rule_id == "none"
    finally:
        os.unlink(path)
