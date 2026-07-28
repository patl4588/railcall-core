# station-v0.33

Real tarball change (first since v0.30). v0.31 and v0.32 were CLI-only.

## Headline

**Phase 4 module sandbox** — opt-in capability declaration for module
handlers, enforced at load time. Backwards-compatible with every existing
module.

Closes the trust gap the FAQ had been openly acknowledging: publisher-trust
answers *who* signed a module, but not *what* it needs to do. Now a
module can declare its capabilities upfront and the loader enforces them.

## Opt-in via manifest

Add a `requires` block to `module.json`:

```json
{
  "id": "acme/linear-tracker",
  "requires": {
    "network":           ["api.linear.app", "*.stripe.com"],
    "subprocess":        false,
    "filesystem_writes": ["/tmp/**"]
  }
}
```

- `network` — fnmatch-style host allowlist. Empty list = deny all egress.
- `subprocess` — `false` blocks subprocess/os.system/exec/spawn.
- `filesystem_writes` — glob allowlist for `open(w|a|x|+)` +
  os.remove/unlink/rename/replace/rmdir/mkdir/makedirs.

Reads are unrestricted (would be too disruptive; we're preventing
exfiltration + tampering, not enumeration).

Modules **without** `requires` continue to load unrestricted — no forced
migration.

## Enforcement

- Wrappers install into the handler namespace before `exec()`.
- Any capability violation raises `SandboxViolation`.
- A **malformed** `requires` block is a rejection reason. Silent-ignore
  would be worse than the current no-sandbox default because the
  operator thinks they're protected.

## Studio Modules tab

Each loaded module now shows a sandbox card:

- **No `requires` block** → visible amber "Sandbox · unrestricted" banner
  so operators aren't misled into thinking legacy modules are sandboxed.
- **Has `requires` block** → green card listing declared capabilities
  (network hosts, subprocess allowed/blocked, filesystem write globs).

## Honest scope

Not container-strong. Documented in the module docstring and the FAQ:

- `import ctypes; libc.system(...)` bypasses subprocess wrap.
- `import _socket; _socket.socket().connect(...)` skips urllib wrap.
- Read isn't restricted.

Sufficient for the ~99% class of "AI-drafted module tried to shell out"
+ "module quietly started talking to a domain it didn't announce."
Publisher-trust + signature-verify remain the primary defenses.

## Files in this tarball changed

- `workbench/module_sandbox.py` — NEW (~330 lines stdlib-only)
- `workbench/studio_server.py` — wire install_restrictions into
  `_load_modules` before handler exec; add `sandbox` field to loaded entry
- `workbench/studio/scripts/views/modules.js` — add `_sandboxCard(m)`
  renderer with the amber / green states

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=2e2ae2d088f2743923ba6ce0d2e8b27cb15d471cee5b3ba38d63ff719c07e6b7
```

## Upgrade path

Nothing to do. Existing modules keep running exactly as before.
Add a `requires` block to any module you'd like to gate.
