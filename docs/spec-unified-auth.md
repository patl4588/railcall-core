# Spec — unified authentication (marketplace as the single identity authority)

**Owner decision (Sami, 2026-08-31):** "we would like to unify authentication …
both should be using the marketplace backend."

## The problem

Two complete, disjoint identity stacks:

| | Marketplace (NestJS) | Gateway (cloud_gateway.py) |
|---|---|---|
| Accounts | `User` (Prisma) — email, argon2, verified flag | `consumers` (SQLite/PG) — email, PBKDF2 |
| Sessions | JWT (HS256) + rotating refresh tokens | homegrown HMAC `payload.sig` tokens |
| OAuth/SSO | Google/GitHub + WorkOS SSO, orgs, roles | its own Google OAuth config |
| Resets | argon2 + throttled endpoints | its own Resend reset emails |

One human ⇒ two accounts, two passwords; every auth fix done twice or not at all.

## Target

Marketplace = the **only** place credentials live and tokens are minted.
Gateway = a **verifier** of marketplace identity + its own metering/billing
ledger keyed by marketplace user id.

Explicitly OUT of scope (not "auth" in this sense, correctly separate):
- `railcall-license` — service-secret S2S, blast-radius-separated by design.
- Station Ed25519 install identity — machine identity; it *binds to* accounts
  (`User.install_pubkey`), it is not replaced by them.

## Step 1+2 — DONE (railcall-core `1175a98`)

Gateway accepts marketplace JWTs alongside legacy sessions, via
**introspection** against `GET /auth/me`:

- No shared signing secret — gateway compromise cannot mint marketplace tokens.
- Fail-closed; 60s positive / 10s negative cache; bounded cache.
- Shape trap handled: JWTs fail the legacy HMAC *compare* (not parse), so the
  fallback runs on every legacy miss, not just exceptions.
- Proven: 6-shape unit test + live end-to-end with a real minted JWT.

Deploy: push railcall-core → Render redeploys the gateway. Zero-risk rollout —
purely additive acceptance; nothing existing changes behavior.

## Step 2.5 — one WEB login (DONE 2026-08-31)

Step 1+2 unified the API; the SITE still had two logins. Closed:

- **Gateway auto-provisions** a free-tier ledger for a marketplace identity on
  first `/v1/auth/me` (railcall-core `cloud_gateway.py`). Verified live: a
  marketplace JWT hit `/v1/team/members` 200 but `/v1/auth/me` 404 — same
  token, only the latter needed a `consumers` row. Now 200 with tier=free,
  500 flows.
- **Dashboard sends the marketplace token** (`sessionHeaders` → `getWebToken`,
  railcall-website `app/lib/auth.ts`). Site nav already pointed only at
  `/marketplace/login`, so one marketplace login now powers storefront AND
  dashboard.

**Remaining single-login gap:** `/cli-activate` (+ `/cli-activate/signup`) is a
separate gateway-account flow with its OWN OAuth start/callback and password
reset, reached directly (from `railcall login` in the terminal), not from nav.
Folding it onto marketplace auth is part of Step 4 — until then, a user who
signs up via the terminal-activation page still creates a gateway-only
consumer. That path is measured and migrated in Steps 3-4.

## Step 3 — account linking (NEXT; needs prod data first)

Goal: every existing gateway `consumer` row maps to a marketplace `User`.

1. **Measure first** (admin, read-only): counts of gateway consumers total /
   with verified marketplace account at same email / gateway-only. That number
   decides quiet-migration vs re-onboarding-email.
2. Add `consumers.mkt_user_id` (nullable). Backfill by **verified-email match**
   only — an unverified marketplace email must never claim a gateway account
   (account-takeover vector). Verified-to-verified match = link silently.
3. Gateway-only users: on next legacy login, offer "link or create your
   RailCall account" (marketplace signup pre-filled with the same email; then
   auto-link on the verified callback).
4. Marketplace claims from step 1 already carry `mkt_user_id` — when a
   marketplace-authed request arrives, upsert the link on first sight.

Invariants:
- Linking NEVER merges balances/metering rows automatically across different
  emails — same-email only; anything else is a support action.
- `_ensure_org(email)` keeps working unchanged during the window (claims carry
  email in both formats).

## Step 4 — retire gateway credentials (LAST; gated on 3 ≥ ~95% linked)

1. Gateway `/login`, `/register`, password-reset → **410 Gone** with a JSON
   pointer to marketplace auth (clients show "sign in with your RailCall
   account").
2. Legacy HMAC sessions: stop MINTING immediately; keep VERIFYING for one TTL
   window (30d), then delete the branch — `_verify_session_token` becomes
   introspection-only.
3. Drop `password_hash` from `consumers` (migration) once minting is off and
   the window has passed. The table remains as the metering/billing ledger.
4. Remove the gateway's own Google OAuth config + Resend reset templates.

Rollback at any point = revert the step's commit; step 1+2's dual acceptance
is the safety net the whole sequence stands on.

## Risks / notes

- `/auth/me` becomes a mild hot path → mitigated by the 60s cache; if it ever
  matters, swap introspection for JWKS (marketplace moves to RS256/EdDSA and
  publishes a public key) — the gateway change is isolated to
  `_verify_marketplace_token`.
- Marketplace outage during the window: marketplace logins pause at the
  gateway, legacy sessions unaffected (fail-closed, verified).
- The test account `authtest-48072750@test.railcall.ai` (created for the live
  proof) can be deleted whenever; it has no purchases.
