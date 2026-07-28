# station-v0.37

Emergency single-fix cut. The Phase 4b sandbox from v0.33 was
poisoning Studio itself for anyone who published a module with a
`requires` block.

## What was broken

Shweta caught it and traced the exact code path:

    File "studio_server.py", line 6473, in _persist_receipt
      os.makedirs(rdir, exist_ok=True)
    File "module_sandbox.py", line 309, in _wrapped
      raise SandboxViolation
    SandboxViolation: module 'shweta/zoho-crm' tried
      os.makedirs('.../.railcall_workspace/receipts') — path not in
      filesystem_writes allowlist

Studio's own receipt writer was hitting the sandbox. Startup got
similarly hit through `webbrowser.register_standard_browsers` calling
`subprocess.check_output`.

## Root cause

Both `_install_subprocess_gate` and `_install_filesystem_gate` mutated
the shared stdlib module singletons:

    # subprocess gate
    import subprocess as _sp
    _sp.Popen = _refuse(...)              # ← process-wide singleton

    # filesystem gate
    import os as _os_write
    setattr(_os_write, name, _wrapped)    # ← process-wide singleton

Every subsequent `import subprocess` / `import os` in the ENTIRE Python
process (including Studio's own request handlers and startup code) got
the poisoned methods.

Impact: any published module that declared `requires` broke Studio
outright. Publishers routed around by dropping the block and showing
"SANDBOX · UNRESTRICTED", defeating the feature.

## v0.37 fix

Namespace-scoped proxies via `types.ModuleType`:

- Copy the real module's public surface onto a fresh proxy module.
- Overwrite ONLY the specific methods being restricted, on the proxy.
- Inject the proxy into the handler's `ns` (never touch the real
  module singleton).

Both gates share the same os proxy via `ns["__rc_sandbox_os_proxy__"]`
so a handler with BOTH `subprocess: false` AND `filesystem_writes: [...]`
gets one os proxy with both restrictions layered, not two proxies
fighting each other.

## Verified

    [after install] Studio's subprocess.check_output still real? True
    [after install] Studio's os.makedirs still real?               True
    [after install] Studio os.makedirs(...) ✓ WORKS
    [handler ns]    os.makedirs('/etc/hackerhouse') ✓ blocked
    [handler ns]    subprocess.run(['curl',...]) ✓ blocked
    [handler ns]    os.path present, os.getenv works — proxy carries
                    the full os surface, only the mutation methods are
                    wrapped.

## Honest scope (unchanged)

A handler that does `import subprocess` INSIDE its function pulls the
real subprocess module directly, bypassing the ns proxy. Same for
`import os`. That's the same limit the module_sandbox docstring
already declared before the fix — the sandbox is defense-in-depth
against accidental / AI-drafted misuse, not against a
Python-import-level adversary. Publisher trust + Ed25519 signature
verification are the primary defense.

## Files changed

- `workbench/module_sandbox.py` — 68 lines changed (see engine
  commit `9b048f915`)

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=82961a373c89474c9814348972312f111753bd8f49615fd9cf2c8fd464a450f8
```

## Republishing modules that dropped the requires block

If you dropped `requires` from your module.json as a workaround (e.g.
shweta/zoho-crm shipped 0.2.2 without the block to keep Studio
working), you can put it back and re-publish on v0.37:

    # module.json
    "requires": {
      "network": ["www.zohoapis.in", "www.zohoapis.com"],
      "subprocess": false,
      "filesystem_writes": []
    }

    railcall market module sign .
    railcall market publish . --type=module

Studio's Modules tab will show your capability declaration in the
green sandbox card instead of the amber "unrestricted" banner.
