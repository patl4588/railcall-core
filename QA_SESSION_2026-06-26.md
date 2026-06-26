# RailCall QA — 2026-06-26 session

Everything shipped today, live on **railcall.ai** (Pages) + **railcall-core.onrender.com** (gateway).
Each row: what to test, copy-paste steps, and the **exact** expected result. Mark PASS/FAIL.

> Read the **"Known by design — NOT bugs"** section at the bottom FIRST, so you don't file the
> intentional limits (free-run counter, team placeholders, gated admin) as defects.

---

## A. Signup / login gate  (railcall.ai)

| # | Test | Steps | Expected |
|---|------|-------|----------|
| A1 | Sign up needs a password | railcall.ai → **Sign Up** → enter email only → submit | Inline error: "Password must be at least 8 characters." |
| A2 | Confirm must match | email + password `Test12345` + confirm `nope` → submit | "Passwords do not match." |
| A3 | New account | email `qa+<n>@example.com` + password (8+) twice → **Create account** | Creates account, key saved, **download begins**, then redirects to /dashboard |
| A4 | Existing email | sign up again with the **same** email | "That email already has an account — enter your password to log in." (flips to Log in) |
| A5 | Log in wrong pw | toggle **Log in**, real email + wrong password | "Incorrect email or password." (no account-exists leak) |
| A6 | Looks legit | open the gate | Light card, lock + **Secure** badge, "no card to start." NOT the old dark terminal box |

## B. Password auth backend (copy-paste, no account created)
```bash
GW=https://railcall-core.onrender.com
# B1 missing pw -> 400
curl -s -o /dev/null -w "B1 %{http_code} (want 400)\n" -X POST "$GW/v1/auth/register" -H "Content-Type: application/json" -d '{"email":"x@example.com"}'
# B2 short pw -> 400
curl -s -o /dev/null -w "B2 %{http_code} (want 400)\n" -X POST "$GW/v1/auth/register" -H "Content-Type: application/json" -d '{"email":"x@example.com","password":"short"}'
# B3 unknown login -> 401 (no enumeration)
curl -s -o /dev/null -w "B3 %{http_code} (want 401)\n" -X POST "$GW/v1/auth/login" -H "Content-Type: application/json" -d '{"email":"ghost@example.com","password":"whatever12"}'
```

## C. Download = a real app  (the big one)
| # | Test | Steps | Expected |
|---|------|-------|----------|
| C1 | It's an app, not a folder | sign up → the download → unzip `RailCall-Studio.zip` | A single **"RailCall Studio"** app icon (Kind = Application), NOT a folder |
| C2 | First open (Gatekeeper) | double-click → "not opened" → **Done** (do NOT Trash) → System Settings → Privacy & Security → **Open Anyway** | App opens |
| C3 | It opens the Studio | after Open Anyway, open it again | Browser tab opens at `http://127.0.0.1:8799/v2`, Studio loads. No Terminal step |
| C4 | Guide present | the zip also contains | `OPEN ME FIRST.txt` with the Gatekeeper steps |

## D. Customer dashboard  (railcall.ai/dashboard, after signup or paste a key)
| # | Test | Expected |
|---|------|----------|
| D1 | Enterprise console | Left sidebar + tabs: **Workspace / Team / Security / Ledger & Billing**; tabs switch |
| D2 | Keys are masked | API key shows `rc_xxx_••••••••••••`; **Reveal** shows it, **Copy** grabs the full key |
| D3 | Billing on home | Workspace tab has a **Billing & balance** card next to runs (balance + Top Up + manage link) |
| D4 | Team is honest | Team tab shows **you** as the one Org Owner; invite is "provisioned per Enterprise — not self-serve yet" (see KD-4) |
| D5 | Security is honest | Security tab shows your (masked) key + the real governance model; scoped keys gated to Enterprise |

## E. `railcall audit` (CLI — the local zero-retention audit)
```bash
# E0 install (or re-run to update)
curl -fsSL https://railcall.ai/install.sh | bash
# E1 make a messy CSV
printf 'Date,Email,Phone,Amount\n2026-06-01,a@b.com,(555) 123-4567,"1,200.00"\n6/2/2026,,5551234567,N/A\n' > /tmp/qa.csv
# E2 audit it
railcall audit /tmp/qa.csv
```
**Expected E2:** a panel listing findings (PII email/phone, mixed Amount, inconsistent Date formats), then
`airlock ✓  0 external sockets`, and a `receipt … · ed25519-signed` line. Nothing is uploaded.

## F. Blind metering — PROVEN, re-run to confirm (copy-paste)
```bash
GW=https://railcall-core.onrender.com
EMAIL="qa-meter-$(date +%s)@example.com"
KEY=$(curl -s -X POST "$GW/v1/auth/signup" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
HASH=$(python3 -c "import hashlib;print(hashlib.sha256('$KEY'.encode()).hexdigest())")
bal(){ curl -s -X POST "$GW/v1/cli/login" -H "Content-Type: application/json" -d "{\"api_key\":\"$KEY\"}" | python3 -c "import sys,json;d=json.load(sys.stdin);print('used',d['used_runs'],'remaining',d['remaining_runs'])"; }
echo "before: $(bal)"                                                                 # used 0 remaining 100
curl -s -X POST "$GW/meter" -H "Content-Type: application/json" -d "{\"key_hash\":\"$HASH\",\"nonce\":\"qa1\",\"action\":\"decrement_run\"}"; echo
echo "after 1: $(bal)"                                                                # used 1 remaining 99
curl -s -X POST "$GW/meter" -H "Content-Type: application/json" -d "{\"key_hash\":\"$HASH\",\"nonce\":\"qa1\",\"action\":\"decrement_run\"}"; echo  # duplicate ignored
echo "after replay: $(bal)"                                                           # STILL used 1 remaining 99
```
**Expected:** decrements per run; same nonce = "duplicate ignored" with no double-charge. **The raw key is
never sent** — only its SHA-256 hash. (Confirm in Wireshark/Charles: the `/meter` body has `key_hash`, not `api_key`.)

## G. Landing copy (railcall.ai) — accuracy check
| # | Expected on the page |
|---|----------------------|
| G1 | Hero: "you own 100% of the generated code … blind cash register … $0.005 … physically incapable of reading your keys, files, or data" |
| G2 | Overlay headline: "Build custom programs. Reverse-integrate either way." |
| G3 | Sovereignty: "Zero data-bearing sockets during processing" + "Open Wireshark and audit the packets live … transaction register, not a data sink" |
| G4 | Checklist has 6 items (code ownership, blind infra, bi-directional, $0.005/run, no fake green, no investor owns a vote) |

## H. Docs (railcall.ai/docs.html)
- H1: Quickstart includes `railcall audit data.csv`.
- H2: FAQ has "What is railcall audit?" and "Does RailCall send my data when it meters a run?"

## I. Admin dash (LOCAL / protected only — see KD-3)
- I1: with the gateway running `RAILCALL_LOCAL_ADMIN=1`, open `/admin` → KPI cards (consumers, runs metered, est revenue, Groq), top accounts, by-status, recent activity.
- I2: on **public prod** (no flag), `/admin` and `/api/dashboard_data` → **404** (correct — it lists every consumer).

---

## Known by design — NOT bugs (do not file these)
- **KD-1 · Free-run counter reads 0 on the dashboard.** The CLI only meters **paid** (`rc_live_`) runs; free-trial runs are enforced locally (offline-friendly) and never ping the gateway. The metering itself is proven (section F). Pending decision: meter free runs too.
- **KD-2 · The `.app` is unsigned** → first open needs Gatekeeper "Open Anyway" (C2). A no-warning build needs an Apple Developer cert (Pat's enrollment, in progress).
- **KD-3 · `/admin` is 404 in public production** — it's gated to a local/protected instance because it lists every consumer.
- **KD-4 · Team tab has no working invite/add-user yet.** Multi-tenant orgs/members/invites are a backend build that is NOT done; the tab shows honest "per-contract" placeholders, not mock users.
- **KD-5 · The Studio's own metering (`billing_telemetry`) is still the legacy form** — it works via gateway backward-compat but isn't blind yet (CLI is). Blind upgrade is a follow-up.

## Key commits (railcall-core main)
auth `d95e446` · gate `b3f599a` · optimize `1b9e31c` · console `4646cb9` · keys+billing-home `975b30c` ·
download.app `f6cb29b`/`d7c008d` · signup-dl-fix `6880336` · ed25519 `74836c4` · blind /meter `0860616` ·
railcall audit `5740fe8` · landing copy `eb61858` · admin `b401766` · docs `5138d40`
