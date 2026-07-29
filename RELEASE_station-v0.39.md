# station-v0.39

Single-fix cut. `capabilities.max_spend_cents` now enforces inside
`for_each` iterations across cumulative spend — the platform gate
Dave (Track B) was documenting as unenforced in his workflow
description.

## What was broken

Dave's workflow declared `capabilities.max_spend_cents` at the top
and looped over payments with `for_each`. The platform gate silently
passed for every iteration. He'd built a manual cond node to
enforce the cap and his workflow description spelled out the reason.

## Two compounding gaps

**Gap 1 — the amount extractor only saw top-level `amount_cents`.**
Publishers whose args nested the amount (`payment.amount_cents`,
`charge.amount_cents`, common alias `charge_cents`, etc.) got 0
back from the estimator, so the pre-run guard never fired.

**Gap 2 — post-run credit re-estimated from the same args.** Same
limitation as gap 1: if the pre-run estimate was 0, the post-run
credit was 0, `spent_cents` stayed 0, next iteration passed. Silent
under-count.

## Fix

`_estimate_amount_cents` now walks nested dicts + lists up to depth 4,
recognizes several common aliases (`charge_cents`, `total_cents`,
`cost_cents`, `amount_in_cents`, `spend_cents`), coerces
integer-strings (`"250"` → 250), sums batch shapes
(`{charges: [{amount:100},{amount:200}]}` → 300), and refuses `bool`
(bool is-a int in Python).

Post-run credit reads spend from THREE sources and credits the max:

1. `receipt.spend_cents` — handler-reported, authoritative
2. Output amount fields — Stripe charge response, gateway ack
3. Args re-estimate — legacy fallback

Preferring the max means a small over-count is possible; that's the
correct tradeoff for spend safety (missed spend > over-attributed).

Added a post-credit re-check: if `spent_cents` already exceeds
`max_spend` after the actual handler-reported spend, the guard
trips before the next iteration runs. Handles the case where the
handler's real spend exceeded the pre-run estimate (dynamic pricing,
per-call surcharges).

## Verified — Dave's exact case

`for_each` over 4 payments, each with nested
`{payment: {amount_cents: 100}}`, cap 250 cents:

    Before v0.39: 4 iterations ran (gate silent)
    After  v0.39: 2 iterations run, iteration 3 REFUSED_PRE
                  (200 + 100 > 250)

10 estimator test cases pass: top-level, nested, aliases, batch
lists, unresolved templates, bool refused, float coerced,
depth-guarded, mid-depth found.

## When Dave updates

He can drop the manual cond node — the platform gate is now
enforcing what his workflow description already documented.

## Files changed

- `workbench/workflow_engine.py` — 122 lines (engine commit
  `7eac2fc46`)

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=81c6682998febaad97c6a1f99a9958eeaeea8dceecd650cb614fe2b6ff608cc3
```

## Credit

**Dave** — third real bug from him in a week. Track B author, gave us
the exact code path both times (Receipts render, spend gate). This
release is his.
