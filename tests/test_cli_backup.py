"""test_cli_backup.py — railcall backup / restore / backup-verify (B3 durability).

The customer's signed receipts + hash-chained policy history ARE the compliance
record; they live on one machine. These commands make that record portable and
self-verifying so a machine death doesn't lose the audit trail. This gate pins:
  - a clean backup self-verifies (every sha256 + policy chain + signature);
  - SECRETS are never bundled (keys.local.json excluded by construction);
  - tamper is caught (a mutated byte fails verify);
  - restore REFUSES a failed archive, and won't silently roll a newer policy
    chain backward without --force;
  - restore never writes a secret back.

Run: python3 -m pytest tests/test_cli_backup.py -v
"""

import json
import os
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import railcall_cli as cli  # noqa: E402


def _seed_ws(policy_versions=2):
    ws = tempfile.mkdtemp(prefix="rc_bk_ws_")
    os.makedirs(os.path.join(ws, "receipts", "capoff"), exist_ok=True)
    json.dump({"schema": "railcall_github_apply_receipt.v1", "mode": "live"},
              open(os.path.join(ws, "receipts", "capoff", "github__live_1.json"), "w"))
    with open(os.path.join(ws, "approval_policy_history.jsonl"), "w") as fh:
        for v in range(1, policy_versions + 1):
            fh.write(json.dumps({"to_version": v,
                                 "prev_integrity": ("h%d" % (v - 1) if v > 1 else None),
                                 "integrity_hash": "h%d" % v}) + "\n")
    json.dump({"GROQ_API_KEY": "gsk_secret_never_backed_up"},
              open(os.path.join(ws, "keys.local.json"), "w"))  # MUST be excluded
    return ws


def _backup(ws):
    cli._station_ws = lambda: ws
    out = os.path.join(tempfile.mkdtemp(), "b.tgz")
    assert cli.cmd_backup([out]) == 0
    return out


def test_clean_backup_self_verifies():
    out = _backup(_seed_ws())
    ok, _, bad = cli._verify_backup(out)
    assert ok and bad == 0


def test_secrets_are_never_bundled():
    out = _backup(_seed_ws())
    names = tarfile.open(out).getnames()
    assert not any("keys.local" in n for n in names)
    assert any(n.endswith("github__live_1.json") for n in names)
    assert any(n.endswith("approval_policy_history.jsonl") for n in names)


def test_tamper_is_caught():
    out = _backup(_seed_ws())
    ext = tempfile.mkdtemp()
    with tarfile.open(out) as t:
        t.extractall(ext)
    p = os.path.join(ext, "workspace", "receipts", "capoff", "github__live_1.json")
    d = json.load(open(p)); d["mode"] = "HACKED"; json.dump(d, open(p, "w"))
    tam = out + ".tam"
    with tarfile.open(tam, "w:gz") as t:
        t.add(os.path.join(ext, "MANIFEST.json"), arcname="MANIFEST.json")
        for r, _, fs in os.walk(os.path.join(ext, "workspace")):
            for f in fs:
                fp = os.path.join(r, f)
                t.add(fp, arcname=os.path.relpath(fp, ext))
    ok, _, bad = cli._verify_backup(tam)
    assert (not ok) and bad >= 1
    cli._station_ws = lambda: tempfile.mkdtemp()
    assert cli.cmd_restore([tam]) == 1          # restore refuses a failed archive


def test_restore_roundtrip_excludes_secret():
    out = _backup(_seed_ws())
    ws2 = tempfile.mkdtemp(); cli._station_ws = lambda: ws2
    assert cli.cmd_restore([out]) == 0
    assert os.path.isfile(os.path.join(ws2, "receipts", "capoff", "github__live_1.json"))
    assert not os.path.isfile(os.path.join(ws2, "keys.local.json"))


def test_restore_wont_regress_a_newer_chain_without_force():
    out = _backup(_seed_ws(policy_versions=2))   # backup head = v2
    ws3 = tempfile.mkdtemp(); cli._station_ws = lambda: ws3
    with open(os.path.join(ws3, "approval_policy_history.jsonl"), "w") as fh:  # on-disk head = v5
        for v in range(1, 6):
            fh.write(json.dumps({"to_version": v,
                                 "prev_integrity": ("h%d" % (v - 1) if v > 1 else None),
                                 "integrity_hash": "h%d" % v}) + "\n")
    assert cli.cmd_restore([out]) == 1           # refuses (would roll back)
    assert cli.cmd_restore([out, "--force"]) == 0
