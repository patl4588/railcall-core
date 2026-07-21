#!/usr/bin/env python3
"""
seed_store.py — where the install's Ed25519 signing seed lives at rest (P0-1).

THE PROBLEM
  The 32-byte signing seed sat in <ws>/keys.local.json as plaintext hex, protected
  only by 0600. Anyone who could read that file could forge receipts that verify
  cleanly against the published install pubkey — which undercuts every receipt-based
  claim the product makes, not just the healthcare ones. §164.312(a)(2)(iv).

THE FIX, AND ITS HONEST LIMIT
  Prefer the OS keychain. On macOS that is `security(1)` in the login keychain.

  What that actually buys:
    ✓ the seed stops appearing in file backups, Time Machine, iCloud/Dropbox sync
    ✓ it stops being readable by anything that merely walks the filesystem
    ✓ it stops being capturable by an accidental `git add` or a copied workspace
    ✗ it does NOT stop malware running as the same user — the login keychain is
      unlocked for that user, so a process with their privileges can ask for it too

  So this is protection against COPYING and LEAKAGE, not against local code execution
  as the owner. Say it that way. Defending against same-user malware needs a hardware
  token or a passphrase prompt on every signature, and both break unattended
  operation, which is the whole point of a local automation engine.

  The secret is fed to `security` over STDIN, never as an argv value — `security`'s
  own usage text warns that -w/-p on the command line is insecure, and argv is visible
  to `ps`. Verified by roundtrip test.

FALLBACK
  If no keychain backend is available (non-macOS today, or `security` missing/locked),
  the seed stays in the 0600 vault file exactly as before. That is a DEGRADED state,
  not a fine one: `status()` reports `at_rest="plaintext_file"` so the honest posture
  is visible rather than assumed. Windows (DPAPI/Credential Manager) and Linux (Secret
  Service) backends are not implemented — that is a gap, recorded as a gap.

TEST ISOLATION
  Workspaces under the system temp dir never touch the keychain. The test suite
  constructs throwaway workspaces constantly; without this it would fill the
  developer's login keychain with orphaned entries. Temp workspaces use the file
  backend, which is also what the existing tests already expect.

Stdlib only.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

SERVICE = "ai.railcall.signing-seed"
_TIMEOUT = 10


def _account_for(vault_path):
    """One keychain item per install, keyed by a hash of the workspace path so two
    installs on one machine never collide. The path itself is not stored."""
    ws = os.path.dirname(os.path.abspath(vault_path))
    return "install-" + hashlib.sha256(ws.encode()).hexdigest()[:16]


def _is_temp(vault_path):
    # realpath BOTH sides: on macOS gettempdir() is /var/folders/... where /var is a
    # symlink to /private/var, so comparing an unresolved path against a resolved one
    # silently never matches — which would let the test suite write orphan keychain
    # entries on every run.
    try:
        return os.path.realpath(vault_path).startswith(
            os.path.realpath(tempfile.gettempdir()))
    except Exception:
        return False


def backend_name(vault_path=None):
    """Which OS-keystore backend applies here, or None for the file fallback.

    Order is platform-exclusive, not preference — a box is one of these.
      macos_keychain    — /usr/bin/security, login keychain
      windows_dpapi     — CryptProtectData, user-scoped; ciphertext stored beside the
                          vault because DPAPI encrypts rather than storing
      linux_secretservice — `secret-tool` (libsecret), the freedesktop keyring
    """
    if vault_path is not None and _is_temp(vault_path):
        return None            # test isolation — see module docstring
    if os.environ.get("RAILCALL_SEED_STORE") == "file":
        return None            # explicit operator opt-out
    if sys.platform == "darwin" and os.path.exists("/usr/bin/security"):
        return "macos_keychain"
    if sys.platform == "win32":
        try:
            import ctypes  # noqa: F401
            return "windows_dpapi"
        except Exception:
            return None
    if sys.platform.startswith("linux") and shutil.which("secret-tool"):
        # libsecret needs a running keyring daemon; a headless box often has none.
        # Probe rather than assume — a store that silently fails is worse than the
        # file fallback, because status() would claim protection that isn't there.
        try:
            p = subprocess.run(["secret-tool", "search", "service", SERVICE],
                               capture_output=True, text=True, timeout=_TIMEOUT)
            if p.returncode in (0, 1):        # 1 == "no match", daemon is alive
                return "linux_secretservice"
        except Exception:
            return None
    return None


def keychain_available(vault_path=None):
    """True if any OS-keystore backend can be used for this workspace."""
    return backend_name(vault_path) is not None


# ---------------------------------------------------------------- keychain ---
def _kc_get(account):
    try:
        p = subprocess.run(["/usr/bin/security", "find-generic-password",
                            "-a", account, "-s", SERVICE, "-w"],
                           capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    hexed = (p.stdout or "").strip()
    try:
        seed = bytes.fromhex(hexed)
    except ValueError:
        return None
    return seed if len(seed) == 32 else None


def _kc_put(account, seed):
    """Write via STDIN, never argv. `security -w` with no value prompts twice
    (password, then confirmation), and reads both from stdin when piped."""
    hexed = seed.hex()
    try:
        p = subprocess.run(["/usr/bin/security", "add-generic-password",
                            "-a", account, "-s", SERVICE, "-U",
                            "-D", "RailCall install signing seed",
                            "-j", "Ed25519 seed for this RailCall install. "
                                  "Deleting it means receipts can no longer be signed.",
                            "-w"],
                           input=hexed + "\n" + hexed + "\n",
                           capture_output=True, text=True, timeout=_TIMEOUT)
        return p.returncode == 0
    except Exception:
        return False


# ------------------------------------------------------------ windows dpapi ---
# DPAPI ENCRYPTS, it does not STORE. So the ciphertext lives beside the vault in
# seed.dpapi and only the user's Windows credentials can decrypt it. Copying that file
# to another machine or another user account yields nothing — which is the same
# copy-resistance the macOS keychain gives, achieved differently.
DPAPI_FILE = "seed.dpapi"
_DPAPI_ENTROPY = b"railcall.signing.seed.v1"   # extra entropy, binds blob to this use


def _dpapi_path(vault_path):
    return os.path.join(os.path.dirname(os.path.abspath(vault_path)), DPAPI_FILE)


def _dpapi_blobs():
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def from_blob(blob):
        return ctypes.string_at(blob.pbData, blob.cbData)

    return ctypes, BLOB, to_blob, from_blob


def _dpapi_put(vault_path, seed):
    try:
        ctypes, BLOB, to_blob, from_blob = _dpapi_blobs()
        crypt32 = ctypes.WinDLL("crypt32.dll")
        blob_in, _b1 = to_blob(seed)
        ent, _b2 = to_blob(_DPAPI_ENTROPY)
        blob_out = BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1 — never prompt; this must work unattended.
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), None,
                                        ctypes.byref(ent), None, None, 0x1,
                                        ctypes.byref(blob_out)):
            return False
        data = from_blob(blob_out)
        p = _dpapi_path(vault_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _dpapi_get(vault_path):
    try:
        p = _dpapi_path(vault_path)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as fh:
            data = fh.read()
        ctypes, BLOB, to_blob, from_blob = _dpapi_blobs()
        crypt32 = ctypes.WinDLL("crypt32.dll")
        blob_in, _b1 = to_blob(data)
        ent, _b2 = to_blob(_DPAPI_ENTROPY)
        blob_out = BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None,
                                          ctypes.byref(ent), None, None, 0x1,
                                          ctypes.byref(blob_out)):
            return None
        seed = from_blob(blob_out)
        return seed if len(seed) == 32 else None
    except Exception:
        return None


# ------------------------------------------------------ linux secret service ---
def _ss_get(account):
    try:
        p = subprocess.run(["secret-tool", "lookup", "service", SERVICE,
                            "account", account],
                           capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    try:
        seed = bytes.fromhex((p.stdout or "").strip())
    except ValueError:
        return None
    return seed if len(seed) == 32 else None


def _ss_put(account, seed):
    """secret-tool store reads the secret from STDIN — never argv."""
    try:
        p = subprocess.run(["secret-tool", "store", "--label=RailCall signing seed",
                            "service", SERVICE, "account", account],
                           input=seed.hex(), capture_output=True, text=True,
                           timeout=_TIMEOUT)
        return p.returncode == 0
    except Exception:
        return False


# -------------------------------------------------------------------- file ---
def _file_get(vault_path, key):
    import json
    try:
        with open(vault_path, encoding="utf-8") as fh:
            hexed = (json.load(fh) or {}).get(key)
        seed = bytes.fromhex(hexed) if hexed else None
        return seed if seed and len(seed) == 32 else None
    except Exception:
        return None


def _file_put(vault_path, key, seed_hex):
    import json
    try:
        os.makedirs(os.path.dirname(vault_path), exist_ok=True)
        try:
            with open(vault_path, encoding="utf-8") as fh:
                vault = json.load(fh) or {}
        except Exception:
            vault = {}
        if seed_hex is None:
            vault.pop(key, None)
        else:
            vault[key] = seed_hex
        tmp = vault_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(vault, fh, indent=2)
        os.replace(tmp, vault_path)
        try:
            os.chmod(vault_path, 0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


# ------------------------------------------------------------------- public ---
def _store_get(vault_path):
    """Read from whichever OS keystore applies, or None."""
    b = backend_name(vault_path)
    if b == "macos_keychain":
        return _kc_get(_account_for(vault_path))
    if b == "windows_dpapi":
        return _dpapi_get(vault_path)
    if b == "linux_secretservice":
        return _ss_get(_account_for(vault_path))
    return None


def _store_put(vault_path, seed):
    b = backend_name(vault_path)
    if b == "macos_keychain":
        return _kc_put(_account_for(vault_path), seed)
    if b == "windows_dpapi":
        return _dpapi_put(vault_path, seed)
    if b == "linux_secretservice":
        return _ss_put(_account_for(vault_path), seed)
    return False


def get(vault_path, key):
    """The seed, from the OS keystore if present, else the vault file. 32 bytes/None."""
    seed = _store_get(vault_path)
    if seed:
        return seed
    return _file_get(vault_path, key)


def put(vault_path, key, seed):
    """Persist the seed in the best available backend. Returns the backend name.

    On keystore success the plaintext copy is REMOVED from the vault file — leaving it
    behind would make the keystore decorative.
    """
    if _store_put(vault_path, seed):
        _file_put(vault_path, key, None)
        return backend_name(vault_path)
    _file_put(vault_path, key, seed.hex())
    return "plaintext_file"


def migrate(vault_path, key):
    """Move an existing plaintext seed into the keychain. Idempotent; safe to call on
    every boot. Returns the backend the seed ended up in, or None if there is no seed.

    Order matters: the keychain write must SUCCEED before the plaintext copy is
    removed, or a failed migration destroys the install's signing identity.
    """
    b = backend_name(vault_path)
    if b is None:
        return "plaintext_file" if _file_get(vault_path, key) else None
    if _store_get(vault_path):
        _file_put(vault_path, key, None)      # already migrated; clear any leftover
        return b
    seed = _file_get(vault_path, key)
    if not seed:
        return None
    if _store_put(vault_path, seed):
        _file_put(vault_path, key, None)
        return b
    return "plaintext_file"                   # keystore refused — keep the file copy


_BACKEND_NOTE = {
    "macos_keychain":
        "Seed held in the macOS login keychain. Protects against file copying, backups "
        "and sync leakage — NOT against malware running as this same user.",
    "windows_dpapi":
        "Seed encrypted with Windows DPAPI under this user's credentials; the ciphertext "
        "sits beside the vault and is useless on another machine or account. Protects "
        "against file copying and backups — NOT against malware running as this user.",
    "linux_secretservice":
        "Seed held in the freedesktop Secret Service keyring (libsecret). Protects "
        "against file copying, backups and sync leakage — NOT against malware running "
        "as this same user.",
}


def status(vault_path, key):
    """Honest at-rest posture for this install. Never returns the seed."""
    b = backend_name(vault_path)
    in_kc = bool(b and _store_get(vault_path))
    in_file = _file_get(vault_path, key) is not None
    if in_kc:
        at_rest, note = b, _BACKEND_NOTE.get(b, "Seed held in an OS keystore.")
    elif in_file:
        at_rest, note = "plaintext_file", (
            "DEGRADED: seed is plaintext hex in the 0600 vault file. Anyone who can "
            "read the file can forge receipts for this install.")
    else:
        at_rest, note = "absent", "No signing seed yet; receipts will be unsigned."
    return {"at_rest": at_rest, "backend": b, "keychain_available": b is not None,
            "seed_in_keychain": in_kc, "seed_in_file": in_file, "note": note}
