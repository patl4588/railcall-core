#!/usr/bin/env python3
"""
Proof for the licensing authority endpoints — the server half of the paid tier.

Until these existed, `entitlement_authority.py` was wired to nothing: a paying
customer had no way to RECEIVE a licence. These tests drive the REAL FastAPI app
against a real SQLite DB, so they exercise auth, plan gating and the seed handling
rather than mocking them.

The property that matters most: a token minted by the server must verify under the
REAL station code, and must NOT activate on any other machine.

Run: python3 test_licensing_endpoints.py     (exit 0 iff every check passes)
"""
import os
import shutil
import sys
import tempfile

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-lic-")
    # Point the gateway at a throwaway DB and give it a TEST issuer seed before import.
    os.environ["RAILCALL_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"
    ISSUER_SEED = "11" * 32
    os.environ["RAILCALL_ISSUER_SEED"] = ISSUER_SEED

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print("• SKIP — fastapi TestClient unavailable: %r" % (e,))
        return 0

    import cloud_gateway as G           # noqa: E402
    import entitlement_authority as EA  # noqa: E402

    # DB_PATH is a module constant, not an env var, and defaults to a file in the CWD.
    # Point it at the throwaway dir BEFORE any connection so the test never writes a
    # database into the repo (and never inherits rows from a previous run).
    # (init_db() already ran at import against the default path; re-run it here so the
    # throwaway DB gets the full schema.)
    G.DB_PATH = os.path.join(tmp, "test.db")
    G.init_db()

    client = TestClient(G.app)

    # A station-side verifier: the REAL engine code, not a reimplementation.
    # Prefer the engine repo — the installed station may predate the paid tier.
    # This is NOT optional: the cross-repo property (a server-minted token verifying
    # under the shipped station code) is the whole point of this file. If the module
    # cannot be found we FAIL, never silently skip — a green run that quietly dropped
    # its most important assertion is the fake-green this project forbids.
    engine_root = os.environ.get("RAILCALL_ENGINE") or os.path.expanduser("~/raill/railcall-engine")
    for root in (engine_root, os.path.expanduser("~/.railcall/station")):
        prim = os.path.join(root, "workbench", "primitives")
        if os.path.isfile(os.path.join(prim, "entitlement.py")):
            # entitlement.py imports railcall_signing, which lives one level up
            sys.path.insert(0, os.path.join(root, "workbench"))
            sys.path.insert(0, prim)
            sys.path.insert(0, root)
            break
    try:
        import entitlement as STATION   # the real station verify path
    except Exception as e:
        print("✗ SETUP: cannot import the station verify module (%r).\n"
              "    Set RAILCALL_ENGINE to the engine checkout. Refusing to report a "
              "pass without the cross-repo check." % (e,))
        return 1

    try:
        # ---- 1. transparency endpoint ------------------------------------------
        r = client.get("/v1/issuer/pubkey")
        ok("1a /v1/issuer/pubkey returns the issuer identity", r.status_code == 200, r.text[:200])
        ident = r.json()
        ok("1b it publishes a 32-byte ed25519 public key",
           len(bytes.fromhex(ident["public_key_hex"])) == 32)
        ok("1c it NEVER leaks the private seed",
           ISSUER_SEED not in r.text and "seed" not in r.text.lower(), r.text[:200])

        # ---- 2. auth + plan gating ---------------------------------------------
        INSTALL_PK = EA.issuer_identity("22" * 32)["public_key_hex"]   # a station pubkey
        r = client.post("/v1/entitlement/mint",
                        data={"api_key": "nope", "install_pubkey": INSTALL_PK})
        ok("2a unknown api key is rejected 401", r.status_code == 401, r.status_code)

        conn = G.db_connect()
        cur = G.db_cursor(conn)
        cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                         "plan, free_runs_remaining, runs_used, status) "
                         "VALUES (?,?,?,?,?,?,?,?,?)"),
                    ("free1", "free@x.com", "2026-01-01", "KEYFREE",
                     G._hash_key("KEYFREE"), "free", 10, 0, "active"))
        # NOTE the plan value: 'paid' is what the Stripe webhook ACTUALLY writes.
        # An earlier mint gated on 'team'/'enterprise' directly and would have 403'd
        # every real customer, because no row is ever set to 'team'. This row is the
        # regression guard for that.
        cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                         "plan, free_runs_remaining, runs_used, status) "
                         "VALUES (?,?,?,?,?,?,?,?,?)"),
                    ("org7", "paid@x.com", "2026-01-01", "KEYPAID",
                     G._hash_key("KEYPAID"), "paid", 0, 0, "active"))
        cur.execute(G.ph("INSERT INTO consumers (id, email, created_at, api_key, api_key_hash, "
                         "plan, free_runs_remaining, runs_used, status) "
                         "VALUES (?,?,?,?,?,?,?,?,?)"),
                    ("orgE", "ent@x.com", "2026-01-01", "KEYENT",
                     G._hash_key("KEYENT"), "enterprise", 0, 0, "active"))
        conn.commit()
        conn.close()

        ok("2z plan vocabulary maps: the webhook's 'paid' IS a paid tier",
           G._tier_for_plan("paid") == "team"
           and G._tier_for_plan("enterprise") == "enterprise"
           and G._tier_for_plan("free") is None
           and G._tier_for_plan(None) is None,
           {p: G._tier_for_plan(p) for p in ("paid", "team", "enterprise", "free", None)})

        r = client.post("/v1/entitlement/mint",
                        data={"api_key": "KEYFREE", "install_pubkey": INSTALL_PK})
        ok("2b a FREE plan cannot mint an entitlement (403)", r.status_code == 403, r.status_code)
        ok("2c the refusal is actionable, not generic",
           "upgrade" in r.text.lower(), r.text[:160])

        # ---- 3. paid mint -------------------------------------------------------
        r = client.post("/v1/entitlement/mint",
                        data={"api_key": "KEYPAID", "install_pubkey": INSTALL_PK})
        ok("3a a paid plan mints successfully", r.status_code == 200, r.text[:200])
        tok = r.json()["entitlement"]
        ok("3b a real Stripe customer (plan='paid') mints the TEAM tier",
           tok["tier"] == "team", tok.get("tier"))
        r2 = client.post("/v1/entitlement/mint",
                         data={"api_key": "KEYENT", "install_pubkey": INSTALL_PK})
        ok("3b' an enterprise contract mints the ENTERPRISE tier",
           r2.status_code == 200 and r2.json()["entitlement"]["tier"] == "enterprise",
           r2.text[:160])
        ok("3b'' tier is never taken from the caller",
           client.post("/v1/entitlement/mint",
                       data={"api_key": "KEYPAID", "install_pubkey": INSTALL_PK,
                             "tier": "enterprise"}).json()["entitlement"]["tier"] == "team")
        ok("3c org_id is the server's customer id, not caller-supplied",
           tok["org_id"] == "org7", tok.get("org_id"))
        ok("3d the token is BOUND to the install pubkey",
           tok.get("install_pubkey") == INSTALL_PK)
        ok("3e response never contains the issuer seed", ISSUER_SEED not in r.text)

        # ---- 4. THE CROSS-REPO PROPERTY: the real station accepts it ------------
        st = STATION.verify_entitlement(
            tok, issuer_pubkey_hex=ident["public_key_hex"],
            expected_install_pubkey=INSTALL_PK)
        ok("4a the REAL station verifies a server-minted token (byte-parity holds)",
           st.get("valid") and st.get("tier") == "team", st)
        # and the whole point of binding:
        other = STATION.verify_entitlement(
            tok, issuer_pubkey_hex=ident["public_key_hex"],
            expected_install_pubkey="ab" * 32)
        ok("4b the same token on ANOTHER machine degrades to free",
           other.get("tier") == "free" and "different install" in (other.get("reason") or ""),
           other)

        # ---- 5. countersignature ------------------------------------------------
        r = client.post("/v1/attestation/countersign",
                        data={"api_key": "KEYFREE", "external_integrity": "sha256:aa",
                              "attestation_id": "att1"})
        ok("5a countersign is refused on a free plan", r.status_code == 403, r.status_code)
        r = client.post("/v1/attestation/countersign",
                        data={"api_key": "KEYPAID", "external_integrity": "sha256:aa",
                              "attestation_id": "att1"})
        ok("5b countersign succeeds on a paid plan", r.status_code == 200, r.text[:200])
        cs = r.json()["countersignature"]
        ok("5c countersignature verifies offline against the issuer pubkey",
           EA.verify_countersignature(cs, issuer_pubkey_hex=ident["public_key_hex"]))
        ok("5d it does NOT verify against a non-issuer key",
           not EA.verify_countersignature(
               cs, issuer_pubkey_hex=EA.issuer_identity("33" * 32)["public_key_hex"]))

        # ---- 6. FAIL CLOSED without a seed -------------------------------------
        os.environ["RAILCALL_ISSUER_SEED"] = ""
        r = client.post("/v1/entitlement/mint",
                        data={"api_key": "KEYPAID", "install_pubkey": INSTALL_PK})
        ok("6a no issuer seed → 503, never an unsigned/self-signed token",
           r.status_code == 503, r.status_code)
        r = client.get("/v1/issuer/pubkey")
        ok("6b pubkey endpoint also fails closed", r.status_code == 503, r.status_code)
        os.environ["RAILCALL_ISSUER_SEED"] = ISSUER_SEED

        print()
        if FAILED:
            print("FAILED (%d): %s" % (len(FAILED), "; ".join(FAILED)))
            return 1
        print("ALL PASS — the gateway mints install-bound entitlements that the REAL "
              "station accepts, refuses free plans, derives tier/org from the DB rather "
              "than the caller, countersigns attestations verifiably offline, never "
              "leaks the issuer seed, and fails CLOSED when unconfigured.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
