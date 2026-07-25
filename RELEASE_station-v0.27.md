# RailCall Station v0.27 — headless CLI auth (API keys in the terminal)

**Status:** cut. Small, focused release on top of v0.26.

v0.26 shipped the marketplace-side API-key surface (create/list/revoke +
`BearerAuthGuard` on `listings.publish`). This release closes the loop
by making those keys usable from the CLI without opening a browser —
the actual CI/CD story customers care about.

## What's new (CLI-side)

**1. `railcall market api-keys` subcommand.** Three verbs, all direct
mappings of the web-UI surface at `/marketplace/settings/api-keys`:

```
railcall market api-keys list
railcall market api-keys create <name> [scopes]
railcall market api-keys revoke <id>
```

Fresh secret prints ONCE to stdout on create (matches the web UI's
one-shot banner). Standard `panel()` output; scriptable if a caller
wants to grep the `rc_ak_live_…` line out of stdout.

**2. `RAILCALL_API_KEY` environment variable.** Every marketplace-authed
command now checks the env var first and falls back to the interactive
session (`railcall market login`) only when it's unset. Precedence is
deliberate: if the key is set but rejected, we DON'T silently downgrade
to the session — that would mask credential misconfigs in CI/CD (worst
class of debugging).

Typical CI/CD flow:

```
export RAILCALL_API_KEY=$(op read op://vault/railcall/api_key)  # 1Password
railcall market publish path/to/module.json                     # signed publish
```

Zero shell state. No cookies, no session files, no browser.

**3. api-keys management endpoints refuse API-key auth.** Deliberate
guard against the lateral privilege loop: an API key can't mint or
revoke other API keys. If the CLI detects `RAILCALL_API_KEY` is set
during an `api-keys` subcommand, it prints an actionable message
pointing the user at `railcall market login` OR the web UI, instead of
firing the request and returning a confusing 401.

## Also in v0.27 (marketplace + website side, deployed already)

Everything in the "Post-cut additions" section of the v0.26 release
notes remains live and untouched. Nothing on the marketplace side
requires a station re-download to work — the CLI just talks to the
production API. Recap:

- Session invalidation on member removal / role demotion
- Admin audit log (`OrgAuditLog` + `/org/audit` + `/marketplace/org/audit` viewer)
- Vault admin UI + SCIM group-map UI
- `/trust/subprocessors` page + SOC 2 status
- `POST /auth/api-keys` + `BearerAuthGuard` wired into `listings.publish`
- `GET /org/export` (GDPR Art. 20)
- `/status` live-probe page

## Verify

```
sha256_of_railcall_station.tar.gz  = c519d6b1085fb8e20d9c100baf85754200363d7dc34d46a79105ad5c9d8afa2d
sha256_of_railcall_cli.py          = 1ea60913e9ba5a9ceb8798aa01ac33ac01e3b80eeea2c998a596333070536f1f
sha256_of_railcall_vault_drivers.py = 7ff6896532adcbcf8302039bafe403884f457d8fb2ed87320e8283c61f9df096
```

Every other file pin (governance package, signer, companion daemon,
vault_io) is unchanged since v0.26 — cross-verified before the cut.

## Deferred to v0.28+

- `railcall audit view` — CLI wrapper around `GET /org/audit` so
  admins can grep the audit log from the terminal.
- `railcall org export` — CLI wrapper around `GET /org/export`.
- Studio session picking up the org identity from the JWT / API key
  (today the Studio side reads `~/.railcall/marketplace_session.json`
  directly; API-key-only setups need a small refactor).
