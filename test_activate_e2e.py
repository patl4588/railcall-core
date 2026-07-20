#!/usr/bin/env python3
"""
End-to-end proof of the purchase chain: paid account → minted entitlement → installed
and active on THIS machine, and inert on any other.

This is the link that was missing. The gateway could mint and the station could verify,
but nothing connected them — a customer would have had to curl the endpoint by hand.

Runs a REAL gateway on a loopback port and drives the REAL CLI code path against it.
No mocks on either side of the wire.

Run: RAILCALL_ENGINE=/path/to/railcall-engine python3 test_activate_e2e.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-act-")
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    ISSUER_SEED = "44" * 32
    os.environ["RAILCALL_ISSUER_SEED"] = ISSUER_SEED
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"

    # --- a fake "installed station" the CLI will talk to -----------------------
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
    for f in ("entitlement.py",):
        shutil.copy(os.path.join(src_prim, f), os.path.join(station_wb, "primitives", f))
    for f in ("railcall_signing.py", "ed25519_pure.py"):
        s = os.path.join(engine, "workbench", f)
        if os.path.isfile(s):
            shutil.copy(s, os.path.join(station_wb, f))

    # a signing identity for this "install"
    sys.path.insert(0, station_wb)
    sys.path.insert(0, os.path.join(station_wb, "primitives"))
    import railcall_signing as SIGN            # noqa: E402
    SIGN._ROOT = os.path.dirname(station_wb)   # <station>/ so _ws() -> .railcall_workspace
    install_pub = SIGN.ensure_keypair()
    ok("0a the test install has a signing identity", bool(install_pub), install_pub)

    # --- a real gateway on loopback -------------------------------------------
    try:
        import uvicorn
    except Exception as e:
        print("✗ SETUP: uvicorn required (%r)" % (e,))
        return 1
    import cloud_gateway as G                  # noqa: E402
    import entitlement_authority as EA         # noqa: E402
    G.DB_PATH = os.path.join(tmp, "gw.db")
    G.init_db()

    conn = G.db_connect(); cur = G.db_cursor(conn)
    cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                     "plan, free_runs_remaining, runs_used, status) VALUES (?,?,?,?,?,?,?,?,?)"),
                ("orgZ", "buyer@x.com", "2026-01-01", "rc_live_TESTKEY",
                 G._hash_key("rc_live_TESTKEY"), "paid", 0, 0, "active"))
    conn.commit(); conn.close()

    port = 8791
    cfg = uvicorn.Config(G.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        if getattr(server, "started", False):
            break
        time.sleep(0.1)
    ok("0b gateway is up on loopback", getattr(server, "started", False))

    try:
        # --- drive the REAL CLI ------------------------------------------------
        os.environ["RAILCALL_GATEWAY_URL"] = "http://127.0.0.1:%d" % port
        os.environ["HOME"] = home              # CLI resolves ~ for station + token
        tokdir = os.path.join(home, ".config", "railcall")
        os.makedirs(tokdir, exist_ok=True)
        with open(os.path.join(tokdir, "token.json"), "w") as fh:
            json.dump({"api_key": "rc_live_TESTKEY"}, fh)

        import railcall_cli as CLI             # noqa: E402
        CLI.TOKEN_PATH = os.path.join(tokdir, "token.json")

        # The station PINS the production issuer public key (like a TLS root). This
        # test runs its own throwaway authority, so re-pin the module to the test
        # issuer. Without this the station correctly refuses the token — which is the
        # pin doing its job, and is why a mismatched seed in production would reject
        # every entitlement ever minted. See the deployment note in claude-context.md.
        _ent_mod = CLI._entitlement_module()
        _ent_mod.ISSUER_PUBKEY_HEX = EA.issuer_identity(ISSUER_SEED)["public_key_hex"]
        ok("0c the station pins an issuer key (production pin must match the seed)",
           bool(_ent_mod.ISSUER_PUBKEY_HEX))

        ok("1a install pubkey is readable and is the PUBLIC half only",
           CLI._install_pubkey_hex() == install_pub, CLI._install_pubkey_hex()[:16])

        rc = CLI.cmd_activate([])
        ok("1b `railcall activate` exits 0", rc == 0, rc)

        p = os.path.join(ws, "entitlement.json")
        ok("1c an entitlement was persisted", os.path.isfile(p))
        tok = json.load(open(p, encoding="utf-8"))
        ok("1d it is bound to THIS install", tok.get("install_pubkey") == install_pub)
        ok("1e tier came from the server (plan='paid' → team)", tok.get("tier") == "team", tok.get("tier"))

        ent = CLI._entitlement_module()
        st = ent.entitlement_state(ws)
        ok("1f the install now reports a PAID tier", st.get("tier") == "team" and st.get("valid"), st)
        ok("1g the private seed was never written into the entitlement",
           "seed" not in json.dumps(tok).lower())

        # --- status path ------------------------------------------------------
        ok("2a `activate --status` exits 0", CLI.cmd_activate(["--status"]) == 0)

        # --- THE BINDING: same token, different machine -----------------------
        other = ent.verify_entitlement(
            tok, issuer_pubkey_hex=EA.issuer_identity(ISSUER_SEED)["public_key_hex"],
            expected_install_pubkey="cd" * 32)
        ok("3a the SAME entitlement on another install degrades to free",
           other.get("tier") == "free", other)

        # --- a free account gets an actionable refusal, not a crash -----------
        conn = G.db_connect(); cur = G.db_cursor(conn)
        cur.execute(G.ph("UPDATE consumers SET plan = 'free' WHERE id = ?"), ("orgZ",))
        conn.commit(); conn.close()
        os.remove(p)
        rc = CLI.cmd_activate([])
        ok("4a a free plan fails cleanly (non-zero, no traceback)", rc == 1, rc)
        ok("4b nothing was persisted for a free plan", not os.path.isfile(p))

        print()
        if FAILED:
            print("FAILED (%d): %s" % (len(FAILED), "; ".join(FAILED)))
            return 1
        print("ALL PASS — the purchase chain closes end to end: a paid account mints an "
              "install-bound entitlement over a real gateway, the CLI installs it, the "
              "station reports the paid tier, the same token is inert on another "
              "install, and a free plan is refused cleanly.")
        return 0
    finally:
        try:
            server.should_exit = True
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
