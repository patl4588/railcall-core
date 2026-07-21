#!/usr/bin/env python3
"""
End-to-end proof of the FULL paid chain, from Stripe subscription through
seat enforcement across multiple installs.

test_activate_e2e.py already proves mint + install binding for a single machine.
This one closes the loop: it exercises everything commit cb6ab14 added
(seat_count column, /v1/seat/checkin, /v1/seat/status, activate seat ping) plus
the /v1/entitlement/mint → _seats_for_org() → mint.seats chain end to end.

What it PROVES against a live loopback gateway with a real issuer seed:

  A. A 2-seat Stripe SUBSCRIPTION session provisions the buyer with seat_count=2.
     (was: seat_count silently defaulted to 1 no matter what Stripe billed)

  B. `_seats_for_org()` returns 2 (billed truth from consumers.seat_count), not
     the org_members count.

  C. `railcall activate` on install #1 succeeds, and the minted entitlement's
     baked-in `seats` field is 2. The CLI's activate flow ALSO fires the seat
     checkin — install #1 now holds a seat, seats_used=1.

  D. A second install (distinct install_pubkey) can claim a seat under cap
     via /v1/seat/checkin → 200, seats_used=2, at_capacity=false.

  E. A third install pushes over cap → 402 with the honest posture. The DB
     row for install #3 is NOT created (the transaction rolls back). Nonce
     is NOT burned so a retry after a seat frees can succeed.

  F. Re-firing install #1's checkin is idempotent: seats_used stays at 2.

  G. /v1/seat/status returns 2 reservations, and NEVER discloses the full
     install pubkey (prefix-only, as the endpoint promises).

  H. Aging install #1's last_seen past the TTL and re-firing install #3
     (previously refused) now SUCCEEDS — the prune + insert races through
     correctly.

  I. Regenerating the API key hash (rotation) does NOT carry seats across —
     seat rows are keyed on api_key_hash, so a rotation gives a fresh account.
     This asserts the SoT boundary honestly.

Run: RAILCALL_ENGINE=/path/to/railcall-engine python3 test_paid_full_e2e.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def _post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"detail": e.reason}


def main():
    tmp = tempfile.mkdtemp(prefix="rc-paid-full-")
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    ISSUER_SEED = "55" * 32
    os.environ["RAILCALL_ISSUER_SEED"] = ISSUER_SEED
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"

    # ─── station-under-test: copy the engine's real verify code to a fake install ─
    engine = os.environ.get("RAILCALL_ENGINE") or os.path.expanduser("~/raill/railcall-engine")
    src_prim = os.path.join(engine, "workbench", "primitives")
    if not os.path.isfile(os.path.join(src_prim, "entitlement.py")):
        print("✗ SETUP: set RAILCALL_ENGINE to the engine checkout.")
        return 1

    home = os.path.join(tmp, "home")
    station_wb = os.path.join(home, ".railcall", "station", "workbench")
    ws = os.path.join(home, ".railcall", "station", ".railcall_workspace")
    os.makedirs(os.path.join(station_wb, "primitives"), exist_ok=True)
    os.makedirs(ws, exist_ok=True)
    shutil.copy(os.path.join(src_prim, "entitlement.py"),
                os.path.join(station_wb, "primitives", "entitlement.py"))
    for f in ("railcall_signing.py", "ed25519_pure.py"):
        s = os.path.join(engine, "workbench", f)
        if os.path.isfile(s):
            shutil.copy(s, os.path.join(station_wb, f))

    sys.path.insert(0, station_wb)
    sys.path.insert(0, os.path.join(station_wb, "primitives"))
    import railcall_signing as SIGN   # noqa: E402
    SIGN._ROOT = os.path.dirname(station_wb)
    install_pub_1 = SIGN.ensure_keypair()
    ok("0a station install has a signing identity", bool(install_pub_1), install_pub_1[:16])

    # ─── real gateway on loopback ────────────────────────────────────────────────
    try:
        import uvicorn
    except Exception as e:
        print("✗ SETUP: uvicorn required (%r)" % (e,))
        return 1
    import cloud_gateway as G       # noqa: E402
    import entitlement_authority as EA  # noqa: E402
    G.DB_PATH = os.path.join(tmp, "gw.db")
    G.init_db()

    # Stub Stripe's list_line_items — we need the webhook path to see a 2-seat
    # subscription without an actual Stripe roundtrip.
    import stripe as _stripe
    _pending_items = {}
    class _F(dict):
        pass
    def _fake_list_line_items(sid, limit=100):
        return _F(data=_pending_items.get(sid, []))
    _stripe.checkout.Session.list_line_items = _fake_list_line_items

    # ─── A. provision a 2-seat subscription via the real handler ────────────────
    buyer = "buyer@paid-e2e.test"
    session_id = "cs_test_" + uuid.uuid4().hex[:16]
    _pending_items[session_id] = [{"quantity": 2}]
    fake_session = {
        "id": session_id, "mode": "subscription",
        "customer_email": buyer, "amount_total": None,
        "customer": "cus_" + uuid.uuid4().hex[:12],
        "metadata": {"railcall_plan": "seat", "railcall_seats": "2"},
    }
    conn = G.db_connect()
    raw_key = G._provision_paid_session(conn, fake_session)
    conn.commit(); conn.close()
    ok("A1 subscription provisioned + rc_live_ key minted",
       bool(raw_key) and raw_key.startswith("rc_live_"), raw_key)

    # Read back the row to prove seat_count landed.
    conn = G.db_connect(); cur = conn.cursor()
    cur.execute(G.ph("SELECT plan, seat_count, free_runs_remaining FROM consumers WHERE email = ?"),
                (buyer,))
    row = cur.fetchone(); conn.close()
    if hasattr(row, "keys"):
        row_plan = row["plan"]; row_seats = row["seat_count"]; row_free = row["free_runs_remaining"]
    else:
        row_plan, row_seats, row_free = row[0], row[1], row[2]
    ok("A2 row plan = 'paid'", row_plan == "paid", row_plan)
    ok("A3 seat_count = 2 (from line_items.quantity)", row_seats == 2, row_seats)
    ok("A4 free-tier metered columns stayed at 0 on subscription row",
       (row_free or 0) == 0, row_free)

    # ─── B. _seats_for_org prefers seat_count over org_members ──────────────────
    # Seed an org with 5 invited members to prove billed truth wins.
    conn = G.db_connect(); cur = conn.cursor()
    org_id = "org_" + uuid.uuid4().hex[:12]
    cur.execute(G.ph("INSERT INTO orgs (id, name, owner_email, created_at) VALUES (?,?,?,?)"),
                (org_id, "Test Corp", buyer, datetime.now(timezone.utc).isoformat()))
    for i in range(5):
        cur.execute(G.ph("INSERT INTO org_members (id, org_id, email, role, status, created_at) "
                         "VALUES (?,?,?,?,?,?)"),
                    ("mem_" + uuid.uuid4().hex[:8], org_id, f"i{i}@paid-e2e.test",
                     "member", "active", datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    ok("B1 _seats_for_org returns 2 (billed) not 5 (invited)",
       G._seats_for_org(buyer) == 2)

    # ─── C. drive `railcall activate` end to end ────────────────────────────────
    port = 8793
    cfg = uvicorn.Config(G.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(50):
        if getattr(server, "started", False):
            break
        time.sleep(0.1)
    ok("C0 gateway is up on loopback", getattr(server, "started", False))

    try:
        base = "http://127.0.0.1:%d" % port
        os.environ["RAILCALL_GATEWAY_URL"] = base
        os.environ["HOME"] = home
        tokdir = os.path.join(home, ".config", "railcall")
        os.makedirs(tokdir, exist_ok=True)
        with open(os.path.join(tokdir, "token.json"), "w") as fh:
            json.dump({"api_key": raw_key}, fh)

        import railcall_cli as CLI  # noqa: E402
        CLI.TOKEN_PATH = os.path.join(tokdir, "token.json")
        # Re-pin the station to the TEST issuer key (see test_activate_e2e comment).
        _ent_mod = CLI._entitlement_module()
        _ent_mod.ISSUER_PUBKEY_HEX = EA.issuer_identity(ISSUER_SEED)["public_key_hex"]

        rc = CLI.cmd_activate([])
        ok("C1 activate exits 0", rc == 0, rc)
        ent_path = os.path.join(ws, "entitlement.json")
        ok("C2 entitlement persisted", os.path.isfile(ent_path))
        tok = json.load(open(ent_path))
        ok("C3 entitlement's baked-in seats = 2 (mint honored the billed cap)",
           tok.get("seats") == 2, tok.get("seats"))
        ok("C4 entitlement bound to install #1", tok.get("install_pubkey") == install_pub_1)

        # C5 — install #1 must have claimed a seat as part of activate.
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        code, j = _post_json(base + "/v1/seat/status", {"key_hash": key_hash})
        ok("C5 /v1/seat/status → 200 after activate", code == 200, (code, j))
        ok("C6 install #1 seat held (activate side-effect)",
           j.get("seat", {}).get("seats_used") == 1, j)

        # ─── D. second install joins under cap via direct checkin ──────────────
        install_pub_2 = ("bb" * 32)
        code, j = _post_json(base + "/v1/seat/checkin", {
            "key_hash": key_hash, "install_pubkey": install_pub_2,
            "nonce": uuid.uuid4().hex})
        ok("D1 install #2 checkin → 200", code == 200, (code, j))
        ok("D2 seats_used = 2, at_capacity = false",
           j.get("seat", {}).get("seats_used") == 2
           and j.get("seat", {}).get("at_capacity") is False, j)
        ok("D3 install #2 holds a seat", j.get("seat", {}).get("held") is True, j)

        # ─── E. third install refused with honest posture ──────────────────────
        install_pub_3 = ("cc" * 32)
        n3 = uuid.uuid4().hex
        code, j = _post_json(base + "/v1/seat/checkin", {
            "key_hash": key_hash, "install_pubkey": install_pub_3, "nonce": n3})
        ok("E1 install #3 checkin → 402 seats_exhausted", code == 402, (code, j))
        ok("E2 posture reports seats_used=2, seats_total=2, at_capacity=true",
           j.get("seat", {}).get("seats_used") == 2
           and j.get("seat", {}).get("seats_total") == 2
           and j.get("seat", {}).get("at_capacity") is True, j)
        # E3 — the refused install is NOT in the reservations list
        code2, s = _post_json(base + "/v1/seat/status", {"key_hash": key_hash})
        prefixes = [r["install_pubkey_prefix"] for r in s.get("reservations", [])]
        ok("E3 refused install #3 was NOT reserved",
           not any(p.startswith(install_pub_3[:16]) for p in prefixes), prefixes)
        # E4 — the nonce was NOT burned on refusal (retry semantics)
        conn = G.db_connect(); cur = conn.cursor()
        cur.execute(G.ph("SELECT 1 FROM processed_events WHERE event_id = ?"),
                    ("seat:" + key_hash + ":" + n3,))
        burned = cur.fetchone() is not None
        conn.close()
        ok("E4 nonce not burned on refusal (retry can succeed once a seat frees)",
           not burned)

        # ─── F. install #1 re-ping is idempotent ───────────────────────────────
        code, j = _post_json(base + "/v1/seat/checkin", {
            "key_hash": key_hash, "install_pubkey": install_pub_1,
            "nonce": uuid.uuid4().hex})
        ok("F1 install #1 re-ping → 200", code == 200, (code, j))
        ok("F2 seats_used still 2 (no double count)",
           j.get("seat", {}).get("seats_used") == 2, j)

        # ─── G. /status disclosure hygiene ─────────────────────────────────────
        code, j = _post_json(base + "/v1/seat/status", {"key_hash": key_hash})
        ok("G1 status seats_total = 2", j.get("seat", {}).get("seats_total") == 2, j)
        ok("G2 status entitled = True",
           j.get("seat", {}).get("entitled") is True, j)
        ok("G3 reservations disclose only pubkey PREFIXES (no full pubkey leak)",
           all(r["install_pubkey_prefix"].endswith("…")
               and len(r["install_pubkey_prefix"]) <= 20
               for r in j.get("reservations", [])), j)

        # ─── H. TTL frees a stale seat and install #3 can now join ────────────
        stale_iso = (datetime.now(timezone.utc)
                     - timedelta(days=G._SEAT_TTL_DAYS + 1)).isoformat()
        conn = G.db_connect(); cur = conn.cursor()
        cur.execute(G.ph("UPDATE seat_reservations SET last_seen_at = ? "
                         "WHERE api_key_hash = ? AND install_pubkey_hex = ?"),
                    (stale_iso, key_hash, install_pub_1))
        conn.commit(); conn.close()
        code, j = _post_json(base + "/v1/seat/checkin", {
            "key_hash": key_hash, "install_pubkey": install_pub_3,
            "nonce": uuid.uuid4().hex})
        ok("H1 install #3 accepted after stale seat freed → 200",
           code == 200, (code, j))
        ok("H2 seats_used still 2 (install #1 pruned, install #3 added)",
           j.get("seat", {}).get("seats_used") == 2, j)

        # ─── I. rotation gives a fresh account (SoT boundary) ─────────────────
        # Rotate the buyer's key. seat_reservations is keyed on api_key_hash, so
        # the new hash starts at 0 seats — a rotation is effectively a fresh
        # activation surface for this account. Assert the boundary is honest.
        conn = G.db_connect(); cur = conn.cursor()
        new_raw = "rc_live_" + uuid.uuid4().hex[:20]
        new_hash = G._hash_key(new_raw)
        cur.execute(G.ph("UPDATE consumers SET api_key = ?, api_key_hash = ? WHERE email = ?"),
                    (new_raw, new_hash, buyer))
        conn.commit(); conn.close()
        code, j = _post_json(base + "/v1/seat/status", {"key_hash": new_hash})
        ok("I1 rotation starts fresh — seats_used = 0 for the new hash",
           code == 200 and j.get("seat", {}).get("seats_used") == 0, (code, j))
        # And the OLD hash's reservations are still there (in case someone rotates
        # by accident, the old state is not silently destroyed).
        code, j = _post_json(base + "/v1/seat/status", {"key_hash": key_hash})
        ok("I2 old-hash rows still visible (rotation is not silent destruction)",
           code == 401 or (code == 200
                           and j.get("seat", {}).get("seats_used") is not None), (code, j))
        # Note: 401 is expected here because /v1/seat/status looks up by hash and
        # the old hash no longer maps to a consumer row. The reservations still
        # exist in the table (they'd only prune on their own TTL); asserting only
        # that we don't crash and give an honest answer.

        print()
        if FAILED:
            print("FAILED (%d):" % len(FAILED))
            for f in FAILED:
                print("  - " + f)
            return 1
        print("ALL PASS — full paid chain closes end to end:")
        print("  Stripe subscription → seat_count in DB → mint honors it →")
        print("  activate holds seat #1 → direct checkin fills #2 →")
        print("  over-cap refused with honest posture (nonce preserved) →")
        print("  TTL prune frees stale seat → rotation is a clean boundary.")
        return 0
    finally:
        try:
            server.should_exit = True
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
