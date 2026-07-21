#!/usr/bin/env python3
"""
mint_issuer_keypair.py — generate the RailCall issuer keypair (paid-tier root of trust).

READ BEFORE RUNNING. This script mints the Ed25519 keypair whose PRIVATE HALF
becomes the gateway's `RAILCALL_ISSUER_SEED` env var and whose PUBLIC HALF gets
pinned into the shipped station at `railcall-engine/workbench/primitives/entitlement.py`
as `ISSUER_PUBKEY_HEX`. That pin acts like a TLS root — a station refuses ANY
entitlement not signed by the seed matching the pinned key.

WHEN TO RUN THIS
────────────────
• LAUNCH PREP — the live gateway currently 503s on /v1/issuer/pubkey, meaning
  the seed was never set. If the previously-pinned ISSUER_PUBKEY_HEX is
  orphaned (its seed was generated in a session and discarded, per the note
  in claude-context.md § "LAUNCH BLOCKER"), running this once and following
  the printed steps unblocks the paid tier.

• KEY ROTATION — future-you rotating the root deliberately. Note that rotation
  invalidates every outstanding entitlement, so treat it as a serious operation.

WHEN NOT TO RUN THIS
────────────────────
• If `RAILCALL_ISSUER_SEED` is already set on the live gateway and matches the
  pinned key, the paid tier already works — running this and deploying its
  output would ROTATE the root and revoke every live customer's entitlement.
  Verify first with:  curl https://railcall-core.onrender.com/v1/issuer/pubkey
  If that returns 200 with a `public_key_hex`, DO NOT RUN THIS SCRIPT.

WHAT THIS SCRIPT DOES
─────────────────────
1. Generates a fresh 32-byte Ed25519 seed (CSPRNG, os.urandom).
2. Derives the matching 32-byte Ed25519 public key.
3. Writes the seed to a 0600 file at a path YOU choose on the command line
   (never to a repo path, never to stdout unless you pass --print-seed).
4. Prints the PUBLIC key hex, ready to paste into entitlement.py.
5. Prints the exact two-step deploy sequence.

The private seed is NEVER logged, NEVER committed, NEVER echoed to the console
unless you explicitly ask for --print-seed (only appropriate when piping into
`pbcopy` and immediately setting the Render env var).

USAGE
─────
    # Standard: write seed to a local file you'll delete after setting Render.
    python3 tools/mint_issuer_keypair.py --seed-out ~/railcall-issuer-seed.txt

    # Alternative: print to stdout so you can pipe directly into pbcopy.
    python3 tools/mint_issuer_keypair.py --print-seed | pbcopy

    # Then use --check to prove parity against the station's verify path.
    python3 tools/mint_issuer_keypair.py --check <seed-hex>

STDLIB ONLY. No third-party deps.
"""
import argparse
import hashlib
import os
import sys

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except Exception as e:
    print("ERROR: the `cryptography` package is required. Install it and re-run.\n"
          "  python3 -m pip install --user --break-system-packages cryptography\n"
          "  (%r)" % (e,), file=sys.stderr)
    sys.exit(2)


def derive_pub_hex(seed_bytes: bytes) -> str:
    """Return the 32-byte Ed25519 public key hex for `seed_bytes`."""
    if len(seed_bytes) != 32:
        raise ValueError("seed must be 32 bytes; got %d" % len(seed_bytes))
    priv = Ed25519PrivateKey.from_private_bytes(seed_bytes)
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pub.hex()


def write_seed_file(path: str, seed_hex: str) -> None:
    """Write the seed to `path` with 0600, atomically. Never overwrites — if the
    file already exists, refuses so you cannot accidentally destroy an earlier mint."""
    path = os.path.expanduser(path)
    if os.path.exists(path):
        raise SystemExit("REFUSING to overwrite existing file: %s\n"
                         "  (rename or delete it first; refusal is deliberate — this "
                         "guards against clobbering a previously-minted seed)" % path)
    tmp = path + ".tmp"
    # O_CREAT | O_EXCL | O_WRONLY, mode 0600 — the file is 0600 from birth,
    # never briefly world-readable, and never exists before we write it.
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(seed_hex + "\n")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def cmd_mint(args):
    seed_bytes = os.urandom(32)
    seed_hex = seed_bytes.hex()
    pub_hex = derive_pub_hex(seed_bytes)
    key_id = hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]

    if args.seed_out:
        write_seed_file(args.seed_out, seed_hex)

    print("─" * 78)
    print("RAILCALL ISSUER KEYPAIR — freshly minted")
    print("─" * 78)
    print()
    print("PUBLIC key hex (safe to publish; pin this in the station):")
    print("  " + pub_hex)
    print()
    print("Key id (transparency; matches /v1/issuer/pubkey response):")
    print("  " + key_id)
    print()
    if args.print_seed:
        print("PRIVATE seed hex (SECRET — never commit, never log):")
        print("  " + seed_hex)
        print()
    elif args.seed_out:
        print("PRIVATE seed written to: %s  (0600, delete once Render env is set)"
              % os.path.expanduser(args.seed_out))
        print()
    else:
        # Refuse to swallow the seed silently. If neither --seed-out nor --print-seed
        # was passed, the seed we just generated would be lost when this process exits,
        # which is worse than either alternative (silently discarding the trust root).
        raise SystemExit("REFUSING to discard the seed: pass either --seed-out <path> "
                         "(recommended) or --print-seed (only if piping to pbcopy).")

    print("DEPLOY STEPS (both must complete for paid tier to work):")
    print()
    print("  1. Update the pinned pubkey in the station code, then cut a new")
    print("     station release so users install a station that trusts this key:")
    print("       railcall-engine/workbench/primitives/entitlement.py:")
    print("         ISSUER_PUBKEY_HEX = \"%s\"" % pub_hex)
    print()
    print("     (The pin ships INSIDE the station tarball. A running station")
    print("      with the OLD pin will refuse entitlements signed by this NEW")
    print("      seed until the user re-runs the installer.)")
    print()
    print("  2. Set the seed as an env var on the Render gateway service:")
    print("       Render dashboard → railcall-core → Environment →")
    print("         RAILCALL_ISSUER_SEED = <the seed hex above>")
    print("       (defined in render.yaml as sync:false, so it must be set")
    print("        manually per environment — this is a security feature.)")
    print()
    print("  Verify BOTH:")
    print("    curl https://railcall-core.onrender.com/v1/issuer/pubkey")
    print("      → should return {\"public_key_hex\":\"" + pub_hex[:24] + "...\", ...}")
    print("    Then run test_activate_e2e.py against a freshly installed station.")
    print()
    print("BACKUP: keep the seed hex in an offline password manager. If lost,")
    print("        every outstanding entitlement becomes unforgeable-but-unreplaceable")
    print("        and the whole install base needs a station re-release.")


def cmd_check(args):
    """Recompute the pubkey from a supplied seed hex and print it, so an operator
    can independently verify a seed matches the pin without shipping anything."""
    seed_hex = args.seed_hex.strip().lower()
    try:
        seed_bytes = bytes.fromhex(seed_hex)
    except Exception:
        raise SystemExit("seed hex must decode as bytes")
    pub_hex = derive_pub_hex(seed_bytes)
    print("public_key_hex: " + pub_hex)
    print("key_id:         " + hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16])
    print()
    print("Compare against ISSUER_PUBKEY_HEX in")
    print("  railcall-engine/workbench/primitives/entitlement.py")
    print("If they match, this seed matches the current pin — safe to set as")
    print("RAILCALL_ISSUER_SEED on the gateway without re-releasing the station.")


def main():
    p = argparse.ArgumentParser(description="Mint the RailCall issuer keypair.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd")

    m = sub.add_parser("mint", help="mint a fresh keypair (default action)")
    m.add_argument("--seed-out", help="path to write the seed to (0600, refuses overwrite)")
    m.add_argument("--print-seed", action="store_true",
                   help="also print the seed to stdout (only if piping to pbcopy etc.)")
    m.set_defaults(func=cmd_mint)

    c = sub.add_parser("check", help="derive a pubkey from an existing seed hex")
    c.add_argument("seed_hex", help="32-byte Ed25519 seed as 64 hex chars")
    c.set_defaults(func=cmd_check)

    # Default subcommand = mint if none supplied
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["mint"] + sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()
