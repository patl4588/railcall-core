# RailCall × MCP

**Status:** Planned. Not yet implemented.
**Owner:** —
**Target:** After first commercial launch (post-30-day window).

---

## 1. What is MCP

**MCP (Model Context Protocol)** is Anthropic's open standard, launched November 2024, for connecting AI clients to external tools and data sources over a shared JSON-RPC protocol.

Three roles:

- **MCP client** — the AI app (Claude Desktop, Cursor, Windsurf, Zed, Cline, VS Code Copilot, etc.)
- **MCP server** — the thing exposing capabilities (a filesystem, a database, GitHub, RailCall)
- **Protocol** — JSON-RPC over stdio (local) or HTTP+SSE (remote), standardized

A server exposes three primitive types:

| Primitive | What it is | RailCall example |
|---|---|---|
| **Tools** | Functions the client can call | `send_discord(message)`, `execute_workflow(spec)` |
| **Resources** | Data the client can read | `integration_audit.jsonl`, `cost_ledger.jsonl` |
| **Prompts** | Reusable prompt templates | Workflow builder system prompt |

Every major AI client either supports MCP today or has a public plan to. It is becoming table stakes.

---

## 2. Why RailCall needs an MCP server

**RailCall already IS a governance layer.** MCP turns it into *the* governance layer for anyone else's AI client.

### The strategic argument

Today, a user picks *one* AI coding tool (Cursor OR VS Code OR Claude Desktop) and lives in it. Each tool re-implements the same integrations badly — Discord, filesystem, shell, GitHub — with no shared audit trail, no shared BYOK vault, no shared cost ledger.

With a RailCall MCP server:

- The user runs `railcall studio` **once**.
- Their Claude Desktop, their Cursor, their VS Code, and any future client all point at the same local server.
- **Every AI action across every tool gets receipted into the same `integration_audit.jsonl`.**
- The BYOK vault, PII firewall, cost router, and audit log serve *every* tool the user has.

We go from "install our VS Code extension" to "install our governance layer once, use it from every AI tool you own."

### Why it's a moat, not just a feature

- Cursor and Copilot can't ship an MCP server that governs *themselves* — they'd be admitting their own tool is inspectable in a way that undermines their closed-cloud model.
- Anthropic and OpenAI won't ship a governance MCP either — they *are* the vendor being governed.
- The MCP server is philosophically only buildable by someone who already believes in local-first + BYOK + audit-first. That's a very short list.

### Compliance tailwind

As AI governance regulation (EU AI Act, SOC 2 AI, state-level bills) tightens, every tool needs to answer "what did the AI do?" RailCall's MCP server is the compliant substrate any AI client can bolt onto without rebuilding themselves.

---

## 3. What to implement

### 3.1 Package

- Name: `railcall-mcp`
- Language: Python (matches Studio)
- Distribution: PyPI + bundled with station tarball
- Transport: **stdio first** (works with Claude Desktop, Cursor, Windsurf, Zed today); HTTP+SSE later for remote/team scenarios
- Auth: none needed for stdio (process-local); token-based when we add HTTP+SSE

### 3.2 Tools to expose

All wrap existing Studio HTTP endpoints — the MCP server is a thin translator, not a rewrite.

| MCP Tool | Wraps | Requires preview? |
|---|---|---|
| `railcall_chat` | `POST /api/chat/local` | No — chat is read-only |
| `railcall_discord_send` | `POST /api/discord/send` | **Yes — client must show preview + get user confirmation** |
| `railcall_slack_send` | `POST /api/slack/send` (to add) | Yes |
| `railcall_web_search` | `POST /api/web_search` | No |
| `railcall_execute_workflow` | `POST /api/workflow/execute` | Yes |
| `railcall_list_workflows` | `GET /api/flow/sources` | No |
| `railcall_sync_settings` | `POST /api/settings/sync` | Yes — key change is sensitive |
| `railcall_read_receipt` | Read from `.railcall_workspace/receipts/` | No |

**Confirmation is enforced client-side** via MCP's tool metadata (`readOnlyHint`, `destructiveHint`, `openWorldHint`). Claude Desktop and Cursor already gate destructive tools behind a user prompt.

### 3.3 Resources to expose

Read-only data the AI client can request as context.

| MCP Resource | URI | Source |
|---|---|---|
| Integration audit log | `railcall://audit-log` | `~/.railcall/station/.railcall_workspace/integration_audit.jsonl` |
| Cost ledger | `railcall://cost-ledger` | `~/.railcall/station/.railcall_workspace/cost_ledger.jsonl` |
| Workflow receipts | `railcall://receipts/{id}` | `~/.railcall/station/.railcall_workspace/receipts/*.json` |
| Keys status (redacted) | `railcall://keys/status` | `keys.local.json` — provider names only, never values |
| Available workflows | `railcall://workflows` | `~/.railcall/station/workbench/flows/` |

### 3.4 Prompts to expose

Reusable templates the client can inject.

| Prompt | Purpose |
|---|---|
| `railcall_governed_action` | System prompt: "Never claim to send/execute without going through the preview → confirm → receipt flow" |
| `railcall_workflow_builder` | The workflow builder system prompt from Studio |
| `railcall_compose_discord` | The Discord composition prompt from the VS Code extension |

### 3.5 Config generator

CLI command that outputs ready-to-paste config for each client:

```bash
railcall mcp config claude-desktop   # writes ~/Library/Application Support/Claude/config.json
railcall mcp config cursor           # outputs Cursor MCP config JSON
railcall mcp config windsurf         # outputs Windsurf MCP config JSON
railcall mcp config --stdio          # prints stdio invocation for any client
```

Zero manual editing — the user runs one command and the client picks up RailCall on next restart.

---

## 4. How we communicate it

### 4.1 One-line pitch

> **RailCall MCP: one governance layer, every AI tool.**
> Install once. Claude Desktop, Cursor, VS Code, and every future MCP client route through your local receipts, your BYOK vault, and your audit trail.

### 4.2 Landing page section

Under the existing "How it works" block, add a **Universal Layer** section:

```
✓ Works with Claude Desktop
✓ Works with Cursor
✓ Works with Windsurf
✓ Works with Zed
✓ Works with any MCP-compatible AI client

One vault. One ledger. One audit trail. Every tool you use.
```

### 4.3 README section (root)

New heading in `railcall-core/README.md`:

```markdown
## Use RailCall from any AI client (MCP)

RailCall exposes an MCP server so Claude Desktop, Cursor, and any other
MCP-compatible AI client can drive it directly. One command:

    railcall mcp config claude-desktop

Restart your client. It now has RailCall's Discord send, web search,
workflow execution, and audit trail — governed, BYOK, receipted.
```

### 4.4 Distribution channels (post-launch)

- Post to `r/ClaudeAI`, `r/cursor`, `r/LocalLLaMA`
- Submit to [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (the official directory)
- Demo video: user says "send deploy status to discord" in **Cursor** → Cursor's Claude calls RailCall's MCP server → receipt appears in RailCall's audit log → user shows both windows side by side

The demo is the pitch. Showing one command in Cursor pulling from RailCall's local ledger is more convincing than any marketing copy.

### 4.5 Positioning inside the "moat" conversation

RailCall MCP is not "another integration." It's the argument that **RailCall isn't a competitor to Cursor — it's underneath Cursor**. That reframe is worth practicing:

- ❌ "RailCall is a better Cursor."
- ✅ "RailCall is what Cursor should have been built on."

Every future AI client that adopts MCP becomes a potential surface for RailCall. We don't need to win the client war; we win by being the layer everyone standardizes on.

---

## 5. Implementation phases

| Phase | Scope | Duration | Ships |
|---|---|---|---|
| **1** | Basic stdio MCP server with 3 tools (`chat`, `discord_send`, `web_search`) | ~3 days | `railcall-mcp` on PyPI + `railcall mcp config claude-desktop` command |
| **2** | Resources: audit log, cost ledger, workflow receipts | ~2 days | Claude Desktop can read RailCall's audit trail as native context |
| **3** | Workflow execution tool + workflow list resource + governed_action prompt | ~3 days | Cursor + Claude Desktop can execute governed workflows end-to-end |
| **4** | Config generators for Cursor, Windsurf, Zed + submit to MCP server directory + demo video | ~2 days | Publicly discoverable, one-command install for every major client |

**Total:** ~10 working days after the extension is commercialized. Not in the 30-day window; the immediate next thing after it.

---

## 6. Open questions

- **HTTP+SSE transport for team scenarios.** Does a team RailCall (shared vault, shared audit) make sense, or does that break the local-first thesis? Probably: yes for teams under 20, no for enterprise (enterprise gets a self-hosted Studio + Tailscale). Decide before Phase 4.
- **Do we need MCP client capabilities too?** i.e. can RailCall Studio itself act as an MCP client and call *other* MCP servers (GitHub, Postgres, etc.)? This would let the workflow runner invoke third-party tools with the same governance layer. Almost certainly yes — but out of scope for the first pass.
- **How do we handle tool-use auth in stdio?** The MCP client (Cursor, Claude Desktop) is trusted because it's local. But when the AI decides to call `railcall_discord_send`, do we require an additional in-Studio confirmation, or trust the client's approval UI? Recommendation: trust the client for stdio, require Studio confirmation for HTTP+SSE.

---

## 7. What's already built vs. what's missing

| Component | Status |
|---|---|
| Studio HTTP endpoints to wrap | ✅ Built (`/api/chat/local`, `/api/discord/send`, `/api/web_search`, `/api/settings/sync`) |
| Audit log file | ✅ Built (`integration_audit.jsonl`) |
| Cost ledger file | ✅ Built (`cost_ledger.jsonl`) |
| Workflow receipts | ✅ Built (`.railcall_workspace/receipts/*.json`) |
| MCP Python SDK | ✅ Available (`mcp` package on PyPI) |
| `railcall-mcp` package | ❌ Not started |
| `railcall mcp config` CLI subcommand | ❌ Not started |
| PyPI publish + versioning | ❌ Not set up |
| Demo video | ❌ Not started |
| Submit to MCP server directory | ❌ Not started |

Everything the MCP server needs to expose already exists. It's ~200 lines of glue code plus distribution. Small effort, large surface expansion.
