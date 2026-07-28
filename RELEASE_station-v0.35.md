# station-v0.35

Emergency single-fix cut. v0.34's module-loader "fix" was wrong.

## What went wrong in v0.34

v0.34 shipped a change to `_load_modules` that put a directory on
`sys.path` before executing handler bytes, so multi-file modules with
sibling packages (`core/`, `cleaners/`, etc) could import each other.

Except I used `os.path.dirname(handler_path)`, which resolves to
`mdir/handlers/` — NOT the module root. So a handler doing
`from core import ...` still failed with `ModuleNotFoundError` because
`core/` sits at `mdir/core/`, one level up from `handlers/`.

Rayan (ShopFlux Shopify CSV Toolkit) caught the bug in testing after
updating to v0.34. Nobody else was blocked yet because most on-disk
modules today are single-file.

## v0.35

    _module_dir = mdir   # was: os.path.dirname(handler_path)

That's the whole diff. `mdir` is the module root directory bound at
the top of the loader block — it's what a publisher intuitively
means by "the module root."

Smoke tested with a fake module tree:

    mymodule/
    ├── handlers/handler.py     # from core import hello
    └── core/__init__.py        # def hello(): return "core loaded"

Before v0.35: `ModuleNotFoundError: No module named 'core'`
After v0.35: `test: core loaded`

## Important honest note

**v0.35 alone doesn't unblock Rayan.** A separate spec gap means
`railcall market publish` today only bundles three files —
`module.json` + `handlers/handler.py` + `module.sig`. Sibling
directories are silently dropped from the tarball at publish time,
so even with the correct sys.path, there's nothing at `mdir/core/`
for the loader to find.

That's tracked as v0.36 batch #0: extended module packaging (walk
whole tree with `.moduleignore`, sign a canonical manifest of paths
+ hashes, upload tarball, Studio install unpacks the full tree).
Coming in the next couple of days.

The v0.35 fix is still worth shipping standalone: any handler that
does `sys.path`-relative work assumes the module root is findable,
and now the loader keeps that promise. Once v0.36 multi-file publish
lands, v0.35's loader becomes what its docstring already claimed.

## Files in this tarball changed

- `workbench/studio_server.py` — 3-line diff in the module loader
  block (see engine commit 9fbcd092b)

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=95c3c77ff6da15b4159ad99b52349b273c6d74bbadb5b98551d8f93707761263
```

## Upgrade path

Zero-config. Existing on-disk modules keep loading exactly as
before (they don't need sys.path help because everything is inline
in one handler.py today). Any future multi-file module — after v0.36
ships packaging — imports cleanly.
