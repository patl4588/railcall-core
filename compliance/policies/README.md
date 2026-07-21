# RailCall — Policy set

Every policy in this folder is the canonical source. Probo (local GRC at
`http://localhost:8080`) holds a copy for browsing + version tracking, but
**git is the source of truth** — Probo is not backed up, git is.

## The set

Ordered by rough SOC 2 / HIPAA examiner priority. Cross-references are by
policy number (e.g. "see 03 §7.5" = Incident Response Policy §7.5).

| # | Policy | Purpose |
|---|---|---|
| 01 | Access Control | Who can reach what on both operator + station sides |
| 02 | Encryption | Algorithms, key management, transport, at-rest posture |
| 03 | Incident Response | Detection, severity classes, runbooks, notification windows |
| 04 | Data Retention & Deletion | Per-data-type retention windows + deletion procedures |
| 05 | Vendor & Subprocessor Management | Render / Stripe / Anthropic / GitHub / VPS / Cloudflare / 1Password inventory |
| 06 | Business Continuity & Disaster Recovery | RTO/RPO + per-scenario recovery runbooks |
| 07 | Change Management | The commit → tests → release → deploy pipeline formalized |
| 08 | Risk Management | 16-entry operating risk register + treatment strategies |
| 09 | Access Review | Per-system review cadence + procedure + log template |
| 10 | Acceptable Use | Operator conduct: no fake-green, evidence before prose, secrets never in text |
| 11 | Confidentiality | Data classification (PUBLIC / INTERNAL / CONFIDENTIAL / SECRET) + handling per class |
| 12 | Software Development Lifecycle (SDLC) | Secure coding standards, test discipline, AI-assisted workflow, dependency management |
| 13 | Password & Credential | 1Password mandate, MFA everywhere, per-credential rotation |
| 14 | Physical Security | Cloud-provider inheritance + operator workstation baseline + physical secret backups |
| 15 | Service Availability & Commitments | Uptime targets, failure semantics, degraded-service behavior, third-party bounds |

## How they link

Every policy cross-references the others by section number — start anywhere,
follow the trail. Best entry points:

- **08 Risk Management §6** — single-page view of the security posture (each
  R-nn ties threat, control, treatment, evidence together).
- **06 BC/DR §5** — per-scenario recovery runbooks (issuer seed lost, gateway
  outage, VPS lost, laptop stolen, Sami unavailable).
- **03 Incident Response §7** — per-threat response runbooks.

## Status

Every policy is currently **v1 DRAFT**. Adoption sequence:

1. Sami reads the set (this is you).
2. Each policy gets a v1.0 ADOPTED transition (add "Adopted by Sami on
   YYYY-MM-DD" to §Adoption or equivalent section).
3. Counsel review before any policy is presented externally.
4. Re-review at each station release + at least annually.

## Related evidence

- **`../HIPAA_SRA_v1_2026-07-21.md`** — the Security Risk Analysis that
  seeded most of the risk register in policy 08.
- **`../../legal/BAA_DRAFT.md`** — the Business Associate Agreement draft
  that references these policies as its Exhibit B evidence base.
- **Probo** at `http://localhost:8080` — browsing UI with version history +
  approval workflow; see `~/.claude/projects/-Users-macbook-raill/memory/project_probo.md`
  for the start/stop procedure.

## No fake-green

Every "IMPLEMENTED" claim in these policies cites a specific file + test that
proves it. Every gap is stated as a gap with reason + treatment. If a policy
claims something and the code doesn't back it, the policy is wrong, not the
code. See `../README.md` for the honesty rules the folder operates under.

## What's still missing (deliberate gaps, tracked)

- **Employee handbook / background checks / training records** — N/A at team
  size 2 with two founders. Trigger for adding: any hire.
- **Formal risk register software** — currently living in policy 08 §6 as a
  markdown table + in Probo as risk entities. When the register outgrows a
  markdown table, migrate to Probo as the SoT.
- **External SOC 2 auditor engagement** — required for the actual SOC 2
  Type II report. Not yet engaged; target Q4 2026 per what /enterprise
  publicly says.
- **HIPAA BAA counsel review** — the BAA draft exists but requires attorney
  review before it can be sent to a customer.
- **Off-box audit-chain witness** — mitigation for R-02 residual, on the
  roadmap.
- **Customer-facing subprocessor list** at `railcall.ai/legal/subprocessors` — a
  DPA-common requirement, referenced by policy 05 §7 but not yet published.
