# MCP server

WebPilot runs as a [Model Context Protocol](https://modelcontextprotocol.io) server, so another agent can delegate web work to it with one tool call.

```bash
python -m app.mcp_server   # stdio transport
```

## Tool

`run_browser_task(task: string)` returns:

```json
{
  "status": "done",
  "answer": "Aurora Headphones costs $149.00.",
  "steps": ["1. navigate {...} -> Opened ...", "2. type_text {...} -> ...", "..."]
}
```

## Client configuration

Claude Desktop (`claude_desktop_config.json`) or any MCP client:

```json
{
  "mcpServers": {
    "webpilot": {
      "command": "/path/to/webpilot-agent/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/webpilot-agent",
      "env": {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-...", "ALLOWED_DOMAINS": "[\"wikipedia.org\"]"}
    }
  }
}
```

With Claude Code:

```bash
claude mcp add webpilot -- /path/to/.venv/bin/python -m app.mcp_server
```

## Safety

There is no human watching an MCP call, so the approver is `deny_all`. Purchases, payments and deletions are always refused. The allow-list, secret handling and redaction all apply as usual. `tests/test_e2e.py` drives the server through a real MCP client.
