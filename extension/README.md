# RailCall AI for VS Code

**A local-first AI coding assistant.** Chat with any LLM, send governed messages to Discord and Slack, run web searches — all through your own RailCall Studio running on `localhost`. Your keys, your ledger, your audit trail.

![RailCall AI sidebar](icons/railcall-icon.png)

## What it does

- **Chat with any model** — Anthropic, OpenAI, Groq, xAI, or **local Ollama**. Bring your own keys.
- **Full workspace awareness** — file tree, active file, and file mentions (even absolute paths with spaces) are auto-injected into the AI's context.
- **AI intent classification** — say *"send the folder tree to discord"* and it understands, previews, and only sends after you click **Run**.
- **Live thinking trace** — see every step (`Reading submission_v3.md → ✓ 12 KB → Composing…`) so you know exactly what the assistant is doing.
- **Preview → Confirm → Receipt** — every action gates through a confirmation card. Nothing leaves your machine without an explicit click. Every Discord send, every search returns a real, logged receipt.
- **Refuses to hallucinate** — when a mentioned file can't be read, the extension halts instead of letting the AI invent data.

## Prerequisites

1. **RailCall Studio** running on `localhost:8799`
   ```bash
   curl -fsSL https://raw.githubusercontent.com/patl4588/railcall-core/main/install.sh | bash
   railcall studio
   ```

2. **At least one API key** — add it in `Cmd+,` → search "RailCall":
   - Free: install [Ollama](https://ollama.ai) locally and pull `qwen:7b` (fully offline path)
   - Free API tier: [Groq](https://console.groq.com) — fastest
   - Paid: Anthropic, OpenAI

Keys stay in `~/.railcall/station/.railcall_workspace/keys.local.json` on your machine.

## Usage

Open the RailCall panel from the Activity Bar or Secondary Side Bar. Then:

| You type | What happens |
|---|---|
| `explain how this function works` | Regular AI chat with active-file context |
| `what's in package.json?` | Reads the file, answers from actual contents |
| `send the deploy status to discord` | AI composes the message → preview card → click **Run** → receipt |
| `/discord good morning team` | Fast-path Discord send (no AI compose) |
| `/search DuckDB vs PostgreSQL` | Web search results as a card |

Right-click any selection for **Explain / Fix / Refactor / Generate from comment**.

## Commands

| Command | Shortcut |
|---|---|
| RailCall: Open Chat | `Cmd+Shift+L` |
| RailCall: Explain | `Cmd+Shift+E` (with selection) |
| RailCall: Sync API Keys to Studio | — |
| RailCall: Move to Right Panel | — |

## Settings

- `railcall.serverUrl` — Studio URL (default `http://127.0.0.1:8799`)
- `railcall.discordWebhookUrl`, `railcall.slackWebhookUrl` — for the built-in send actions
- `railcall.groqApiKey`, `railcall.anthropicApiKey`, `railcall.openaiApiKey` — synced to Studio vault
- `railcall.autoSyncKeys` — auto-push settings changes to Studio (default `true`)

## What's actually local vs cloud

| Component | Local? |
|---|---|
| Studio server + cost router + PII firewall | ✅ Local |
| Keys vault + audit log + workflow runner | ✅ Local |
| AI inference (Ollama) | ✅ Local |
| AI inference (Anthropic / OpenAI / Groq) | ❌ BYOK cloud, PII-scrubbed |
| Discord/Slack webhooks | ❌ Their servers |
| Web search (DuckDuckGo) | ❌ Proxied through Studio |

## Links

- **Studio**: https://github.com/patl4588/railcall-core
- **Website**: https://railcall.ai
- **Report a bug**: https://github.com/patl4588/railcall-core/issues

## License

MIT
