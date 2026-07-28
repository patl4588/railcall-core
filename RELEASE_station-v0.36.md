# station-v0.36

Real multi-file module support. Closes the spec gap that had every
publisher with a proper package layout ship broken modules to buyers.

## Headline

**`railcall market publish` now bundles the whole module tree.**

Before v0.36: `market publish` only shipped 3 files (`module.json`,
`handlers/handler.py`, `module.sig`). Sibling directories (`core/`,
`cleaners/`, `validators/`, `exporters/`, `reports/`, `rules/`, etc)
were silently dropped from the tarball. Publishers who architected
modules correctly — separated concerns, real package boundaries, tests
they could run standalone — got half their code truncated between
local test and marketplace install.

After v0.36: opt-in v2 (tree) bundles carry the entire module dir as
a signed tarball. v1 single-file bundles keep working byte-identically
for every existing module.

Rayan (ShopFlux Shopify CSV Toolkit) caught this in testing and
pushed back until we fixed it correctly.

## New bundle spec — auto-detected

Publishers do nothing new for existing single-file modules. For
tree-shaped modules, `railcall market module sign` auto-promotes to
v2 when it sees ANY of:

- `manifest.manifest_version: 2` in module.json (explicit opt-in)
- A `.moduleignore` file in the module dir (implicit opt-in)
- Any file outside `{module.json, module.sig, handlers/}`

## .moduleignore

fnmatch-style patterns, one per line, `#` for comments. Directory
patterns end with `/`.

Defaults (always excluded):

    __pycache__/, *.pyc, *.pyo, *.pyd
    .pytest_cache/, .mypy_cache/, .ruff_cache/
    .git/, .gitignore
    .env, .env.*, *.env
    .railcall/, .railcall_workspace/
    node_modules/
    *.log, .DS_Store
    module.sig            ← never part of the signed tree

Publisher `.moduleignore` merges with defaults:

    # my_module/.moduleignore
    fixtures/
    tests/
    dev-notes/

## Signature contract

    v1 (single-file):  canonical(manifest without "signature") || b"\n" || handler.py bytes
    v2 (tree):         canonical(manifest without "signature") || b"\n" || tree_manifest_bytes

`tree_manifest_bytes` is sorted lines of `<rel_path>\t<sha256_hex>\n`
for every file in the module dir after `.moduleignore` filtering. So
the Ed25519 signature covers the manifest AND every file's exact bytes
AND the exact set of files. Adding, removing, or modifying any file
breaks the signature.

## What ships in the tarball

- `workbench/studio_server.py` — `_verify_module_signature` dispatches
  on `manifest_version`. v2 reconstructs `tree_manifest_bytes` from
  disk with the same `.moduleignore` rules the CLI used at sign time
  (byte-parity verified). `marketplace_install_listing` unpacks
  `module_files_b64` (base64(tar.gz)) into `module_dir` before writing
  the three canonical files. Path-traversal guarded.

## What ships in the CLI (v0.36)

- `railcall market module sign` — auto-detects tree mode, walks
  `.moduleignore`, writes `manifest_version: 2` to `module.json`,
  signs against the tree manifest.
- `railcall market module verify` — reads `manifest_version`, walks
  the tree, verifies against the correct recipe.
- `railcall market publish` — builds deterministic `tar.gz` in-memory
  (sorted names, fixed mtime + mode → reproducible bytes), 8 MiB
  uncompressed cap, base64-encodes as `module_files_b64` in the
  payload alongside the existing 3 fields.
- `railcall market install` — decodes + untars into `mdir/`, then
  writes the three canonical files. Path-traversal guarded.

## Backend (railcall-marketplace)

Accepts optional `module_files_b64` in the module payload, 12 MiB
base64 cap, requires `manifest_version: 2` in both payload and
parsed `module.json`. Absent field = legacy v1 install path.

## Backwards compatibility

Every existing module (all v1 single-file) publishes, installs, and
verifies exactly as before. No forced migration. Publishers who want
tree support add sibling directories and re-sign.

Old stations (< v0.36) hitting a v2 module get a clean rejection with
a message pointing at the upgrade path (loader can't reconstruct the
tree manifest → signature fails → module refused, not silently
partial-installed).

## Smoke tested end-to-end

Real Ed25519 key + fake multi-file module + tamper cases:

    [SIGN] v2, 3 files
    [VERIFY unmodified]  ✓ PASS
    [VERIFY tampered]    ✓ CORRECTLY REJECTED (edited a file)
    [VERIFY new file]    ✓ CORRECTLY REJECTED (added a file)
    [VERIFY restored]    ✓ PASS
    [V1 compat]          ✓ PASS

Byte parity confirmed between CLI's `_module_tree_manifest_bytes`
and engine's `_module_tree_manifest_bytes` (identical 482-byte tree
manifest for the same test tree — that's what makes signature
verification possible across the wire).

## Files changed this release

- Tarball: `workbench/studio_server.py` (v2 verify + install unpack)
- CLI (fetched separately): `railcall_cli.py` (sign / publish / install v2)
- Marketplace backend (deploys separately): `listings.service.ts`
  (accepts new payload field)

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=ca6d9fa82cc3d573e0e06fb2c236a4ddfad70df377c3647cbdc27770bbb807c5
```

## Publisher migration guide

**Have an existing single-file module?** Nothing to do. Ship as
before.

**Have a tree-shaped module the marketplace was truncating?** After
upgrading:

    cd my-module/
    # optional: add .moduleignore for fixtures/tests/dev-notes
    railcall market module sign .
    # sign output shows: spec: v2 (tree) + file count
    railcall market publish . --type=module
    # publish shows: bundle bytes uploaded

Buyers install with `railcall market install <slug>` (unchanged) and
get every file you signed.
