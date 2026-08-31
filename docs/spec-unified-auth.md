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

**Single-login gap CLOSED (2026-08-31, later same day):** `/cli-activate` and
`/cli-activate/signup` are now redirects to the marketplace login/signup
(routes preserved for CLI-printed URLs; old UIs in git history). `/dashboard`
recognizes the marketplace token and sends unauthenticated visitors to the one
login. Gateway `/v1/auth/me` returns the clear `api_key` so the CLI-activation
purpose (copy your key into `railcall login <key>`) works end-to-end from a
marketplace login — proven live. The landing's injected script also flips
"Sign in"→"Dashboard" when the marketplace token is present. No UI on
railcall.ai uses gateway credentials anymore; endpoint retirement stays Step 4.

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

## Step 3 MEASUREMENT + LINK — DONE (2026-08-31)

Measured live (hashed emails; no raw address list left the gateway):
**186 gateway consumers / 161 marketplace users.**

| segment | count | active | paying |
|---|---|---|---|
| verified-email match (linked) | 15 | 8 | 0 |
| unverified-email match (NOT auto-linked) | 4 | 1 | 0 |
| gateway-only (no marketplace account) | 167 | 24 | 1 |

**Only 8.1% linkable now, not the ~95% Step 4 assumed — so the silent-backfill
path is OFF. This is re-onboarding, not silent migration.** The 15 verified
matches ARE linked (`consumers.mkt_user_id` set via `/v1/admin/link_accounts`,
dry-run→apply→idempotent re-apply all proven). Revised plan below.

### Revised Step 4 (the 167 gateway-only, by stakes not headcount)

1. **The 1 paying gateway-only account — WHITE-GLOVE, do not automate.** Confirm
   its email, have them create/verify a marketplace account, link it, verify
   balance carried. One person; worth it.
2. **The ~24 active gateway-only — one re-onboarding email** ("your login is
   moving; set your password once", marketplace signup pre-filled + auto-link
   on the verified callback). Outward comms → Sami/Pat decision.
3. **The ~140 dormant gateway-only — leave them.** The shipped /cli-activate
   redirect already routes them to marketplace signup whenever one returns.
   No proactive work.
4. **The 4 unverified matches — never auto-link** (takeover vector). They flow
   through the same re-onboarding as gateway-only if they return.

## Step 4 — retire gateway login endpoints (after the above; keep verifying legacy sessions one window)

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
