"""defaults — packaged safe-default governance.yml the CLI/daemon fall back to.

If ~/.railcall/governance.yml is missing, PolicyEngine loads defaults/governance.default.yml
(pointed at by governance.DEFAULT_POLICY_PATH). The default fallback action is 'allow' so an
existing install without a governance.yml still runs; a MALFORMED user policy still fails safe
(reject all) because that's a real error, not an unopinionated install.
"""
