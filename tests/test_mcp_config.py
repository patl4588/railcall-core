#!/usr/bin/env python3
"""
Proof for `railcall mcp config` (MCP distribution, item 1.15).

The risky part is not launching the server — it is WRITING TO A FILE THE USER ALREADY
OWNS. People routinely have several MCP servers configured in Claude Desktop. A naive
write would silently delete them. These tests exist mainly to prove that cannot happen.

Run: python3 test_mcp_config.py     (exit 0 iff every check passes)
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import railcall_cli as CLI   # noqa: E402

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-mcp-")
    cfg = os.path.join(tmp, "nested", "claude_desktop_config.json")
    try:
        # ---- 1. fresh install: creates the file and the block ------------------
        res, err = CLI._merge_mcp_config(cfg)
        ok("1a no error on a fresh config", err is None, err)
        ok("1b file created (parent dirs made)", os.path.isfile(cfg))
        doc = json.load(open(cfg, encoding="utf-8"))
        ok("1c railcall server registered", "railcall" in doc["mcpServers"], doc)
        ok("1d invocation points at the installed station's mcp_server.py",
           doc["mcpServers"]["railcall"]["args"][0].endswith(
               os.path.join("workbench", "mcp_server.py")),
           doc["mcpServers"]["railcall"])
        ok("1e no backup made when there was nothing to back up", res["backup"] is None)

        # ---- 2. THE ONE THAT MATTERS: other servers must survive ---------------
        doc = {"mcpServers": {
                   "filesystem": {"command": "npx", "args": ["-y", "@mcp/filesystem"]},
                   "github": {"command": "npx", "args": ["-y", "@mcp/github"]}},
               "someOtherSetting": {"keep": True}}
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        res, err = CLI._merge_mcp_config(cfg)
        after = json.load(open(cfg, encoding="utf-8"))
        ok("2a existing MCP servers are NOT clobbered",
           "filesystem" in after["mcpServers"] and "github" in after["mcpServers"],
           list(after["mcpServers"]))
        ok("2b their definitions are untouched",
           after["mcpServers"]["github"]["args"] == ["-y", "@mcp/github"])
        ok("2c railcall added alongside them", "railcall" in after["mcpServers"])
        ok("2d unrelated top-level settings preserved",
           after.get("someOtherSetting") == {"keep": True}, after.get("someOtherSetting"))
        ok("2e reports how many others were kept", res["others"] == 2, res)
        ok("2f a backup was written before touching the file",
           res["backup"] and os.path.isfile(res["backup"]), res)
        bak = json.load(open(res["backup"], encoding="utf-8"))
        ok("2g the backup holds the ORIGINAL content",
           "railcall" not in bak["mcpServers"] and "github" in bak["mcpServers"])

        # ---- 3. re-running is idempotent, and says so --------------------------
        res, err = CLI._merge_mcp_config(cfg)
        again = json.load(open(cfg, encoding="utf-8"))
        ok("3a re-run does not duplicate or multiply servers",
           len(again["mcpServers"]) == 3, list(again["mcpServers"]))
        ok("3b re-run reports it was an update, not a first registration",
           res["updated"] is True, res)

        # ---- 4. malformed config: refuse rather than destroy -------------------
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json ")
        res, err = CLI._merge_mcp_config(cfg)
        ok("4a invalid JSON is refused, not overwritten", res is None and err is not None, err)
        ok("4b the user's file is left exactly as it was",
           open(cfg, encoding="utf-8").read() == "{ this is not json ")

        print()
        if FAILED:
            print("FAILED (%d): %s" % (len(FAILED), "; ".join(FAILED)))
            return 1
        print("ALL PASS — config merge never clobbers other MCP servers or unrelated "
              "settings, backs up before writing, is idempotent, and refuses to "
              "overwrite a config it cannot parse.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
