"""test_cli_seed_store.py — CLI-side P0-1: the receipt-signing seed at rest.

The station side of P0-1 was closed in the engine repo (commit 392e8bb4c). This
suite guards the CLI half: the daemon signer + `railcall rotate-key` now route
their seed through `seed_store` too, matching the same migrate-on-boot + fail-safe
ordering the engine's `railcall_signing.py` uses.

What it pins:
  - `seed_store.py` exists in the CLI tree (no more silent import fallback).
  - The daemon's `_ensure_signing_seed()` prefers the keychain when available.
  - When the keychain is unavailable (which the module deliberately signals for
    temp workspaces so tests never orphan real login-keychain entries) the
    plaintext-file fallback still works and receipts still sign.
  - Migration is IDEMPOTENT: running it twice on a plaintext vault produces the
    same seed bytes both times (pubkey continuity for pre-existing installs).
  - Rotation via `_persist_signing_seed()` PRESERVES every other vault key, so
    a rotation never nukes BYOK credentials.
  - The at-rest posture is REPORTABLE — `signing_seed_status()` returns a shape
    the operator can inspect.

Run: python3 -m pytest tests/test_cli_seed_store.py -v
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_1_module_present():
    """seed_store imports cleanly from the CLI tree — the fallback branch in the
    daemon should never be the primary path on a real install."""
    import seed_store  # noqa: F401
    assert hasattr(seed_store, "get")
    assert hasattr(seed_store, "put")
    assert hasattr(seed_store, "migrate")
    assert hasattr(seed_store, "status")


def test_2_temp_workspaces_bypass_keychain():
    """Temp workspaces MUST NOT touch the real login keychain — the suite runs
    against tempdirs constantly, and orphaning login-keychain entries per test
    run would be a leak in its own right."""
    import seed_store as ss
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    assert ss.backend_name(vault) is None
    assert ss.keychain_available(vault) is False


def test_3_plaintext_fallback_roundtrip():
    """With no keychain (test isolation forces this), put()/get() must still
    persist the seed into the 0600 vault file so receipts still sign."""
    import seed_store as ss
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    seed = os.urandom(32)
    posture = ss.put(vault, "_railcall_signing_seed", seed)
    assert posture == "plaintext_file"
    got = ss.get(vault, "_railcall_signing_seed")
    assert got == seed
    # 0600 pinned on the file — verified before we trust any receipt claim.
    assert oct(os.stat(vault).st_mode & 0o777) == "0o600"


def test_4_migrate_idempotent_and_seed_bytes_stable():
    """Idempotent migration is what preserves the install pubkey across the
    upgrade boot. Same seed bytes in → same seed bytes out, no matter how many
    times _ensure_signing_seed runs. If this ever fails, existing CLI receipts
    would silently become unverifiable — the exact anti-goal."""
    import seed_store as ss
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    seed = os.urandom(32)
    # Simulate a pre-upgrade install: plaintext seed in vault.
    with open(vault, "w", encoding="utf-8") as f:
        json.dump({"_railcall_signing_seed": seed.hex()}, f)
    os.chmod(vault, 0o600)

    for _ in range(3):
        ss.migrate(vault, "_railcall_signing_seed")
        got = ss.get(vault, "_railcall_signing_seed")
        assert got == seed, "migrate() must never mutate the seed bytes"


def test_5_ensure_signing_seed_from_plaintext_stays_stable():
    """Boot the daemon's `_ensure_signing_seed()` against a plaintext vault and
    the RETURNED HEX must equal the plaintext hex — proving pre-P0-1 receipts
    still verify after the upgrade."""
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    original_hex = os.urandom(32).hex()
    with open(vault, "w", encoding="utf-8") as f:
        json.dump({"_railcall_signing_seed": original_hex}, f)
    os.chmod(vault, 0o600)

    import railcall_companion_daemon as dae
    orig_root = dae.ROOT
    try:
        dae.ROOT = tmp
        got = dae._ensure_signing_seed()
        assert got == original_hex, "existing seed bytes must survive the upgrade path"
    finally:
        dae.ROOT = orig_root


def test_6_ensure_signing_seed_creates_when_missing_and_preserves_other_keys():
    """A fresh install path: no seed yet, other BYOK keys already in the vault
    (imagine a user who set OLLAMA_HOST before ever calling `railcall demo`).
    _ensure_signing_seed must mint a valid 32-byte seed AND leave the rest of
    the vault untouched. Regression guard for "signing routing accidentally
    stomped the vault"."""
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    with open(vault, "w", encoding="utf-8") as f:
        json.dump({"ollama": {"OLLAMA_HOST": "http://x"}}, f)
    os.chmod(vault, 0o600)

    import railcall_companion_daemon as dae
    orig_root = dae.ROOT
    try:
        dae.ROOT = tmp
        got = dae._ensure_signing_seed()
        assert got is not None, "signer must be able to mint on first use"
        assert len(bytes.fromhex(got)) == 32
        # Vault preserved
        with open(vault, encoding="utf-8") as f:
            v = json.load(f)
        assert v.get("ollama", {}).get("OLLAMA_HOST") == "http://x", (
            "unrelated vault keys must survive first-use seed generation")
    finally:
        dae.ROOT = orig_root


def test_7_persist_signing_seed_rotation_preserves_other_keys():
    """`railcall rotate-key` writes through _persist_signing_seed(). It must land
    the new seed AND leave every other vault key intact. A rotation that drops
    a BYOK credential would look like a "mysterious deauth" to the user."""
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    with open(vault, "w", encoding="utf-8") as f:
        json.dump({
            "slack": {"token": "xoxb-test"},
            "_railcall_signing_seed": os.urandom(32).hex(),
        }, f)
    os.chmod(vault, 0o600)

    class _FakeD:
        ROOT = tmp
        vault_io = None
        receipt_signer = None

    import railcall_cli as cli
    orig_d = cli.d
    try:
        cli.d = _FakeD
        new_seed_hex = os.urandom(32).hex()
        vpath = cli._persist_signing_seed(new_seed_hex)
        assert vpath == vault
        with open(vault, encoding="utf-8") as f:
            v = json.load(f)
        assert v.get("slack", {}).get("token") == "xoxb-test", (
            "rotation must preserve BYOK credentials")
        # Where the seed landed depends on backend; on a temp workspace the
        # backend is forced to file, so the vault MUST carry the new seed.
        # (On a real install with a keychain, this would be absent — the
        # keychain-side round-trip is covered by the engine's test_seed_store.)
        assert v.get("_railcall_signing_seed") == new_seed_hex
    finally:
        cli.d = orig_d


def test_8_status_reports_honest_posture():
    """`signing_seed_status()` must return a shape callers can render without
    the seed ever being in it. If any field name changes, the `railcall status`
    output would regress — this pins the contract."""
    tmp = tempfile.mkdtemp(prefix="rc_seed_test_")
    vault = os.path.join(tmp, "keys.local.json")
    with open(vault, "w", encoding="utf-8") as f:
        json.dump({"_railcall_signing_seed": os.urandom(32).hex()}, f)
    os.chmod(vault, 0o600)

    import railcall_companion_daemon as dae
    orig_root = dae.ROOT
    try:
        dae.ROOT = tmp
        st = dae.signing_seed_status()
    finally:
        dae.ROOT = orig_root
    assert "at_rest" in st
    assert "backend" in st
    assert "keychain_available" in st
    assert "note" in st
    # Temp workspace forces file backend, so posture must be plaintext_file.
    assert st["at_rest"] == "plaintext_file"
    # Never leaks the seed itself.
    dumped = json.dumps(st)
    assert "_railcall_signing_seed" not in dumped


if __name__ == "__main__":
    # Run without pytest so the suite also works in the minimal install env.
    fns = [(name, fn) for name, fn in sorted(globals().items())
           if name.startswith("test_") and callable(fn)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print("PASS", name)
        except AssertionError as e:
            failed += 1
            print("FAIL", name, "—", e)
        except Exception as e:
            failed += 1
            print("ERR ", name, "—", type(e).__name__, e)
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(0 if failed == 0 else 1)
