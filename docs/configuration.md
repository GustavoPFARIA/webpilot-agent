# Configuration

Settings are read from environment variables or a `.env` file (see [`.env.example`](../.env.example)) by `app/config.py`, which uses pydantic-settings. Lists and dicts are JSON.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto` (first key found: Anthropic, OpenAI, Gemini; offline policy if none), `anthropic`, `openai`, `gemini` or `scripted` |
| `GEMINI_API_KEY` | – | Free tier at aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Any Gemini model with function calling |
| `OPENAI_BASE_URL` | – | Any OpenAI-compatible server (Ollama, Groq, OpenRouter, vLLM) |
| `LLM_MIN_INTERVAL_S` | provider default | Minimum seconds between model calls (Gemini free tier: 6.5) |
| `ANTHROPIC_API_KEY` | – | Required for `anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Any Claude model with tool use |
| `OPENAI_API_KEY` | – | Required for `openai` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Any model with function calling |
| `BROWSER_CHANNEL` | *(empty)* | Empty uses Playwright's Chromium; `msedge` or `chrome` use an installed browser |
| `HEADLESS` | `true` | Set `false` to watch the browser |
| `MAX_STEPS` | `15` | Step budget per run |
| `APPROVAL_TIMEOUT_S` | `300` | A pending approval is treated as a reject after this |
| `ALLOWED_DOMAINS` | `["*","127.0.0.1","localhost"]` | `"*"` = any public website (internal networks, cloud metadata and this app's API still blocked). Replace it with exact hosts (subdomains included) for allow-list mode |
| `SECRETS` | demo store account | `{"name": "value"}` used through `{{secret:name}}` placeholders |
| `BROWSER_DENIED_PATHS` | `["/api/","/docs","/redoc","/openapi.json","/health","/sandbox/_state"]` | Paths the browser may never load on any host (the app's internals) |
| `PUBLIC_URL` | *(from the request)* | Where the browser can reach this server; the agent's default start page is `{PUBLIC_URL}/sandbox/`. Leave it empty locally; set it when the browser must use a different address than the user (e.g. inside Docker) |

## API access

| Variable | Default | Description |
|---|---|---|
| `API_KEYS` | `{}` | `{"token": "user"}`. Empty means only loopback clients are accepted (local use). Set it for any deployment. |

## Limits and budgets

| Variable | Default | Description |
|---|---|---|
| `RUNS_PER_MINUTE` | `10` | New runs per user per minute (over the limit returns `429`) |
| `MAX_CONCURRENT_RUNS` | `2` | Runs in progress per user |
| `RUN_TIMEOUT_S` | `600` | Wall-clock limit per run |
| `MAX_TOKENS_PER_RUN` | `300000` | Input + output + cache-read tokens |
| `MAX_COST_PER_RUN_USD` | `1.00` | Stops the run with `budget_exceeded` |
| `PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` / `PRICE_CACHE_READ_PER_MTOK` | provider default | USD per million tokens for cost tracking. Defaults: Claude 3.00 / 15.00 / 0.30, OpenAI 0.40 / 1.60 / 0.10, Gemini free tier 0 |

## Resilience and observability

| Variable | Default | Description |
|---|---|---|
| `LLM_TIMEOUT_S` | `60` | Per model API call |
| `LLM_MAX_RETRIES` | `3` | SDK retries with exponential backoff (429, 5xx, connection errors) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | – | Send traces to an OTLP/HTTP collector |
| `OTEL_CONSOLE` | `false` | Print spans to stdout |

## Pointing it at real sites

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ALLOWED_DOMAINS=["wikipedia.org","books.toscrape.com"]
```

Keep the allow-list as narrow as the task needs. It's the control that holds when everything else fails.
