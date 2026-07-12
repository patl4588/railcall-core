"""policy_engine.py — load governance.yml, evaluate FlowContexts, produce Decisions.

Design contract (matches Phase 1 spec):
  - `__init__(policy_path)` never raises. A missing OR malformed file sets `self.failed = True`
    and every evaluate() call after that returns `Decision(allow=False, ...)` — safe fail.
  - `evaluate(flow_context)` matches rules in file order, action_type first then data_sensitivity.
    First match wins. If nothing matches, apply the fallback (default: reject).
  - `policy_hash` is the sha256 hex of the raw governance.yml bytes on disk (or "" if no file).
  - Fields the spec explicitly reserves (estimated_cost_usd, two_person_approval, auto data_sensitivity)
    are NOT matched on. Rules that mention them get a stderr warning at load time and are still
    loaded — just with those keys ignored — so an aspirational governance.yml doesn't crash Phase 1.

YAML parsing is deliberately in-house. RailCall's requirements.txt does NOT ship PyYAML, and the
governance DSL is a tiny subset of YAML (key: value, lists via '-', two-space indent). A hand-rolled
parser keeps the "install stays a 2-file curl|bash" promise the CLI header calls out. The parser
handles:
  - dict / list nesting via indentation
  - inline scalars: strings (bare, single/double quoted), ints, bools (true/false), null (None)
  - '#' line comments and trailing whitespace
It intentionally REFUSES anything more exotic (flow-style {}, [], anchors, multi-doc '---'):
Phase 1 governance rules don't need them, and silently accepting them would let a broken policy
"parse" into something the engine can't reason about.
"""
import hashlib
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from .policy_schema import (
    Decision,
    FlowContext,
    GovernancePolicy,
    PolicyFallback,
    PolicyRule,
    PolicyRuleMatch,
    PolicyRuleRequires,
    _validate_authority,
    _validate_fallback_action,
    risk_from_authority,
)

# path to the packaged safe-default policy the CLI/daemon fall back to when
# ~/.railcall/governance.yml does not exist.
DEFAULT_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "defaults", "governance.default.yml"
)

# Fields we accept in a rule's `match` / `requires` blocks. Anything else in `requires` is
# flagged at load time as "unenforced in Phase 1" and dropped.
_SUPPORTED_MATCH_FIELDS = {"action_type", "data_sensitivity"}
_SUPPORTED_REQUIRES_FIELDS = {"approval_authority", "dry_run_first"}
# Fields the Phase 1 spec explicitly calls out as reserved / not enforced yet.
_RESERVED_FIELDS_WARN = {"estimated_cost_usd", "two_person_approval", "data_sensitivity_auto"}


# ================================================================================================
# Minimal YAML parser — enough for the governance DSL, deliberately no more.
# ================================================================================================
class _YAMLError(Exception):
    """Raised when the minimal parser sees something outside the governance DSL. Caller catches
    this and flips the engine to `failed`."""


def _strip_comment(line: str) -> str:
    """Drop everything from an unquoted '#' onward. Preserve '#' inside quoted strings."""
    out = []
    in_single = in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(raw: str) -> Any:
    """Parse a YAML scalar into a Python value. Recognizes int, bool, null, and quoted/bare strings."""
    s = raw.strip()
    if s == "":
        return None
    if s.lower() in ("null", "~"):
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # quoted string
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    # int
    try:
        return int(s)
    except ValueError:
        pass
    # float
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _indent_of(line: str) -> int:
    """Number of leading spaces. Tabs are rejected — the DSL is two-space-indented only."""
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            raise _YAMLError("tabs are not allowed in indentation")
        else:
            break
    return n


def _tokenize(text: str) -> List[Tuple[int, str]]:
    """Return a list of (indent, stripped-line) tuples, skipping blank/comment-only lines."""
    tokens: List[Tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        cleaned = _strip_comment(raw)
        if not cleaned.strip():
            continue
        ind = _indent_of(cleaned)
        tokens.append((ind, cleaned[ind:]))
    return tokens


def _parse_block(tokens: List[Tuple[int, str]], pos: int, base_indent: int) -> Tuple[Any, int]:
    """Parse the block starting at tokens[pos]. Returns (value, new_pos). base_indent is the indent
    at which the *containing* block sits; every child must be indented STRICTLY more than that."""
    if pos >= len(tokens):
        return None, pos
    ind, line = tokens[pos]
    if ind < base_indent:
        return None, pos

    # ---- list block: every line at this indent starts with "- "
    if line.startswith("- "):
        items: List[Any] = []
        list_indent = ind
        while pos < len(tokens):
            ind2, line2 = tokens[pos]
            if ind2 < list_indent or not line2.startswith("- "):
                break
            item_body = line2[2:]
            # A "- key: val" starts an inline dict — normalize by injecting a virtual line
            if ":" in item_body and not (item_body.startswith("'") or item_body.startswith('"')):
                # push a virtual token: same-indent (list_indent+2) "key: rest", then recurse into a dict block.
                virtual: List[Tuple[int, str]] = [(list_indent + 2, item_body)]
                # gather following lines that belong to this list item (indent > list_indent)
                pos += 1
                while pos < len(tokens):
                    i3, l3 = tokens[pos]
                    if i3 <= list_indent:
                        break
                    virtual.append((i3, l3))
                    pos += 1
                sub, _ = _parse_block(virtual, 0, list_indent + 2)
                items.append(sub)
            else:
                items.append(_scalar(item_body))
                pos += 1
        return items, pos

    # ---- dict block: lines of form "key: value" or "key:" followed by an indented block
    result: Dict[str, Any] = {}
    dict_indent = ind
    while pos < len(tokens):
        ind2, line2 = tokens[pos]
        if ind2 != dict_indent:
            break
        if line2.startswith("- "):
            # list-in-dict-position is a syntax error unless the caller already peeled it off
            break
        if ":" not in line2:
            raise _YAMLError("expected 'key: value' or 'key:' at %r" % line2)
        key, _, rest = line2.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # nested block on the next lines
            pos += 1
            if pos < len(tokens) and tokens[pos][0] > dict_indent:
                sub, pos = _parse_block(tokens, pos, tokens[pos][0])
                result[key] = sub
            else:
                result[key] = None
        else:
            result[key] = _scalar(rest)
            pos += 1
    return result, pos


def _parse_yaml(text: str) -> Dict[str, Any]:
    """Parse a governance.yml document into a plain nested-dict tree.
    Raises _YAMLError on anything outside the tiny governance DSL."""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    if tokens[0][0] != 0:
        raise _YAMLError("top-level content must start at indent 0")
    doc, _ = _parse_block(tokens, 0, 0)
    if not isinstance(doc, dict):
        raise _YAMLError("top-level of governance.yml must be a mapping")
    return doc


# ================================================================================================
# Policy engine
# ================================================================================================
class PolicyEngine:
    """Load and evaluate a governance policy. Never raises. Fails safe (reject-all) on any error."""

    def __init__(self, policy_path: Optional[str] = None):
        """Load and parse `policy_path`. On any error (missing file, malformed YAML, bad shape),
        emit a stderr line and set self.failed=True so every evaluate() rejects."""
        self.policy_path: Optional[str] = policy_path
        self.policy: Optional[GovernancePolicy] = None
        self.failed: bool = False
        self._raw_bytes: bytes = b""
        self._policy_hash: str = ""

        if not policy_path:
            self.failed = True
            self._warn("no policy path provided — engine is in fail-closed mode")
            return
        if not os.path.exists(policy_path):
            self.failed = True
            self._warn("policy file not found: %s — engine is in fail-closed mode" % policy_path)
            return
        try:
            with open(policy_path, "rb") as fh:
                self._raw_bytes = fh.read()
            self._policy_hash = hashlib.sha256(self._raw_bytes).hexdigest()
            text = self._raw_bytes.decode("utf-8")
            tree = _parse_yaml(text)
            self.policy = self._build_policy(tree)
        except (_YAMLError, ValueError, UnicodeDecodeError) as e:
            self.failed = True
            self.policy = None
            self._warn("failed to parse %s (%s) — engine is in fail-closed mode" % (policy_path, e))
        except Exception as e:  # noqa: BLE001 — never raise out of __init__
            self.failed = True
            self.policy = None
            self._warn("unexpected error loading %s (%s: %s) — engine is in fail-closed mode"
                       % (policy_path, type(e).__name__, e))

    # ---- properties -----------------------------------------------------------------------------
    @property
    def policy_hash(self) -> str:
        """sha256 hex of the raw governance.yml bytes on disk, or '' if no file was loaded."""
        return self._policy_hash

    # ---- public API -----------------------------------------------------------------------------
    def evaluate(self, flow_context: FlowContext) -> Decision:
        """Match rules in order; first hit wins. Fallback applies when no rule matches. Never raises."""
        if self.failed or self.policy is None:
            return Decision(
                allow=False,
                requires_approval=False,
                authority_level=None,
                matched_rule_id="none",
                risk_classification="unknown",
                message="policy engine failed to load — rejecting for safety",
            )
        for rule in self.policy.rules:
            if rule.match.matches(flow_context.action_type, flow_context.data_sensitivity):
                auth = rule.requires.approval_authority
                needs_approval = auth in ("L2", "L3")
                # dry_run_first: the flow is only allowed when it's actually a dry run
                dry_required = bool(rule.requires.dry_run_first)
                allow = True
                message = "matched rule %s" % rule.id
                if dry_required and not flow_context.dry_run:
                    allow = False
                    message = ("rule %s requires a dry-run first; re-run with --dry-run" % rule.id)
                return Decision(
                    allow=allow,
                    requires_approval=needs_approval,
                    authority_level=auth or self.policy.default_authority_level,
                    matched_rule_id=rule.id,
                    risk_classification=risk_from_authority(auth),
                    message=message,
                    dry_run_required=dry_required,
                )
        # no match → fallback
        fb = self.policy.fallback
        if fb.action == "allow":
            return Decision(
                allow=True,
                requires_approval=False,
                authority_level=self.policy.default_authority_level,
                matched_rule_id="none",
                risk_classification="unknown",
                message=fb.message or "no rule matched — fallback allow",
            )
        return Decision(
            allow=False,
            requires_approval=False,
            authority_level=None,
            matched_rule_id="none",
            risk_classification="unknown",
            message=fb.message or "no rule matched — fallback reject",
        )

    # ---- internals ------------------------------------------------------------------------------
    def _warn(self, msg: str) -> None:
        """One-line stderr diagnostic. Never a stack trace — operators grep for 'policy_engine'."""
        try:
            sys.stderr.write("policy_engine: %s\n" % msg)
            sys.stderr.flush()
        except Exception:
            pass

    def _build_policy(self, tree: Dict[str, Any]) -> GovernancePolicy:
        """Turn the raw parsed dict into a validated GovernancePolicy dataclass.
        Emits warnings for reserved / unsupported fields but does not crash on them."""
        version = tree.get("version", 1)
        try:
            version = int(version)
        except (TypeError, ValueError):
            version = 1
        default_auth = _validate_authority(tree.get("default_authority_level")) or "L1"

        rules_raw = tree.get("rules") or []
        if not isinstance(rules_raw, list):
            raise _YAMLError("'rules' must be a list")
        rules: List[PolicyRule] = []
        for r in rules_raw:
            if not isinstance(r, dict):
                raise _YAMLError("each rule must be a mapping")
            rid = str(r.get("id") or "unnamed")
            match_raw = r.get("match") or {}
            req_raw = r.get("requires") or {}
            if not isinstance(match_raw, dict):
                raise _YAMLError("rule %s: 'match' must be a mapping" % rid)
            if not isinstance(req_raw, dict):
                raise _YAMLError("rule %s: 'requires' must be a mapping" % rid)
            # warn on reserved fields anywhere in match/requires
            for k in list(match_raw.keys()) + list(req_raw.keys()):
                if k in _RESERVED_FIELDS_WARN:
                    self._warn("rule %s uses unenforced field %s; will not match in Phase 1" % (rid, k))
            # warn on unknown-but-not-reserved fields; drop them
            for k in match_raw.keys():
                if k not in _SUPPORTED_MATCH_FIELDS and k not in _RESERVED_FIELDS_WARN:
                    self._warn("rule %s: unknown match field %r ignored in Phase 1" % (rid, k))
            for k in req_raw.keys():
                if k not in _SUPPORTED_REQUIRES_FIELDS and k not in _RESERVED_FIELDS_WARN:
                    self._warn("rule %s: unknown requires field %r ignored in Phase 1" % (rid, k))

            match = PolicyRuleMatch(
                action_type=match_raw.get("action_type"),
                data_sensitivity=match_raw.get("data_sensitivity"),
            )
            requires = PolicyRuleRequires(
                approval_authority=_validate_authority(req_raw.get("approval_authority")),
                dry_run_first=bool(req_raw.get("dry_run_first", False)),
            )
            rules.append(PolicyRule(id=rid, match=match, requires=requires))

        fb_raw = tree.get("fallback") or {}
        if not isinstance(fb_raw, dict):
            raise _YAMLError("'fallback' must be a mapping")
        fallback = PolicyFallback(
            action=_validate_fallback_action(fb_raw.get("action", "reject")),
            message=str(fb_raw.get("message") or "No policy rule matched"),
        )
        return GovernancePolicy(
            version=version,
            default_authority_level=default_auth,
            rules=rules,
            fallback=fallback,
        )
