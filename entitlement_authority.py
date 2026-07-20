"""
entitlement_authority.py — the SERVER side of the RailCall paid tier: the licensing
authority that MINTS signed entitlements and COUNTERSIGNS attestations.

This is the piece that makes the paid tier real. The station ships only the issuer
PUBLIC key (pinned) and verifies entitlements OFFLINE; the issuer PRIVATE seed lives
ONLY here, on the server, and is what a customer cannot forge. Mirror image of the
station's workbench/primitives/entitlement.py verify path.

BYTE-PARITY CONTRACT (do not break):
  The station verifies a token by rebuilding body = {every field except "signature"}
  and Ed25519-verifying the signature over `_canonical(body)`, where the station's
  _canonical is:
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
  So this module MUST canonicalize identically (same sort_keys, same separators,
  default ensure_ascii). test_entitlement_authority_e2e.py proves a token minted here
  verifies under the REAL station code — that test is the parity guard.

INSTALL-PUBKEY BINDING (closes the copyable-entitlement gap):
  A minted entitlement embeds the buyer's install_pubkey in the SIGNED body. Because
  the station signs "everything except signature", the bound pubkey is automatically
  inside the signature — no extra crypto. The station's verify enforces that the
  token's install_pubkey matches THIS install's pubkey, so a token lifted to another
  machine degrades to free.

Stdlib + `cryptography` (already a gateway dependency, via receipt_signer.py).
The issuer seed is passed in per call — never stored in this module, never logged.
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SCHEMA = "railcall_entitlement.v1"
TIERS = ("team", "enterprise")  # 'free' is the un-entitled default; never minted.

# The one live paid feature the station gates on today (h_ext_attest). Team+ get it.
_DEFAULT_FEATURES = {
    "team": ["external_attestation", "multi_seat"],
    "enterprise": ["external_attestation", "multi_seat", "sso"],
}


def _canonical(body: Dict[str, Any]) -> bytes:
    # MUST byte-match workbench/primitives/entitlement.py:_canonical on the station.
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def _priv(seed_hex: str) -> Ed25519PrivateKey:
    seed = bytes.fromhex(seed_hex)
    if len(seed) != 32:
        raise ValueError("issuer seed must be 32 bytes / 64 hex chars")
    return Ed25519PrivateKey.from_private_bytes(seed)


def _pub_raw(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def issuer_identity(seed_hex: str) -> Dict[str, str]:
    """Public identity of the issuer for the /v1/issuer/pubkey transparency endpoint
    and for pinning into the shipped station. Never exposes the seed."""
    priv = _priv(seed_hex)
    pub = _pub_raw(priv)
    return {
        "alg": "ed25519",
        "public_key_hex": pub.hex(),
        # station derives key_id the same way: sha256(pub_bytes)[:16]
        "key_id": hashlib.sha256(pub).hexdigest()[:16],
    }


def mint_entitlement(*, install_pubkey_hex: str, org_id: str, tier: str,
                     seats: int, issued_at: str, expires_at: str,
                     issuer_seed_hex: str,
                     features: Optional[List[str]] = None) -> Dict[str, Any]:
    """Sign an entitlement bound to `install_pubkey_hex`. `issued_at`/`expires_at`
    are UTC 'YYYY-MM-DDThh:mm:ssZ' strings (the station parses them as UTC via
    calendar.timegm — emitting local time would skew expiry, so callers MUST pass Z).
    Returns the full token the customer feeds to install_entitlement()."""
    if tier not in TIERS:
        raise ValueError("tier must be one of %s" % (TIERS,))
    if not install_pubkey_hex or len(bytes.fromhex(install_pubkey_hex)) != 32:
        raise ValueError("install_pubkey_hex must be a 32-byte hex Ed25519 public key")
    feats = sorted(set(features if features is not None else _DEFAULT_FEATURES[tier]))
    body = {
        "schema": SCHEMA,
        "org_id": str(org_id),
        "tier": tier,
        "seats": int(seats),
        "features": feats,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "issuer": "railcall",
        "install_pubkey": install_pubkey_hex,   # SIGNED — the binding
    }
    priv = _priv(issuer_seed_hex)
    sig = priv.sign(_canonical(body)).hex()
    key_id = hashlib.sha256(_pub_raw(priv)).hexdigest()[:16]
    token = dict(body)
    token["signature"] = {"alg": "ed25519", "sig": sig, "key_id": key_id}
    return token


def countersign_attestation(*, external_integrity: str, attestation_id: str,
                            countersigned_at: str, issuer_seed_hex: str) -> Dict[str, Any]:
    """The server-side billing/trust truth: countersign a submission bundle's
    external_integrity with the issuer seed. This is what turns the station's
    'submission_bundle_pending_railcall_countersignature' into an accepted attestation.
    Returns a countersignature block verifiable offline against the issuer public key."""
    payload = {
        "kind": "railcall_attestation_countersignature.v1",
        "external_integrity": external_integrity,
        "attestation_id": attestation_id,
        "countersigned_at": countersigned_at,
        "issuer": "railcall",
    }
    priv = _priv(issuer_seed_hex)
    sig = priv.sign(_canonical(payload)).hex()
    key_id = hashlib.sha256(_pub_raw(priv)).hexdigest()[:16]
    return {**payload, "signature": {"alg": "ed25519", "sig": sig, "key_id": key_id}}


def verify_countersignature(countersig: Dict[str, Any], *, issuer_pubkey_hex: str) -> bool:
    """Offline check that a countersignature is genuinely from the issuer (for the
    station to confirm its attestation was accepted). Never raises."""
    try:
        block = countersig.get("signature") or {}
        body = {k: v for k, v in countersig.items() if k != "signature"}
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(issuer_pubkey_hex))
        pub.verify(bytes.fromhex(block["sig"]), _canonical(body))
        return True
    except Exception:
        return False
