"""governance — RailCall Phase 1 policy engine + receipt-v2 governance blocks.

Public surface:
    PolicyEngine       — load governance.yml, evaluate a FlowContext, produce a Decision.
    FlowContext        — the (action_type, data_sensitivity, dry_run) tuple the CLI passes in.
    Decision           — allow / requires_approval / authority_level / matched_rule_id / risk.
    GovernancePolicy   — parsed policy tree (rules + fallback).
    PolicyRule         — one rule with match + requires.
    PolicyFallback     — action to take when nothing matched.
    DEFAULT_POLICY_PATH — path to the packaged safe-default governance.yml.

The engine NEVER raises out of load/evaluate — a missing or malformed policy sets
`failed = True` and makes every subsequent evaluate() reject. That's the safe-fail
contract Phase 1 depends on.
"""
from .policy_schema import (
    Decision,
    FlowContext,
    GovernancePolicy,
    PolicyFallback,
    PolicyRule,
)
from .policy_engine import DEFAULT_POLICY_PATH, PolicyEngine

__all__ = [
    "Decision",
    "FlowContext",
    "GovernancePolicy",
    "PolicyFallback",
    "PolicyRule",
    "PolicyEngine",
    "DEFAULT_POLICY_PATH",
]
