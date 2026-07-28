# station-v0.34

Tarball change. Small but hits every publisher with a multi-file module
layout, so shipping fast rather than batching.

## Headline

**Module loader now puts your module's install directory on sys.path
for the duration of the handler exec.**

Real bug caught by Rayan (ShopFlux Shopify CSV Toolkit). Handlers with
the standard nested-package layout — a `handlers/handler.py` that does
`from core import ...` on sibling packages like `core/`, `cleaners/`,
`validators/` — failed to load on v0.33 with:

    load error: ModuleNotFoundError: No module named 'core'

Root cause: the loader exec'd handler_bytes but never made the handler's
install directory findable on sys.path. Only stdlib + station-side
packages resolved. Local `python handler.py` tests passed because cwd
happened to be the module root; Studio load failed because it wasn't.

## Fix

    _module_dir = os.path.dirname(handler_path)
    if _module_dir and _module_dir not in sys.path:
        sys.path.insert(0, _module_dir)
        _pushed_module_dir = True
    try:
        exec(compile(handler_bytes, handler_path, "exec"), ns)
    finally:
        if _pushed_module_dir:
            sys.path.remove(_module_dir)

`finally`-guard removes the entry after exec so a later-loaded module
can't accidentally shadow a different module's `core/` package. Import
cache is left populated on purpose — the handler needs its submodules
callable at command-execution time, not just at load time.

## Impact

Unblocks any module with a nested package layout. Recommend publishers
use this shape:

    marketplace_module/
    ├── module.json
    ├── handlers/handler.py
    ├── core/                    # <-- now importable via `from core import ...`
    ├── cleaners/
    ├── validators/
    └── ...

Handlers on v0.33 with `sys.path.insert(0, ...)` shims at the top of
handler.py keep working on v0.34 — the shim's `if X not in sys.path`
guard makes it idempotent.

## Files changed in tarball

- `workbench/studio_server.py` — 24 lines (see engine commit 5c4b15764)

## Verify

```bash
curl -sSL https://install.railcall.ai | bash
# STATION_SHA=f17fbf281327120159611dd4ae5b877b9421a4e3f6301384a386618415589d97
```

## Upgrade path

Zero-config. Existing modules keep loading. Modules that were rejected
with `ModuleNotFoundError` on v0.33 will load cleanly on v0.34.
