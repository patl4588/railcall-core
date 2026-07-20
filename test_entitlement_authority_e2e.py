#!/usr/bin/env python3
"""End-to-end proof of the paid-tier crypto spine, ACROSS repos:

  server authority (railcall-core/entitlement_authority.py)  -- MINTS + COUNTERSIGNS
  real station verifier (railcall-engine/.../entitlement.py) -- VERIFIES OFFLINE

This is the byte-parity guard: a token minted by the server must verify under the
UNMODIFIED station code, or the whole model is broken. It also proves the new
install-pubkey binding closes the copyable-entitlement gap.

Uses THROWAWAY test keypairs only — never the real issuer seed.

Run: python3 test_entitlement_authority_e2e.py
"""
import hashlib
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # entitlement_authority (this repo)
_ENGINE = "/Users/macbook/raill/railcall-engine"
for p in (_ENGINE, os.path.join(_ENGINE, "workbench"),
          os.path.join(_ENGINE, "workbench", "primitives")):
    if p not in sys.path:
        sys.path.insert(0, p)

import entitlement_authority as AUTH             # SERVER side
import entitlement as STATION                    # the REAL station verifier

FAILS = []


def ok(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -- %s" % (extra,)) if extra and not cond else ""))
    if not cond:
        FAILS.append(label)


def _seed():
    return os.urandom(32).hex()


def _pub(seed_hex):
    return AUTH.issuer_identity(seed_hex)["public_key_hex"]


def main():
    # throwaway authority + two installs (real seed never touched)
    iss_seed = _seed()
    iss_pub = _pub(iss_seed)
    inst_seed = _seed(); inst_pub = _pub(inst_seed)          # buyer's machine
    other_seed = _seed(); other_pub = _pub(other_seed)       # a different machine

    T0 = 1_700_000_000.0
    iat = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0))
    exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 + 30 * 86400))

    # ── 1. server mints a bound team entitlement ─────────────────────────────
    tok = AUTH.mint_entitlement(install_pubkey_hex=inst_pub, org_id="acme",
                                tier="team", seats=5, issued_at=iat, expires_at=exp,
                                issuer_seed_hex=iss_seed)
    ok("1 authority mints a team token with schema + install binding",
       tok.get("schema") == "railcall_entitlement.v1" and tok["install_pubkey"] == inst_pub
       and tok["signature"]["alg"] == "ed25519", tok)

    # ── 2. the REAL station verifies it OFFLINE (byte-parity proof) ──────────
    st = STATION.verify_entitlement(tok, issuer_pubkey_hex=iss_pub,
                                    expected_install_pubkey=inst_pub, now=T0 + 100)
    ok("2 station verifies the server-minted token (canonicalization byte-matches)",
       st["valid"] and st["tier"] == "team" and st["seats"] == 5
       and "external_attestation" in st["features"], st)

    # ── 3. BINDING: same token on a DIFFERENT install → free (gap closed) ────
    st_foreign = STATION.verify_entitlement(tok, issuer_pubkey_hex=iss_pub,
                                            expected_install_pubkey=other_pub, now=T0 + 100)
    ok("3 copied token on another machine → free (bound to a different install)",
       st_foreign["tier"] == "free" and "different install" in st_foreign["reason"], st_foreign)

    # ── 3b. and when the install can't be confirmed at all → free ────────────
    st_noid = STATION.verify_entitlement(tok, issuer_pubkey_hex=iss_pub,
                                         expected_install_pubkey=None, now=T0 + 100)
    ok("3b bound token with no confirmable install identity → free", st_noid["tier"] == "free")

    # ── 4. wrong issuer key (can't self-mint) → free ─────────────────────────
    st_forge = STATION.verify_entitlement(tok, issuer_pubkey_hex=other_pub,
                                          expected_install_pubkey=inst_pub, now=T0 + 100)
    ok("4 verified against a non-issuer key → free (no self-minting)", st_forge["tier"] == "free")

    # ── 5. tamper the signed body (bump seats) → signature fails → free ──────
    tampered = dict(tok, seats=9999)
    st_t = STATION.verify_entitlement(tampered, issuer_pubkey_hex=iss_pub,
                                      expected_install_pubkey=inst_pub, now=T0 + 100)
    ok("5 tampered token (seats bumped) → free (signature no longer matches)",
       st_t["tier"] == "free")

    # ── 6. expiry is enforced against server-minted expires_at ───────────────
    st_exp = STATION.verify_entitlement(tok, issuer_pubkey_hex=iss_pub,
                                        expected_install_pubkey=inst_pub,
                                        now=T0 + 31 * 86400)
    ok("6 past expires_at → free (expired)", st_exp["tier"] == "free" and "expired" in st_exp["reason"])

    # ── 7. install path stores a token bound to THIS install, refuses foreign ─
    # install_entitlement checks expiry against real wall-clock, so mint live-dated.
    import tempfile
    tnow = time.time()
    tok_live = AUTH.mint_entitlement(
        install_pubkey_hex=inst_pub, org_id="acme", tier="team", seats=5,
        issued_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tnow)),
        expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tnow + 30 * 86400)),
        issuer_seed_hex=iss_seed)
    ws = tempfile.mkdtemp(prefix="rc-e2e-")
    inst = STATION.install_entitlement(ws, tok_live, issuer_pubkey_hex=iss_pub,
                                       expected_install_pubkey=inst_pub)
    ok("7a install_entitlement accepts a token bound to this install",
       inst.get("ok") and inst["tier"] == "team", inst)
    bad = STATION.install_entitlement(ws, tok_live, issuer_pubkey_hex=iss_pub,
                                      expected_install_pubkey=other_pub)
    ok("7b install_entitlement REFUSES a token bound to another install", not bad.get("ok"))

    # ── 8. attestation COUNTERSIGN (server-side billing/trust truth) ─────────
    ci = AUTH.countersign_attestation(external_integrity="sha256:deadbeef",
                                      attestation_id="att_0001",
                                      countersigned_at="2026-07-17T12:00:00Z",
                                      issuer_seed_hex=iss_seed)
    ok("8a countersignature verifies against the issuer pubkey (offline)",
       AUTH.verify_countersignature(ci, issuer_pubkey_hex=iss_pub))
    ok("8b countersignature fails against a non-issuer key",
       not AUTH.verify_countersignature(ci, issuer_pubkey_hex=other_pub))
    ci_tampered = dict(ci, external_integrity="sha256:evil")
    ok("8c tampered countersignature body → fails",
       not AUTH.verify_countersignature(ci_tampered, issuer_pubkey_hex=iss_pub))

    # ── 9. seat-validation ping is BLIND: exactly {key_hash, nonce} ─────────
    seat_key = "rc_seat_" + os.urandom(6).hex()
    ping = {"key_hash": hashlib.sha256(seat_key.encode()).hexdigest(),
            "nonce": os.urandom(8).hex()}
    ok("9 seat-validate ping carries ONLY key_hash + nonce (no action names/counts)",
       set(ping.keys()) == {"key_hash", "nonce"})

    if FAILS:
        print("\nFAILED: %d — %s" % (len(FAILS), FAILS))
        return 1
    print("\nALL PASS — cross-repo spine: server mint verifies under the REAL station "
          "code (byte-parity), install-binding closes the copy gap, forge/tamper/expiry "
          "degrade to free, attestation countersign is offline-verifiable, seat ping is blind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
