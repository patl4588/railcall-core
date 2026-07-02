# RailCall Knowledge Base

The support brain answers from this file (plus the canonical facts baked into the brain). Edit freely —
the bot hot-reloads on save, no restart needed. Keep answers short, true, and non-committal where we're
unsure. If we don't know, the honest answer is "not sure yet, a teammate will confirm." UNKNOWN ≠ PASS.

## Install & first run
- Install: `curl -fsSL https://railcall.ai/install.sh | bash`. Studio opens locally at `http://127.0.0.1`.
- Nothing runs until you approve it — builds are dry-run by default; the Airlock shows the exact payload first.
- Requirements: macOS or Linux with Python 3. The `.app` is signed + notarized (opens clean on macOS).
- "It didn't open / Gatekeeper blocked it": use the curl install above (not an unsigned download).

## Accounts, keys & BYOK
- Bring your own key (BYOK): your provider key lives in a local **0600** vault and never leaves your machine.
- We will **never** DM you first or ask for your API key. Anyone who does is not us — report it in #support.
- Free tier: **100 flows, no card required.** Flows are prepaid, the balance never expires, no per-seat fees.

## Billing
- Pricing is blind-metered: a flat **$0.01 per governed flow**. The unit is a "flow."
- To check balance the client sends only a **hashed** key + a one-time nonce — never the raw key, files, or data.
- Reinstalling never resets your balance; the token carries it. Run `railcall balance` to check.
- Refunds / double-charges / billing disputes → a human handles these. Say so and escalate.

## Receipts & verification
- Every governed flow mints an **Ed25519-signed receipt** on your machine.
- Verify any receipt offline with `railcall verify` — tamper-evident, no trust required.
- A run only counts as PASS when `external_sockets: 0`, `needs_audit: 0`, and the sha256 `integrity_root` re-verifies.

## Privacy & data
- Local-first: keys, files, workflow data, and generated code **never leave your machine**.
- The billing gateway is a transaction register, **not** a data sink — it ingests credentials/billing tokens only.
- You own 100% of the code RailCall generates. Cancel any time and you keep every line.

## Compliance (be honest)
- RailCall does **not** auto-grant SOC2 / HIPAA / GDPR. If a status is UNKNOWN it means unverified — never claim a pass.
- Enterprise / contract-specific compliance questions → escalate to a human.

## Webhooks & connectors
- Webhook ingest is loopback-bound and token-gated (per-slot `WEBHOOK_TOKEN`). External senders need a tunnel.
- Connectors are generic local adapters (REST / Webhook / SQL / Email / OAuth) + MCP — not cloud relayers.

## When to escalate to a human (don't guess)
- Billing disputes, refunds, account access/lockout, an unconfirmed bug, a security report, anything legal,
  or any question not covered above. Answer what you can, then loop in the team.
