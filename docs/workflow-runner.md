# Workflow Runner

`workflow_runner.py` — generic pipeline executor for RailCall.

Installed at `~/.railcall/station/workbench/workflow_runner.py`.

## Concept

A workflow is a list of typed **nodes**. The executor runs them in order,
passing each node's output as the next node's input. If a node outputs a
list and the next node is a scalar processor, the executor fans out: runs
it once per item and collects results.

```
csv_read → message_template → discord_send
  [rows]      [strings]         [send receipt]
```

## CLI usage

```bash
# set credentials once
railcall set discord-webhook https://discord.com/api/webhooks/{id}/{token}
railcall set ollama-host http://localhost:11434   # if non-default

# dry-run (preview, nothing sent)
railcall workflow run contacts.csv

# live send
railcall workflow run contacts.csv --live

# custom template
railcall workflow run contacts.csv --template "{{name}} joined as {{role}}!" --live

# send to Slack
railcall set slack-webhook https://hooks.slack.com/services/…
railcall workflow run contacts.csv --dest slack --live
```

## Spec format

```json
{
  "name": "csv_to_discord",
  "steps": [
    { "id": "read",   "type": "csv_read",        "config": { "path": "/data/contacts.csv" } },
    { "id": "filter", "type": "filter",           "config": { "field": "active", "value": "yes" } },
    { "id": "format", "type": "message_template", "config": { "template": "{{name}} · {{email}}" } },
    { "id": "send",   "type": "discord_send",     "config": {} }
  ]
}
```

## Node types

| Node | Input | Output | Config |
|---|---|---|---|
| `csv_read` | — | `list[dict]` | `path` |
| `message_template` | `list[dict]` or `dict` | `list[str]` | `template` (`{{field}}` tokens) |
| `filter` | `list` | `list` | `field`, `value` or `not_empty: true` |
| `limit` | `list` | `list` | `n` (default 10) |
| `discord_send` | `list[str]` | send receipt | `webhook_url`, `dry_run` |
| `slack_send` | `list[str]` | send receipt | `webhook_url`, `dry_run` |
| `http_request` | any | response | `url`, `method`, `dry_run` |

## Credential resolution

Config values of the form `{{vault.provider.FIELD}}` are resolved from
`~/.railcall/station/.railcall_workspace/keys.local.json` at run time.

Priority order for Discord webhook URL:
1. `config.webhook_url` in the spec
2. `{{vault.discord.DISCORD_WEBHOOK_URL}}` in the vault
3. `DISCORD_WEBHOOK_URL` environment variable
4. If none: forced dry-run

## Studio API

```
POST /api/workflow/execute
{
  "spec": { "name": "...", "steps": [...] },
  "dry_run": false
}
```

Response:
```json
{
  "ok": true,
  "run_id": "c6438b42",
  "name": "csv_to_discord",
  "steps": [
    { "id": "read",   "type": "csv_read",   "ok": true, "output_count": 3, "duration_ms": 5 },
    { "id": "format", "type": "message_template", "ok": true, "output_count": 3, "duration_ms": 0 },
    { "id": "send",   "type": "discord_send", "ok": true,
      "output": { "sent": 3, "errors": [], "dry_run": false }, "duration_ms": 2468 }
  ],
  "summary": "3 message(s) sent via discord send"
}
```

## Python API

```python
import sys
sys.path.insert(0, "~/.railcall/station/workbench")
import workflow_runner as wr

spec = {
    "name": "csv_to_discord",
    "steps": [
        {"id": "read",   "type": "csv_read",          "config": {"path": "/data/contacts.csv"}},
        {"id": "format", "type": "message_template",   "config": {"template": "{{name}} · {{email}}"}},
        {"id": "send",   "type": "discord_send",       "config": {}},
    ],
}

result = wr.run(spec, vault={"discord": {"DISCORD_WEBHOOK_URL": "https://…"}}, dry_run=False)
print(result["summary"])  # "3 message(s) sent via discord send"
```

## Receipt format

Every run returns:
```json
{
  "ok": true,
  "run_id": "c6438b42",
  "name": "workflow name",
  "steps": [ { "id", "type", "ok", "duration_ms", "output_count | output | error" } ],
  "summary": "human-readable outcome"
}
```

If any step fails, the executor stops immediately (`ok: false`) and the
failing step carries an `error` string. Steps after the failure are not run.

## Adding a new node type

Add a function and register it in `NODE_REGISTRY` in `workflow_runner.py`:

```python
def _my_node(cfg, inp, vault):
    # inp is the output of the previous step
    # cfg is the resolved config dict
    # vault is the full keys.local.json dict
    return "transformed output"

NODE_REGISTRY["my_node"] = _my_node
```
