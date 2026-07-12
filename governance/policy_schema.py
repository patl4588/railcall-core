"""policy_schema.py — pure-stdlib dataclasses that describe a RailCall governance policy.

No pydantic, no third-party validators — the policy is small and hand-audited, so a dataclass
with a from_dict() constructor is the honest way to type-check it. Anything that arrives on the
wire (governance.yml -> dict -> from_dict) is either a well-formed policy tree, or the engine
flips to `failed` and rejects everything: no half-parsed rules ever match.

Field semantics that are load-bearing for the receipt v2 governance block:

  PolicyRule.match.action_type / data_sensitivity  — str | list[str] | None. None means "don't
      constrain on this axis"; a list means "match ANY of these values". First matching rule wins.
  PolicyRule.requires.approval_authority           — one of L1|L2|L3 or None. Drives Decision's
      authority_level AND the receipt's risk_classification (L3=high, L2=medium, L1=low).
  PolicyRule.requires.dry_run_first                — bool. If true and the flow is NOT dry-run,
      the CLI must reject.

  PolicyFallback.action                            — "allow" | "reject". Applied when no rule matches.
      The safe default in defaults/governance.default.yml is "allow" so existing installs without a
      governance.yml don't get locked out — but a malformed policy still fails safe (reject all).

  FlowContext                                      — what the CLI passes in per invocation.
  Decision                                         — what evaluate() hands back to the CLI.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

# ---- discriminated string enums (kept as bare strings so YAML loads cleanly) -------------------
_VALID_AUTHORITY = {"L1", "L2", "L3"}
_VALID_FALLBACK_ACTION = {"allow", "reject"}
_VALID_RISK = {"low", "medium", "high", "unknown"}


@dataclass
class PolicyRuleMatch:
    """Match predicate on a rule. Either axis can be a single string, a list, or None (don't care).
    Matching is case-sensitive; the CLI is responsible for passing lower-cased tokens."""

    action_type: Optional[Union[str, List[str]]] = None
    data_sensitivity: Optional[Union[str, List[str]]] = None

    def matches(self, action_type: Optional[str], data_sensitivity: Optional[str]) -> bool:
        """Return True iff EVERY constrained axis matches the incoming FlowContext. An unconstrained
        axis (None) never blocks a match — it's a wildcard."""
        if self.action_type is not None:
            allowed = self.action_type if isinstance(self.action_type, list) else [self.action_type]
            if action_type not in allowed:
                return False
        if self.data_sensitivity is not None:
            allowed = self.data_sensitivity if isinstance(self.data_sensitivity, list) else [self.data_sensitivity]
            if data_sensitivity not in allowed:
                return False
        return True


@dataclass
class PolicyRuleRequires:
    """What a matched rule REQUIRES the flow to satisfy. authority_level None means the flow can
    proceed at the default authority level; dry_run_first True means the flow must be a dry-run."""

    approval_authority: Optional[str] = None    # L1 | L2 | L3 | None
    dry_run_first: bool = False


@dataclass
class PolicyRule:
    """A single named rule: id + match + requires. Rules are evaluated in file order; first hit wins."""

    id: str
    match: PolicyRuleMatch = field(default_factory=PolicyRuleMatch)
    requires: PolicyRuleRequires = field(default_factory=PolicyRuleRequires)


@dataclass
class PolicyFallback:
    """What to do when NO rule matches. action must be 'allow' or 'reject'; message is user-facing."""

    action: str = "reject"
    message: str = "No policy rule matched"


@dataclass
class GovernancePolicy:
    """The parsed governance.yml tree. `version` is opaque (bumped when the schema changes);
    `default_authority_level` is what an unmatched-but-allowed flow runs at."""

    version: int = 1
    default_authority_level: str = "L1"
    rules: List[PolicyRule] = field(default_factory=list)
    fallback: PolicyFallback = field(default_factory=PolicyFallback)


@dataclass
class FlowContext:
    """What the CLI passes into evaluate() per flow invocation. `data_sensitivity` is user-DECLARED
    only — the engine deliberately never auto-detects PII/PHI/secrets (see the Phase 1 ABSOLUTE RULES:
    'never auto-detect')."""

    action_type: Optional[str] = None
    data_sensitivity: Optional[str] = None
    dry_run: bool = False


@dataclass
class Decision:
    """What evaluate() hands back. `allow=False` means the CLI must abort with a clear error;
    `requires_approval=True` means run the approval airlock; `authority_level` is what to record in the
    receipt's governance block; `matched_rule_id` is 'none' when no rule matched; `risk_classification`
    is derived directly from the matched rule's authority (L3=high / L2=medium / L1=low / no-match=unknown)."""

    allow: bool
    requires_approval: bool = False
    authority_level: Optional[str] = None
    matched_rule_id: str = "none"
    risk_classification: str = "unknown"
    message: str = ""
    dry_run_required: bool = False


# ---- validators (called by policy_engine at load time) -----------------------------------------
def _validate_authority(v: Any) -> Optional[str]:
    """Return v if it's a valid authority level string, else None (rejected upstream)."""
    if v is None:
        return None
    if isinstance(v, str) and v in _VALID_AUTHORITY:
        return v
    return None


def _validate_fallback_action(v: Any) -> str:
    """Fallback action must be 'allow' or 'reject'; anything else collapses to 'reject' (safe)."""
    if isinstance(v, str) and v in _VALID_FALLBACK_ACTION:
        return v
    return "reject"


def risk_from_authority(auth: Optional[str]) -> str:
    """Map an authority level onto the receipt's risk_classification.
    L3 = high, L2 = medium, L1 = low, unknown otherwise."""
    if auth == "L3":
        return "high"
    if auth == "L2":
        return "medium"
    if auth == "L1":
        return "low"
    return "unknown"
