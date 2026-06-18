# RailCall Public-Launch Honesty Gates — Audit Receipt

**Audit time:** 2026-06-16
**Auditor:** Nick (operator) + Claude (file-level verification)
**Purpose:** Pin the file + line state of both honesty gates before
railcall.ai goes public (noindex off).

---

## Gate #1 — `railcall` CLI alias ships

**State:** **CLOSED** (this audit)

**Verifying commit:** `45ae3ccac7a5dd6ea63a5d82eb0ab4634b59ec73` on
`origin/railcall-cli-alias-v1` (3-file change: `INSTALL.md`,
`install.sh`, `node/package.json`; README.md untouched).

**Evidence pinned in-repo:**

- `node/package.json` bin map adds `"railcall-node": "./index.js"`
  (alongside existing `"metercall-node"`) — true alias of the same
  entry point.
- `install.sh` writes a thin launcher to `~/.railcall/bin/railcall`
  that resolves `$REPO` at runtime via `$BASH_SOURCE` and
  `exec node "$REPO/node/index.js" "$@"`. No vendored copy.
- PATH addition to `~/.zshrc` is marker-guarded
  (`# >>> railcall path >>>` / `# <<< railcall path <<<`).
- Claude Desktop config is **reported, not edited** (honest
  refusal to auto-mutate `claude_desktop_config.json`).

**Live verification on iMac (Atlantics-iMac, macOS Tahoe):**

- `./install.sh` exit 0
- `~/.railcall/bin/railcall` written (1,017 B, executable, sha256
  `da129395f7121a8928ad9cc3805f19efa3f69ed52ee744d30ab6c25c1b4801da`)
- `railcall where` → prints repo + node + mcp entry paths
- `railcall version` → `0.1.0`
- `railcall --help` → usage with 4 subcommands, no server started
- L4 RPC node NOT started during audit: 0 running processes,
  0 listeners on :8545
- Re-running `install.sh` is idempotent: PATH marker count
  stays at 2, launcher sha256 unchanged.

---

## Gate #2 — payments stay labeled "preview" / dry-run / no live billing

**State:** **CLOSED** in committed website copy (this audit).

**Verifying commits:**

- `origin/website-developer-first-v1 @ 6ca3a4637947535e387dfa610640d66427c02a1a`
  — RailCall homepage (`index.html`, plus identical mirrors
  `home.html` and `the-one.html`, same blob `c7051f8d5e088ee20bac864debf0afc348a93726`,
  25,237 bytes).
- `origin/website-sandbox-v1 @ 56b85677de04acfb88ae5637b0d0417d84daec08`
  — `sandbox.html` browser-only simulator (84 KB).

**Evidence (`index.html` on `website-developer-first-v1`):**

- `<meta name="robots" content="noindex">` — present (1).
- `preview` — 13 occurrences (payments framing, plan tier, status block).
- `dry-run` — 11 occurrences.
- Explicit disclaimer (line 198 of original audit):
  *"payments are the next rail, not a live one. As of today RailCall
  meters each run as a receipt in **dry-run preview** — no USDC
  settles, no card is charged, **no live billing path is enabled**.
  The x402 and Stripe tracks above describe the architecture the
  metered receipt was designed for."*
- HIPAA/SOC2 only appears in the **competitor** column of the
  comparison table (line 141) — competitor's liability surface,
  not a RailCall compliance claim. Not a banned claim.
- Net banned-claim hits: 0.

**Evidence (`sandbox.html` on `website-sandbox-v1`):**

- `<meta ... noindex ...>` — present (1).
- Pricing references are `$0.005 per run` (4 occurrences) — not
  `$0.01` as the round-robin email asserted. The free-tier copy
  reads **100 Free Runs Included** (line 128) — not 50 free runs as
  the email asserted. The audit doc pins what is actually in the
  file; the email's numbers were not landed.
- Banned-claim sweep: no `cryptographic`, no `production-ready live`,
  no `SOC2 certified`, no `Stripe integrated`. Stripe mentions appear
  in a competitor-comparison table (e.g. "Flat $15 to $100+ per
  user/month" vs RailCall, "$10 credit deposits to survive Stripe
  fees") — comparisons, not RailCall claims.
- The page is a sandbox simulator. "Preview" framing is in the
  parent index.html's payments section (which links here). Pages
  are noindexed.

**Implicit gate:** while noindex is on across all these pages,
gate #2 holds by default — search engines won't surface the pricing
to the public. Flipping noindex off without first reconciling the
public-facing pricing copy (1 cent claim vs 0.5 cent reality;
50 free claim vs 100 free reality) would be a gate-#2 break.

---

## Pinned blockers to noindex-off (must be resolved first)

1. **Pricing reconciliation.** Decide $0.005 or $0.01 (current file
   says $0.005, recent message asserted $0.01). Decide 50 or 100 free
   runs (current file says 100, recent message asserted 50). Update
   the file OR update the message. Commit + push the canonical
   version before noindex off.
2. **railcall.ai deployment path.** Yesterday's handoff said GitHub
   Pages (apex A records to GitHub's four `185.199.108.x` IPs).
   This morning's handoff said "active Digital Ocean Droplet IP".
   No droplet IP exists on origin (no `droplet`, `digitalocean`,
   `fly.toml`, or deploy config committed). Pick a path, commit the
   IP / Pages CNAME, then point GoDaddy at it.
3. **CNAME for railcall.ai.** Current `CNAME` file on
   `website-developer-first-v1` still says `metercall.ai`. If
   railcall.ai goes on Pages, it needs its own repo with a `CNAME`
   reading exactly `railcall.ai` (per the prior handoff) — that
   prod repo has not been created yet.

## Sign-off (when gates close together)

- [x] Gate #1 (CLI alias ships) — CLOSED
- [ ] Gate #2 (payments stay preview) — file state CLOSED; **pricing
  reconciliation pending** (see blocker #1)
- [ ] Deployment path picked + IP / CNAME committed (blocker #2-3)
- [ ] noindex flipped off (only after all above)

— Receipt logged 2026-06-16
