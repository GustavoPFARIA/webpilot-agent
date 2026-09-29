# API reference

Base URL `http://127.0.0.1:8000`. OpenAPI docs are at `/docs`.

## Authentication

When `API_KEYS` is set, every `/api` route needs `Authorization: Bearer <token>`, and a missing or wrong token returns `401`. Without `API_KEYS`, only requests from the same machine (loopback) are accepted.

Runs are private to the user who created them. Another user's run id returns `404`.

## `POST /api/runs`

Starts a run in the background.

```json
{"task": "What is the price of the Aurora Headphones?"}
```

`202 Accepted` returns `{"id": "Xq3v9LmT0aBcDeFg", "status": "running"}`. `422` means the task is empty or longer than 500 characters. `429` (with `Retry-After`) means the user is over `RUNS_PER_MINUTE` or `MAX_CONCURRENT_RUNS`.

## `GET /api/runs/{id}`

```json
{
  "id": "Xq3v9LmT0aBcDeFg",
  "task": "Buy the Aurora Headphones.",
  "status": "awaiting_approval",
  "answer": "",
  "model": "claude-sonnet-5-5",
  "pending": {
    "action": "click",
    "args": {"element_id": 8},
    "element": "[8] button \"Place order\"",
    "reason": "Clicking 'Place order' can spend money or change data."
  },
  "steps": [
    {
      "n": 1, "action": "navigate", "args": {"url": "http://127.0.0.1:8000/sandbox/"},
      "outcome": "Opened http://127.0.0.1:8000/sandbox/", "ok": true,
      "url": "http://127.0.0.1:8000/sandbox/", "thought": "", "flags": [],
      "latency_ms": 212, "screenshot": "<base64 jpeg>"
    }
  ],
  "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "llm_calls": 0, "cost_usd": 0.0},
  "created_at": "2026-09-28T23:49:42+00:00"
}
```

`usage` is filled in when the run finishes.

| `status` | Meaning |
|---|---|
| `running` | Working |
| `awaiting_approval` | Paused; see `pending` |
| `done` | Finished successfully |
| `failed` | The agent reported it couldn't complete the task |
| `rejected` | A human rejected a sensitive action |
| `max_steps` | Step budget exhausted |
| `budget_exceeded` | Token or cost budget exhausted |
| `error` | Model API failure after retries, timeout, or infrastructure error |

## `POST /api/runs/{id}/approval`

```json
{"approve": true}
```

Returns `200 {"id", "approved"}`, `404` for an unknown run, or `409` if the run is not waiting for approval.

## `GET /api/runs`

Returns the 50 most recent runs, newest first: `[{id, task, status, created_at}]`.

## `GET /health`

`{"status": "ok", "llm_provider": "scripted", "allowed_domains": [...], "auth": "loopback_only"}`
