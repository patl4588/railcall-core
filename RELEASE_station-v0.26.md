# RailCall Station v0.26 — enterprise readiness (SSO + RBAC + SCIM + configurable receipt vault)

**Status:** cut. Tarball built, install.sh pinned, GitHub release published.

The most significant single release since v0.22 (marketplace/modules launch). v0.25 was the last "solo-user" cut; v0.26 is the first release where a team-sized customer can honestly buy Enterprise:

- Log in with their identity provider (WorkOS SSO — Okta, Azure AD, Google Workspace, Ping, any SAML/OIDC).
- Auto-provision + auto-remove users when their HR system flips them (SCIM Directory Sync).
- Assign roles across their team (owner/admin/publisher/operator/viewer).
- Publish modules only their team sees (internal-only marketplace visibility).
- Stream every signed receipt to a shared vault they control (local path, external SSD, NAS mount, USB stick, or an S3-compatible bucket — one config, every seat writes there).

Every existing solo install keeps working unchanged. The vault config is optional, additive, and best-effort — a mirror on top of the local write path that has always been the trust surface. If the vault is unreachable, the local write still happens; the run never fails on a mirror.

## What's new

**1. WorkOS SSO** — `/marketplace/sso` on the storefront + `/auth/sso/*` on the marketplace API. Enterprise buyer types their work-email domain; browser bounces through their IdP; JIT-provisions User + Membership; mints the same JWT+refresh pair the password flow issues. First user on a fresh WorkOS org auto-lands as `owner` because they're almost certainly the identity admin who set up SSO in the first place. Degrades cleanly without `WORKOS_API_KEY` — the SSO routes 503 with an actionable message; every other endpoint keeps working.

**2. Multi-seat + RBAC** — `Organization` + `Membership` tables with a five-role ladder (viewer < operator < publisher < admin < owner). Full invitation flow: `POST /org/invitations` (admin+), invite email with a sha256-hashed token, `POST /org/invitations/accept`. Last-owner protection prevents the org from becoming ownerless via demote/remove. Frontend: `/marketplace/org/members` (roster + invite + role dropdown + revoke).

**3. SCIM Directory Sync** — `POST /webhooks/workos` signature-verified receiver. Handles `dsync.user.created/updated/deleted` + `dsync.group.user_added/removed`. When the customer's IdP flips a user, we mirror it: JIT-create Membership, sync attributes, mark Membership.removed_at on deletion. Group→role mapping via `Organization.dir_group_role_map` (RailCall staff sets it after the customer creates their IdP groups). Group elevation is additive-only — a manual UI promotion isn't clobbered by an unrelated group event.

**4. Internal-only marketplace** — `ListingVisibility` enum (`public` | `org_internal`) + `Listing.owner_org_id`. Publisher-role members can publish listings that only members of their org can see + install + purchase. Non-members get 404 (not 403) on both browse and detail so slug enumeration returns nothing.

**5. Configurable receipt vault** — `Organization.vault_config` JSONB + admin surface. Every Studio in the org fetches the config on boot (5-min TTL cache) and mirrors every receipt + audit line to whatever driver the org set. Drivers:

- `local` — filesystem path. Covers external SSD, NAS mount, USB stick — the OS mounts, Studio writes.
- `s3` — hand-rolled AWS SigV4 over urllib. Zero deps. Works with AWS S3, MinIO, Cloudflare R2, GCS interop, or any S3-compatible target via `endpoint_url`. Verified end-to-end against MinIO.
- `network_share` — SMB/NFS wrapper. OS mounts; Studio checks mount presence + writes.
- `custom` — importlib loader. Customer ships their own driver in `~/.railcall/vault_drivers/`; config `{driver:"custom", module_ref:"pkg.mod:Cls"}` loads it at Studio boot.

**Fail-mode is fixed: always fall back to local.** Local write happens first (unchanged from v0.25). Vault mirror runs after in a swallowed try/except with stderr logs. Vault failure never breaks a governed run.

**Secrets never in the marketplace DB.** S3 access keys and custom-driver secrets are configured as **references** (`env:VAR`, `file:/path`, `keyring:label`) — the Studio-side driver resolves them at runtime. The marketplace explicitly rejects raw `*_key`/`*_secret` at the boundary with an actionable error.

## Also in v0.26

- **Air-gap install kit** (Enterprise plan Week 1) — `railcall_station_v0.26_airgap.tar.gz` for customers who cannot let outbound traffic reach railcall.ai. Every file listed in `MANIFEST.txt` with its sha256. Full offline install path.
- **Login unification** — the single `/signin` on railcall.ai now routes to the marketplace login; the CLI's gateway flow lives at `/cli-activate`. One login story per user.
- **HIPAA trust page** — `/trust/hipaa` documents BAA scope, technical controls, receipt-vault architecture. Buyable-tier compliance leave-behind.

## Post-cut additions (2026-07-25 same day)

The initial v0.26 cut was extended after Sami's audit turned up
enterprise gaps a CISO would name in a procurement review. All of
these landed the same day, on top of the tagged station tarball —
they're marketplace + storefront side, so they roll out via the
regular deploy chain, not the versioned release.

**Session invalidation:** `User.session_generation` bumps on member
removal + role demotion. `AuthService.invalidateAllSessions` revokes
every refresh token for the target user in the same transaction. Max
window from "you're fired" to "your JWT stops working" = 15 min
(access-TTL grace).

**Admin audit log:** `OrgAuditLog` append-only table + write hooks
on every admin mutation surface (invite / role change / member
removal / vault config / SCIM events / org export). Frontend at
`/marketplace/org/audit` with event-slug filter + keyset pagination.

**Vault admin UI:** `/marketplace/org/vault-config` — driver picker
with per-driver form fields. Refuses raw secrets at the input the
same way the API does; only `env:` / `file:` / `keyring:` references
accepted.

**SCIM group-map UI:** `/marketplace/org/dir-role-map` — add / edit /
remove (WorkOS group id → OrgRole) rows. Self-serve for the
customer's own admin (the staff endpoint at `/admin/orgs/:id/dir-role-map`
still exists for support-team bootstrap).

**API keys for CI/CD:** `/marketplace/settings/api-keys` — long-lived
tokens with `rc_ak_live_` prefix, sha256-hashed in the DB, per-key
scopes, optional expiration, best-effort `last_used_at`. Wired into
`listings.publish` (headless CI can publish modules); other endpoints
can adopt `BearerAuthGuard` when needed.

**Data export:** `GET /org/export` — GDPR Art. 20 / CCPA "right to
access" dump of everything the marketplace stores about the org.
Owner-only. Recorded in the audit log itself.

**Subprocessor list:** `/trust/subprocessors` — public per-vendor
cards (Render / WorkOS / Stripe / Resend / GitHub / Cloudflare) with
data categories, jurisdiction, notes. Includes vendor-management
policy summary + 30-day new-vendor notification commitment.

**Status page:** `/status` — live client-side probes of railcall.ai
+ marketplace API, auto-refresh every 30s.

## Verify

```
sha256_of_railcall_station.tar.gz = e90027bf8c28057fcb461ebda9dff7a577918ee11e764461e6c4c4f2585e6626
sha256_of_railcall_cli.py         = 9a607b4cb41987685573b1624a85f70264819e3a537b43ded3013364604bbc95
sha256_of_railcall_vault_drivers.py = 7ff6896532adcbcf8302039bafe403884f457d8fb2ed87320e8283c61f9df096
```

Every install.sh downloads is pinned above; a wire tamper fails the pin gate before anything reaches disk.

## Deferred to v0.27+

- `railcall_hosted` vault driver — requires a marketplace-side vault-ingest endpoint + storage decision. Separate design conversation.
- Weeks 13-16 of the Enterprise plan (SLA infra, BAA workflow, policy engine).
- Studio session picking up the org identity from JWT claims (marketplace org membership → Studio session context).
