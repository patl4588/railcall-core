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

import datetime
import hashlib
import hmac
import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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


def _resolve_secret_ref(ref: str) -> str:
    """Resolve a *_ref value from vault_config into the actual secret bytes.
    Supported schemes:
      env:VAR_NAME          — read from os.environ
      file:/path/to/secret  — read the file's stripped contents
      keyring:label         — read from the system keyring via the `keyring`
                              module (only if it's importable — no hard dep)

    Every scheme is Studio-side only; the marketplace never sees these values.
    Raises ValueError on unresolved refs so the driver fails fast with a
    clear message the org admin can act on.
    """
    if not isinstance(ref, str):
        raise ValueError(f"secret ref must be a string, got {type(ref).__name__}")
    if ref.startswith("env:"):
        name = ref[4:]
        val = os.environ.get(name)
        if not val:
            raise ValueError(f"env var {name!r} is empty or unset")
        return val
    if ref.startswith("file:"):
        path = os.path.expanduser(ref[5:])
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            raise ValueError(f"cannot read secret file {path!r}: {e}") from e
    if ref.startswith("keyring:"):
        label = ref[8:]
        try:
            import keyring as _kr  # optional dep — install locally if used
        except Exception as e:
            raise ValueError(
                f"keyring: refs require the `keyring` Python package "
                f"(pip install keyring); got: {e}"
            ) from e
        # Two-part label 'service:username' or a bare label ('service').
        if ":" in label:
            service, user = label.split(":", 1)
        else:
            service, user = label, "railcall_vault"
        val = _kr.get_password(service, user)
        if not val:
            raise ValueError(
                f"keyring returned no value for service={service!r} user={user!r}"
            )
        return val
    raise ValueError(
        f"unsupported secret ref scheme in {ref!r}; expected env: / file: / keyring:"
    )


class S3VaultDriver(VaultDriver):
    """Writes to an S3-compatible bucket (AWS S3, MinIO, Cloudflare R2,
    Google Cloud Storage in interop mode). Uses hand-rolled AWS Signature
    Version 4 over urllib — no boto3 dependency, works everywhere Python
    does.

    Object layout under the bucket (optional `prefix` prepended):
        receipts/<schema>-<utc>-<hash>.json     (one object per receipt)
        audit/<utc>-<hash>.jsonl                 (one object per audit line)

    Why one-object-per-line instead of appending: S3 has no append
    primitive — the alternatives are (a) versioned bucket + full re-write
    on each line (O(N) work per audit event, painful for long-running
    orgs) or (b) client-side batching + periodic flush (loses events on
    crash). One-object-per-line is O(1), crash-safe, and cheap on both
    write cost and storage — audit lines are small.
    """

    name = "s3"

    def __init__(
        self,
        bucket: str,
        region: str,
        access_key_ref: str,
        secret_key_ref: str,
        endpoint_url: Optional[str] = None,
        prefix: str = "",
    ):
        if not bucket:
            raise ValueError("S3VaultDriver requires 'bucket'")
        if not region:
            raise ValueError("S3VaultDriver requires 'region'")
        self.bucket = bucket
        self.region = region
        self.access_key = _resolve_secret_ref(access_key_ref)
        self.secret_key = _resolve_secret_ref(secret_key_ref)
        # Endpoint override — MinIO/R2/GCS or an AWS VPC endpoint.
        # Default to the region-specific AWS URL.
        if endpoint_url:
            self.endpoint = endpoint_url.rstrip("/")
        else:
            self.endpoint = f"https://s3.{region}.amazonaws.com"
        self.prefix = prefix.strip("/")
        # Parse endpoint into host — needed for the Host header + sig
        parsed = urllib.parse.urlparse(self.endpoint)
        self.host = parsed.netloc or parsed.path
        self.scheme = parsed.scheme or "https"

    def _key(self, tail: str) -> str:
        return f"{self.prefix}/{tail}" if self.prefix else tail

    def _put(self, key: str, body_bytes: bytes, content_type: str) -> None:
        # AWS SigV4 PUT — https://docs.aws.amazon.com/general/latest/gr/sigv4-signed-request-examples.html
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        service = "s3"
        payload_hash = hashlib.sha256(body_bytes).hexdigest()

        # Path-style URL: /<bucket>/<key>. Every non-AWS S3-compat (MinIO,
        # R2) supports path-style; AWS S3 also accepts it. Simpler than
        # switching between virtual-hosted and path modes.
        # Each path segment is URI-encoded per RFC-3986 unreserved rules.
        def _seg(s: str) -> str:
            return urllib.parse.quote(s, safe="")

        canonical_uri = "/" + _seg(self.bucket) + "/" + "/".join(
            _seg(p) for p in key.split("/") if p
        )
        canonical_querystring = ""
        canonical_headers = (
            f"host:{self.host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = (
            f"PUT\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/{service}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        # Derive signing key (four HMACs down the chain)
        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
        k_date = _hmac(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        k_region = _hmac(k_date, self.region)
        k_service = _hmac(k_region, service)
        k_signing = _hmac(k_service, "aws4_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        authorization = (
            f"{algorithm} Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        url = f"{self.scheme}://{self.host}{canonical_uri}"
        req = urllib.request.Request(
            url,
            data=body_bytes,
            method="PUT",
            headers={
                "Host": self.host,
                "Authorization": authorization,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": amz_date,
                "Content-Type": content_type,
                "Content-Length": str(len(body_bytes)),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.getcode()
            if code >= 300:
                body = r.read()
                raise IOError(f"S3 PUT failed: HTTP {code}: {body!r}")

    def write_receipt(self, receipt: Dict[str, Any], canonical_filename: str) -> None:
        schema = str(receipt.get("schema") or "receipt").replace("/", "_").replace("..", "")
        body = json.dumps(receipt, separators=(",", ":"), sort_keys=True).encode("utf-8")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        h = hashlib.sha256(body).hexdigest()[:12]
        key = self._key(f"receipts/{schema}-{stamp}-{h}.json")
        self._put(key, body, "application/json")

    def append_audit_line(self, entry: Dict[str, Any]) -> None:
        body = (json.dumps(entry, separators=(",", ":")) + "\n").encode("utf-8")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        h = hashlib.sha256(body).hexdigest()[:12]
        key = self._key(f"audit/{stamp}-{h}.jsonl")
        self._put(key, body, "application/jsonl")


class NetworkShareVaultDriver(LocalVaultDriver):
    """SMB/NFS network share driver. The OS handles the actual mount
    (via /etc/fstab, systemd .mount unit, autofs, or `mount` at boot);
    Studio just writes to the mount point. That means this driver IS a
    LocalVaultDriver at the write layer — the only added value is
    checking the mount is present + surfacing a clear error if it isn't.

    Rationale: implementing SMB/NFS in-process would require credentials
    at the wrong layer (Studio ends up holding domain credentials for
    the customer's file share), plus fighting with Windows AD auth
    quirks. Delegating to the OS mount is more secure and matches how
    every serious agent runs on the host anyway.
    """

    name = "network_share"

    def __init__(self, protocol: str, mount_point: str):
        if protocol not in ("smb", "nfs"):
            raise ValueError("NetworkShareVaultDriver: protocol must be 'smb' or 'nfs'")
        self.protocol = protocol
        super().__init__(path=mount_point)

    def _ensure_dirs(self) -> None:
        # Check the mount is actually mounted before we try to write into
        # it. Not foolproof (a mount can vanish mid-write) but catches
        # the common case of "the config points at /mnt/share but nobody
        # mounted it yet" — clearer than a permission-denied error.
        if not os.path.ismount(self.path) and not os.path.isdir(self.path):
            raise IOError(
                f"{self.protocol} mount not found at {self.path!r} — "
                f"mount the share before Studio can write receipts here"
            )
        super()._ensure_dirs()


class CustomVaultDriver(VaultDriver):
    """User-supplied driver. Loaded via importlib from `module_ref`, which
    is 'pkg.module:ClassName'. The class must accept an `options` dict
    kwarg in __init__ and implement `write_receipt` + `append_audit_line`
    matching the VaultDriver interface.

    Trust boundary: this executes Python code from the customer's own
    machine. Configuring driver=custom is opting into arbitrary code
    execution the same way `pip install` is — that's fine because the
    org admin who sets vault_config is the same person who deploys code
    to their machines. We don't add a second gate.

    Example: config `{driver:"custom", module_ref:"acme.vault:SnowflakeVault",
    options:{account:"acme", warehouse:"AUDIT"}}` imports acme.vault,
    instantiates SnowflakeVault(options={"account":"acme","warehouse":"AUDIT"}),
    and delegates every write to that instance.
    """

    name = "custom"

    def __init__(self, module_ref: str, options: Optional[Dict[str, Any]] = None):
        if not module_ref or ":" not in module_ref:
            raise ValueError(
                "CustomVaultDriver: module_ref must be 'pkg.module:ClassName'"
            )
        mod_path, cls_name = module_ref.split(":", 1)
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:
            raise ValueError(
                f"CustomVaultDriver: cannot import {mod_path!r}: {e}"
            ) from e
        cls = getattr(mod, cls_name, None)
        if cls is None:
            raise ValueError(
                f"CustomVaultDriver: {mod_path}.{cls_name} does not exist"
            )
        try:
            self._impl = cls(options=options or {})
        except Exception as e:
            raise ValueError(
                f"CustomVaultDriver: {module_ref} constructor failed: {e}"
            ) from e
        # Duck-type the interface — a clearer error than an AttributeError
        # deep inside the write path six months later.
        for method in ("write_receipt", "append_audit_line"):
            if not callable(getattr(self._impl, method, None)):
                raise ValueError(
                    f"CustomVaultDriver: {module_ref} is missing {method}()"
                )

    def write_receipt(self, receipt: Dict[str, Any], canonical_filename: str) -> None:
        self._impl.write_receipt(receipt, canonical_filename)

    def append_audit_line(self, entry: Dict[str, Any]) -> None:
        self._impl.append_audit_line(entry)


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
        if driver == "s3":
            return S3VaultDriver(
                bucket=config.get("bucket", ""),
                region=config.get("region", ""),
                access_key_ref=config.get("access_key_ref", ""),
                secret_key_ref=config.get("secret_key_ref", ""),
                endpoint_url=config.get("endpoint_url"),
                prefix=config.get("prefix", ""),
            )
        if driver == "network_share":
            return NetworkShareVaultDriver(
                protocol=config.get("protocol", ""),
                mount_point=config.get("mount_point", ""),
            )
        if driver == "custom":
            return CustomVaultDriver(
                module_ref=config.get("module_ref", ""),
                options=config.get("options"),
            )
        # railcall_hosted lands in a separate phase — it requires a
        # marketplace-side ingest endpoint + storage decision that
        # deserves its own design conversation.
        if driver == "railcall_hosted":
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
