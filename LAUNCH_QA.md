# RailCall — Launch QA Manual (Human End-to-End)

**For:** Nick · **Backend:** `cloud_gateway.py` on Render (`railcall-core.onrender.com`, Postgres) · **Web:** `railcall.ai` (Pages)
**Live config:** Billing Portal configuration `bpc_1TlcOnK4wE8d2pNXydWZ6DpR` (code-defined, cached)
**How to use:** run each step in order; mark ✅/❌ against the **Expect** line. A ❌ with the actual output beats a guessed ✅. Don't skip the Integrity phase.

Key formats: free = `rc_free_…`, paid = `rc_live_…`. Gateway base = `https://railcall-core.onrender.com`.

---

## PHASE 1 — FREE PATH (web → terminal)

| # | Action | Expect |
|---|--------|--------|
| 1.1 | On `railcall.ai`, open the email gate, enter a **fresh** email, submit | Redirects to `/dashboard` |
| 1.2 | Read the dashboard | `rc_free_…` key shown · tier badge **free** · meter **`0 / 100 runs`** · light "Ledger & Billing" card on the right |
| 1.3 | Click **Copy** on the key and on each command | Each shows "Copied" |
| 1.4 | Terminal: `curl -fsSL https://railcall.ai/install.sh \| bash` | CLI installs, no errors |
| 1.5 | `railcall login <rc_free_…>` | Prints authenticated · tier **free** · **100 remaining** |
| 1.6 | Re-enter the **same** email at the gate | Returns the **same** `rc_free_…` key (no duplicate, no second account) |

**API truth check (optional):** `curl -s -X POST $GW/v1/cli/login -H 'Content-Type: application/json' -d '{"api_key":"rc_free_…"}'`
→ `{"authenticated":true,"tier":"free","remaining_runs":100,"allocated_runs":100,"used_runs":0}`

---

## PHASE 2 — PAID PATH (Stripe checkout → terminal)

| # | Action | Expect |
|---|--------|--------|
| 2.1 | From the dashboard/pricing, click **Top Up Balance** | Opens the Stripe checkout (`buy.stripe.com/3cI14o…`) |
| 2.2 | Pay **$10** (real card or Stripe test mode), using the **same email** as your account | Stripe confirms payment |
| 2.3 | Land on `/success` then `/dashboard` | Shows `rc_live_…` key · tier **paid** · meter reflects **1,000 runs** ($10 → 1000; 1¢ = 1 run) |
| 2.4 | `railcall login <rc_live_…>` | Authenticated · tier **paid** · **1,000 remaining** |
| 2.5 | Buy **again** with the same email | Balance **accumulates** (e.g. 1,000 → 2,000), not reset |

> Note: paid balance is **dynamic** = the cents you paid. $10→1000, $50→5000, $70→7000. There is no fixed pack size.

---

## PHASE 3 — MANAGEMENT PATH (Stripe Customer Portal)

| # | Action | Expect |
|---|--------|--------|
| 3.1 | On the dashboard as a **paid** user, click **Stripe Customer Portal** | Redirects to a real `billing.stripe.com/p/session/…` portal |
| 3.2 | Inspect the portal layout | Code-defined config: **Invoice history**, **Payment methods** (add/swap card), **Customer info** (business **email**, **address**, **Tax ID**) |
| 3.3 | Add/update a **payment method** | Saves; reflected in Stripe Dashboard → Customers |
| 3.4 | Add a corporate **Tax ID** + business **address** | Saves on the Customer |
| 3.5 | Click **Return** (top-left / footer) | Lands back on `railcall.ai/dashboard` (the `default_return_url`) |
| 3.6 | As a **free** user, click the portal control | Stays disabled / "Opens after your first top-up" — **no** portal, **no** error |

**API truth check:** `curl -s -X POST $GW/v1/billing/portal -H 'Content-Type: application/json' -d '{"api_key":"rc_live_…"}'`
→ `{"portal_url":"https://billing.stripe.com/…","configuration":"bpc_1TlcOnK4wE8d2pNXydWZ6DpR"}`
Same call with a `rc_free_…` key → `{"portal_url":null,"reason":"no_purchases", …}` (HTTP 200, honest).

> Known limit: invoice history may be **empty** for one-time top-ups bought via the Payment Link (one-time charges don't create Stripe invoices). Receipts still arrive by email. To populate the portal's invoice list, enable **invoice creation** on the Payment Link / checkout in Stripe.

---

## PHASE 4 — SYSTEM INTEGRITY CHECKS

| # | Check | Command / Action | Expect |
|---|-------|------------------|--------|
| 4.1 | Metering decrements server-side | Run a governed flow on a paid key, refresh dashboard | **Used** ↑, **Remaining** ↓, **Allocated** unchanged |
| 4.2 | Allocated is immutable | After several runs | `allocated_runs` never moves (only used/remaining do) |
| 4.3 | Idempotency | Re-send the same metered run (same idempotency key) | Booked once; duplicate ignored |
| 4.4 | Webhook signature | `curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/webhooks/stripe -H 'stripe-signature: t=1,v1=bad' -d '{}'` | **400** (rejects unsigned/forged) |
| 4.5 | Error boundaries | unknown route / missing email / bad key | **404** / **400** / **401** (never a raw 500 stack) |
| 4.6 | CORS | preflight from a non-railcall origin | No `Access-Control-Allow-Origin` echoed; `railcall.ai` is allowed |
| 4.7 | Health | `curl -s $GW/health` | `{"status":"ONLINE","db_mode":"PostgreSQL",…}` |
| 4.8 | Dashboard hygiene | DevTools → Network on `/dashboard` | Zero third-party/CDN loads; resize < 820px → single-column stack |

---

## PHASE 5 — TEAM (multi-tenant orgs)

Structural isolation: every endpoint derives the org from the **caller's key**. One tenant can never
see or touch another's members.

| # | Check | Command / Action | Expect |
|---|-------|------------------|--------|
| 5.1 | Owner sees their org | `/dashboard` → **Team** tab | You listed as **Owner / Active**; no Remove on the owner |
| 5.2 | Invite a new email | Team → enter `mate@ex.com` + role → **Send invite** | `accept.html?token=…` link returned; invitee shows **Pending** |
| 5.3 | Accept | open the link → "join &lt;Org&gt; as &lt;role&gt;" → set password (8+) → **Accept** | Invitee gets their own key + 100 runs, lands on `/dashboard` |
| 5.4 | Now active | reopen the owner's Team tab | invitee is **Active** with their role |
| 5.5 | Remove / Cancel | Remove a member / Cancel a pending invite | row disappears |
| 5.6 | RBAC | invite while signed in as a Developer/Auditor | **403** (only owner/admin can invite) |
| 5.7 | **Isolation** | two orgs A & B; from B call `/v1/team/members`, then try to remove A's member | B sees **only B's** members; B removing A's member → **404** |
| 5.8 | Replay | re-accept a used token | **404** (one-time) |

Quick isolation proof (copy-paste):
```bash
GW=https://railcall-core.onrender.com ; TS=$(date +%s)
g(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))"; }
A=$(curl -s -X POST "$GW/v1/auth/signup" -H 'Content-Type: application/json' -d "{\"email\":\"a-$TS@ex.com\"}"|g api_key)
B=$(curl -s -X POST "$GW/v1/auth/signup" -H 'Content-Type: application/json' -d "{\"email\":\"b-$TS@ex.com\"}"|g api_key)
T=$(curl -s -X POST "$GW/v1/team/invite" -H 'Content-Type: application/json' -d "{\"api_key\":\"$A\",\"email\":\"al-$TS@ex.com\",\"role\":\"developer\"}"|g invite_url|sed 's/.*token=//')
curl -s -X POST "$GW/v1/team/accept" -H 'Content-Type: application/json' -d "{\"token\":\"$T\",\"password\":\"passw0rd12\"}">/dev/null
echo "B sees only B (must NOT contain al-…):"; curl -s -X POST "$GW/v1/team/members" -H 'Content-Type: application/json' -d "{\"api_key\":\"$B\"}"
```

---

### Sign-off
- [ ] Phase 1 Free Path ✅
- [ ] Phase 2 Paid Path ✅
- [ ] Phase 3 Management Path ✅
- [ ] Phase 4 Integrity ✅
- [ ] Phase 5 Team ✅

Report any ❌ with the actual output (status code / JSON / screenshot). Known non-blockers tracked separately: plaintext key storage (hash at rest), no overspend floor on `/meter`, and reconciling the "enforced locally" vs "Server-verified" free-tier wording.
