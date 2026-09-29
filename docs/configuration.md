# Configuration

Settings are read from environment variables or a `.env` file (see [`.env.example`](../.env.example)) by `app/config.py`, which uses pydantic-settings. Lists and dicts are JSON.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `scripted` | `scripted` (offline deterministic policy), `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | – | Required for `anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Any Claude model with tool use |
| `OPENAI_API_KEY` | – | Required for `openai` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Any model with function calling |
| `BROWSER_CHANNEL` | *(empty)* | Empty uses Playwright's Chromium; `msedge` or `chrome` use an installed browser |
| `HEADLESS` | `true` | Set `false` to watch the browser |
| `MAX_STEPS` | `15` | Step budget per run |
| `APPROVAL_TIMEOUT_S` | `300` | A pending approval is treated as a reject after this |
| `ALLOWED_DOMAINS` | `["127.0.0.1","localhost"]` | Hosts (and subdomains) the agent may open |
| `SECRETS` | demo store account | `{"name": "value"}` used through `{{secret:name}}` placeholders |
| `PUBLIC_URL` | `http://127.0.0.1:8000` | Where the server is reachable; the agent's default start page is `{PUBLIC_URL}/sandbox/` |

## Pointing it at real sites

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ALLOWED_DOMAINS=["wikipedia.org","books.toscrape.com"]
```

Keep the allow-list as narrow as the task needs. It's the control that holds when everything else fails.
