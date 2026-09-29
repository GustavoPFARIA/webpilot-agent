# API reference

Base URL `http://127.0.0.1:8000`. OpenAPI docs are at `/docs`.

## `POST /api/runs`

Starts a run in the background.

```json
{"task": "What is the price of the Aurora Headphones?"}
```

`202 Accepted` returns `{"id": "3f9c0a1b2c4d", "status": "running"}`. `422` means the task is empty or longer than 500 characters.

## `GET /api/runs/{id}`

```json
{
  "id": "3f9c0a1b2c4d",
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
  "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "llm_calls": 0},
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
| `error` | Infrastructure error (for example, the browser couldn't start) |

## `POST /api/runs/{id}/approval`

```json
{"approve": true}
```

Returns `200 {"id", "approved"}`, `404` for an unknown run, or `409` if the run is not waiting for approval.

## `GET /api/runs`

Returns the 50 most recent runs, newest first: `[{id, task, status, created_at}]`.

## `GET /health`

`{"status": "ok", "llm_provider": "scripted", "allowed_domains": [...]}`
