# RailCall Station v0.4 — registry-driven send airlock + airlock MCP reach users

**Branch:** `release/station-v0.4` · **Author:** Pat (programmer) · **Gatekeeper:** Sami
**Status:** bundle built + verified locally (RE-CUT — see corrected-build note). **Publish (release cut + merge) is Sami's gate.**

This rebuilds the shipped station from **engine `main`** (tip `c700ab6c2` — all 6 v1
PRs, Nick's compute-gate fix, the WS uid-safety hotfix #16, and the CI fix #17)
so the registry-driven send airlock **and the airlock MCP server** reach
installed users. The old station (v0.3) predates §1–§4.

## Corrected build (re-cut, same version)

The first v0.4 cut silently shipped the old cap-off MCP: `build_station_tar.sh`
carried a pre-v1 line (`cp -f workbench/mcp_capoff_server.py workbench/mcp_server.py`)
that ran immediately before tarring and clobbered the airlock `mcp_server.py`
the engine-main overlay had put in place. **Fixed in this PR**: the clobber line
is removed and the script now **fails closed** — it refuses to build if
`workbench/mcp_server.py` in the source tree isn't the airlock, so this cannot
silently regress. `mcp_capoff_server.py` still ships under its own name (the
cap-off #16 workflow's `primitives/mcp_loopback.py` spawns it by filename).

## Artifact

| | |
|---|---|
| Tarball | `railcall_station.tar.gz` (22 MB) |
| SHA-256 | `e8e6358afb0eedddc39f34fa68c3ff6b836dcf9458627b554a84b07c0cfa8972` |
| Built from | engine `main` @ `c700ab6c2`, patched `scripts/build_station_tar.sh` |
| Local copy | `~/Desktop/railcall_station_v0.4.tar.gz` (upload this as the release asset) |

`install.sh` on this branch is already bumped: `STATION_URL` → `station-v0.4`,
`STATION_SHA` → the value above.

## What changed vs v0.3

- **Airlock MCP server** (`workbench/mcp_server.py`, from engine PR #15) —
  **33 registry-driven tools** over stdio JSON-RPC: per ready integration
  `<provider>_<verb>_plan` / `_apply` (plan → policy → signed staged delta →
  one-time consent token → Saga → signed receipt) plus
  `railcall_integrations_list` / `railcall_receipts_list` /
  `railcall_receipt_verify`. Byte-for-byte identical to engine `main`.
  Claude Desktop / VS Code config: `docs/mcp-integration.md` (in the engine).
- `POST /api/integration/{stage,approve}` — the one generic governed-send route
- `GET /api/registry` — full serialized registry (CLI / extension / MCP hosts)
- `GET /api/channels` — registry-driven, bare-map extension contract
- `workbench/studio_integration_send.py` — the generic stage→approve airlock
- `workbench/primitives/integration_registry.py` — 16 entries, **15 ready**
- 5 new primitives (linear/twilio/gcal/s3/intercom) + slack/discord/github/gsheets/webhook wired
- **WS uid-safety** (engine #16, merged before this re-cut): boot aborts if the
  workspace is owned by another user; re-enforces 0700.

## Verification of THIS bundle (SHA `e8e6358a…`; live :8799 never touched)

1. **Built** in a temp tree = installed station structure + engine-`main`
   `workbench/` overlaid (preserves the 3 station-only launchers), using the
   **patched** build script.
2. **Bundled `mcp_server.py` == engine `main` byte-for-byte** — identical
   sha256 `8776403764…202e5007e` on both sides, zero diff.
3. **Live `tools/list` over stdio: 33 tools** (initialize announces
   `railcall-airlock 1.0.0`). Note for reviewers: the ast/grep literal-count
   heuristic returns 6 by construction — tool names are derived from the
   registry at runtime (that's the zero-edit design), so the wire probe is the
   honest measure.
4. **Full MCP roundtrip against the bundled binary**: `linear_issue_create_plan`
   → signed staged delta (`require_human`) → `_apply` with the consent token →
   `DRY_RUN` `railcall_linear_apply_receipt.v1`, Ed25519-signed →
   `railcall_receipt_verify` → integrity match + `signature: verified`.
5. **Cruft-free** (no specs/tests/corpora/node_modules) and **secret-clean**
   (content scan; `chat_guard.py` matches are its own detector regexes).
6. Boots on a throwaway port; `GET /api/registry` → 15 ready.

## Scope corrections (evidence, not assertion)

- **The "ten `/api/<x>/send` shell blocks to retire" never existed** — not in engine
  `main`, not in the v0.3 station. The station's real legacy send routes were the
  three cap-off endpoints `/run_github`, `/run_slack`, `/run_discord`; untouched
  by this rebuild.
- **Release home is railcall-core, not railcall-contrib.** Both `install.sh` files
  fetch the station from `github.com/patl4588/railcall-core/releases/…`. Note:
  `railcall-contrib/install.sh` still points at **station-v0.1** — stale, separate cleanup.

## To publish (Sami — this is the gate)

```bash
# 1. cut the release, uploading the exact verified tarball
gh release create station-v0.4 \
  ~/Desktop/railcall_station_v0.4.tar.gz#railcall_station.tar.gz \
  --repo patl4588/railcall-core \
  --title "RailCall Station v0.4 — registry-driven send airlock + airlock MCP" \
  --notes "Ships §1–§4: airlock MCP (33 tools), generic /api/integration/{stage,approve}, /api/registry, 15 ready integrations, WS uid-safety."

# 2. verify the published asset SHA matches install.sh
curl -fsSL https://github.com/patl4588/railcall-core/releases/download/station-v0.4/railcall_station.tar.gz \
  | shasum -a 256   # must equal e8e6358afb0eedddc39f34fa68c3ff6b836dcf9458627b554a84b07c0cfa8972

# 3. merge this branch (install.sh points at v0.4 + the new SHA)
# Order matters: the release must exist before install.sh v0.4 goes live on main.
```
