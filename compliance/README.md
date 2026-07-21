# RailCall — Compliance evidence

This folder is where RailCall's compliance artifacts live. It's intended to be the
single place a customer's security team, an auditor, or our own counsel can find
what RailCall claims about compliance and the evidence backing each claim.

## What's in here

- **`HIPAA_SRA_v1_2026-07-21.md`** — the Security Risk Analysis
  (45 CFR §164.308(a)(1)(ii)(A)). Structured to match the HHS SRA Tool's
  category set, cites real code and test-suite line numbers, and states
  gaps as gaps rather than hiding them. **ADOPTED 2026-07-21** by Sami Ben
  Chaalia (Security Officer); see §8 of the document. Counsel review still
  required before presenting to a covered entity — adoption is the internal
  compliance-record act, not the external legal-sign-off act.
- **`../legal/BAA_DRAFT.md`** — the Business Associate Agreement draft
  (already lives under `legal/`, kept there for now to match existing paths).
  Not to be sent to a customer until counsel reviews it.

## What is deliberately NOT in here

- **SOC 2 report.** None exists yet. Target: Q4 2026 per what /enterprise
  now says publicly. When we engage a CPA firm the readiness assessment
  will land here first.
- **Signed BAAs, executed DPAs, per-customer paperwork.** Those are
  customer-specific and belong in a private legal system of record, not
  in a public repo folder.

## Honesty rules

Same rules as the rest of the repo:
- **No fake-green.** A control is either implemented (cite the code) or a
  gap (state it as a gap). Never "in progress" without saying who is doing
  the work and when.
- **Evidence before prose.** Every controls table row cites a specific
  file, function, and behaviour. If the row can't cite something, it's a gap.
- **Point-in-time.** Every document carries the date it was written and the
  git commit it applies to. A recycled SRA that quietly stops matching
  reality is worse than none.
