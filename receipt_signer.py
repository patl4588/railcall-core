"""
receipt_signer.py — Ed25519 receipt signing/verification over CANONICAL JSON (RFC 8032), built on
the standard `cryptography` library.

Determinism is the whole point: a receipt is serialized with sorted keys + the tightest separators,
so the SAME logical payload yields byte-identical signing input on any host, any Python, any order
the dict happened to be built in. That is what makes a signature verifiable by a third party who
only re-serializes the same fields.

Key material:
  • seed_hex       — the 32-byte Ed25519 private seed, 64 hex chars. Never logged, never returned.
  • public_key_hex — the 32-byte public key, 64 hex chars. Safe to publish; this is what verifies.
  • signature      — 64-byte Ed25519 signature, 128 hex chars.
"""
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_SEED_BYTES = 32  # Ed25519 private seed length (RFC 8032)


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic serialization of `payload`: keys sorted, no insignificant whitespace, UTF-8.
    Signer and verifier MUST agree on these bytes — so this is the single source of truth for both."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _load_seed(seed_hex: str) -> Ed25519PrivateKey:
    seed = bytes.fromhex(seed_hex)
    if len(seed) != _SEED_BYTES:
        raise ValueError(
            "Ed25519 seed must be %d bytes (%d hex chars); got %d bytes"
            % (_SEED_BYTES, _SEED_BYTES * 2, len(seed))
        )
    return Ed25519PrivateKey.from_private_bytes(seed)


def sign_payload(payload: dict, seed_hex: str) -> str:
    """Sign `payload` with the 32-byte Ed25519 seed. Returns the 64-byte signature as 128 hex chars.
    Deterministic: signing the same payload with the same seed always yields the same signature."""
    signing_key = _load_seed(seed_hex)
    return signing_key.sign(canonical_bytes(payload)).hex()


def verify_payload(payload: dict, signature_hex: str, public_key_hex: str) -> bool:
    """Verify `signature_hex` over `payload` against `public_key_hex`. Returns True iff valid for the
    canonical bytes; returns False (never raises) on a bad signature, wrong key, or malformed input."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature_hex), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def public_key_hex(seed_hex: str) -> str:
    """Derive the 32-byte public key (64 hex) from the 32-byte private seed, so the verify key can be
    published without ever exposing the seed."""
    raw = _load_seed(seed_hex).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return raw.hex()
