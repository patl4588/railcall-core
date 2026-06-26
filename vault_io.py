"""
vault_io.py — atomic, truncation-safe I/O for the 0600 secret vault (keys.local.json).

The exact failure this exists to prevent: a process that does `open(path, "w")` and then dies
mid-`json.dump` leaves a TRUNCATED, unparseable file. On a vault that holds the Ed25519 signing
seed, that is silent data loss — and a naive reader that catches the parse error and returns `{}`
makes the corrupt vault look merely empty, dropping the seed for good.

This module closes both holes:
  • WRITE  — serialize into a sibling temp file, fsync the bytes to the platter, then os.replace()
             it over the target. os.replace() is an atomic same-filesystem rename, so a crash at
             ANY instant leaves the previous COMPLETE file intact. Readers never see a half file.
  • READ   — a present-but-unparseable (or zero-byte) vault raises VaultCorruptError instead of
             masquerading as `{}`, so a caller can recover from a backup rather than overwrite a
             recoverable seed.
  • PERMS  — the file is pinned to 0600 at create time (on the fd, before any bytes land), so the
             secret is never briefly world-readable.

Pure standard library. No third-party dependency.
"""
import json
import os
import tempfile

DEFAULT_MODE = 0o600


class VaultCorruptError(Exception):
    """The vault file exists but does not parse as JSON (or is empty). Never silently treated as
    {} — that path is precisely how a truncated vault used to swallow the signing seed."""


def load(path, *, default=None):
    """Read and parse the vault.

    Missing file        -> `default` (or {} if default is None).
    Empty / unparseable -> raises VaultCorruptError (caller decides whether to recover from a .bak),
                           never a silent {}.
    """
    if not os.path.exists(path):
        return {} if default is None else default
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if not raw.strip():
        raise VaultCorruptError("%s is 0 bytes / whitespace — refusing to treat as empty {}" % path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise VaultCorruptError("%s does not parse (%s); %d bytes on disk" % (path, e, len(raw))) from e


def save(path, obj, *, mode=DEFAULT_MODE):
    """Atomically persist `obj` as pretty JSON to `path` at `mode` (default 0600).

    temp-in-same-dir -> write -> flush -> os.fsync -> os.replace -> chmod -> fsync(dir).
    A crash never truncates the live file; readers observe old-or-new, never partial.
    Returns the number of bytes written.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    data = json.dumps(obj, indent=2).encode("utf-8")

    # mkstemp creates the temp file 0600 by default, in the SAME directory, so os.replace() is a
    # genuine atomic same-filesystem rename (a cross-fs move would NOT be atomic).
    fd, tmp = tempfile.mkstemp(prefix=".keys-", suffix=".tmp", dir=directory)
    try:
        os.fchmod(fd, mode)              # pin permissions on the fd before any secret bytes land
        with os.fdopen(fd, "wb") as f:   # fdopen takes ownership of fd; closed on exit
            f.write(data)
            f.flush()
            os.fsync(f.fileno())         # force bytes to disk, not just the page cache
        os.replace(tmp, path)            # ATOMIC swap (POSIX rename semantics)
        os.chmod(path, mode)             # belt + suspenders on the final inode
        _fsync_dir(directory)            # make the rename itself durable across power loss
        return len(data)
    except BaseException:
        # Never leave a stray temp file behind on failure.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(path, mutate, *, mode=DEFAULT_MODE, default=None):
    """Read-modify-write in one atomic step: load -> mutate(dict) -> save.

    `mutate` receives the current dict and may either mutate it in place (returning None) or return
    a new dict. Every pre-existing key (e.g. the signing seed) is preserved unless the caller drops
    it explicitly. Propagates VaultCorruptError rather than clobbering an unparseable vault.
    """
    current = load(path, default={} if default is None else default)
    if current is None:
        current = {}
    result = mutate(current)
    new_obj = current if result is None else result
    save(path, new_obj, mode=mode)
    return new_obj


def _fsync_dir(directory):
    """fsync the directory so the rename entry is durable. Best-effort: some filesystems disallow
    directory fsync — the file fsync + atomic os.replace already guarantee no torn write."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass
