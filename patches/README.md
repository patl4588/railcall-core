# Staged patches — review & merge (for Nick)

Two SEV-3 fixes from the QA campaign, pre-coded so they're a review-and-merge, not a re-scope.

| Patch | Fixes | Where it applies |
|---|---|---|
| `studio_csrf.patch` | Cross-site POST with no `Origin`/`Referer` reaching the mutating `/api/*` routes (key-write, command-run) | `studio_server.py` → `do_POST` |
| `engine_signing.patch` | `workflow_id` / `built_at` attached *after* signing → mutable on a signed receipt (Nick's 2 missed tampers) | the engine's `railcall_flow_receipt.v0` mint block |

**These target the engine source (`railcall-engine`), which is not in this repo.** So they're written as
precise, commented diffs to **review and apply by hand** — the `@@` context lines are illustrative of the
real blocks, not guaranteed to `git apply` clean against your tree. Each change is tiny (8 lines / 2 lines
moved) and each patch ends with the exact `curl` / tamper test to confirm it before you merge.

The `studio_csrf.patch` context is taken verbatim from the current `do_POST`, so it should apply cleanly
or near-cleanly. The `engine_signing.patch` is the *move-these-above-the-signature* change — apply it at
wherever your flow-receipt is assembled and signed.

After merging, rebuild + redistribute the Studio bundle (the CSRF fix only protects users once the new
bundle ships via `install.sh`).
