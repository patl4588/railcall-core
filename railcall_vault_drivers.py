"""Receipt-vault drivers.

The vault is where every governed run's signed receipt AND the append-only
audit_log line land. The default (single-user) install writes both into
~/.railcall/receipts and ~/.railcall/audit_log.jsonl — no driver needed.

When the Studio is bound to a marketplace org, the org's admin can point
the vault at a shared destination so every seat's receipts converge into
one place a compliance auditor can query. That's what this module wires up.

Design contract (a driver PROMISES):
  - write_receipt(receipt: dict, canonical_filename: str) -> None
        Persist the receipt bytes at the driver's target. Best-effort;
        raise on failure so the caller can log + fall back.
  - append_audit_line(entry: dict) -> None
        Append one JSON line to the driver's audit stream. Same failure
        contract as above.

The caller (railcall_cli._archive_and_log) invokes drivers with try/except
around each method — a vault write MUST NEVER break a governed run. That
policy is enforced there, not here, so drivers can raise honestly.

Only the LocalVaultDriver ships in this file. S3 / network_share / custom
drivers land in a Phase-3 change; the interface below is stable, so adding
them is purely additive.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional


class VaultDriver:
    """Abstract driver interface. Subclasses implement the two methods."""

    name = "abstract"

    def write_receipt(self, receipt: Dict[str, Any], canonical_filename: str) -> None:
        raise NotImplementedError

    def append_audit_line(self, entry: Dict[str, Any]) -> None:
        raise NotImplementedError


class NullVaultDriver(VaultDriver):
    """No-op driver. Used when the caller has no org config — every write
    is silently swallowed; the local default writer (in railcall_cli) is
    still doing its job independently.
    """

    name = "null"

    def write_receipt(self, receipt: Dict[str, Any], canonical_filename: str) -> None:
        return

    def append_audit_line(self, entry: Dict[str, Any]) -> None:
        return


class LocalVaultDriver(VaultDriver):
    """Writes to a filesystem path. Covers three real customer stories with
    one driver: external SSD, mounted NAS, USB stick. The org admin picks
    the mount point; Studio here just writes files.

    Layout under `path`:
        receipts/<schema>-<utc_stamp>[-n].json  (0640, atomic replace)
        audit_log.jsonl                          (append-only)
    """

    name = "local"

    def __init__(self, path: str):
        if not path or not isinstance(path, str):
            raise ValueError("LocalVaultDriver requires a non-empty path")
        self.path = os.path.expanduser(path)
        self.receipts_dir = os.path.join(self.path, "receipts")
        self.audit_log_path = os.path.join(self.path, "audit_log.jsonl")

    def _ensure_dirs(self) -> None:
        # Create BOTH the base and the receipts subdir. Any failure here
        # propagates — the caller wraps in try/except and logs.
        os.makedirs(self.receipts_dir, exist_ok=True)

    def write_receipt(self, receipt: Dict[str, Any], canonical_filename: str) -> None:
        self._ensure_dirs()
        schema = str(receipt.get("schema") or "receipt").replace("/", "_").replace("..", "")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        cand = os.path.join(self.receipts_dir, f"{schema}-{stamp}.json")
        n = 1
        while os.path.exists(cand):
            cand = os.path.join(self.receipts_dir, f"{schema}-{stamp}-{n}.json")
            n += 1
        # Atomic write via temp-then-rename. Fsync the tempfile so a crash
        # between write and rename doesn't leave a half-file with a real name.
        tmp = cand + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # tmpfs et al. may not support fsync — best-effort
        os.chmod(tmp, 0o640)
        os.replace(tmp, cand)

    def append_audit_line(self, entry: Dict[str, Any]) -> None:
        self._ensure_dirs()
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def load_driver(config: Optional[Dict[str, Any]]) -> VaultDriver:
    """Factory: dispatch on config['driver'] to a driver instance. Unknown
    or unsupported drivers return NullVaultDriver + log a warning so the
    caller keeps running — the local default writer still catches everything.
    """
    if not config or not isinstance(config, dict):
        return NullVaultDriver()
    driver = config.get("driver")
    try:
        if driver == "local":
            return LocalVaultDriver(path=config.get("path", ""))
        # Phase-3 drivers will slot in here. Until then, degrade honestly.
        if driver in ("s3", "network_share", "railcall_hosted", "custom"):
            print(
                f"[vault] driver={driver!r} not yet supported in this Studio; "
                f"receipts will land in the local default only",
                file=sys.stderr,
            )
            return NullVaultDriver()
        print(
            f"[vault] unknown driver={driver!r}; ignoring org vault config",
            file=sys.stderr,
        )
        return NullVaultDriver()
    except Exception as e:
        print(
            f"[vault] failed to construct driver={driver!r}: {e}; "
            f"receipts will land in the local default only",
            file=sys.stderr,
        )
        return NullVaultDriver()
