# Security

A browser agent reads attacker-controlled content on every page and acts with the user's identity. WebPilot assumes **the model will eventually be fooled**. The important guarantees are enforced in code, outside the model, and each one has a test or an eval that tries to break it.

## Threat model

| Asset | Threat | Example |
|---|---|---|
| User credentials | Leak to the model provider, logs or an attacker | A page echoes "Welcome demo@acme.test"; an injected review asks the agent to paste the password somewhere |
| User data and session | Exfiltration off-site | A link, a form, an open redirect or an image beacon to `evil.example/?c=<data>` |
| Internal network | SSRF: the agent as a proxy into private services | "Open `http://169.254.169.254/latest/meta-data/`", or the app's own `/api` |
| User money and data | Unwanted purchases, payments, deletions | The model misreads the task, or a page tricks it into clicking "Buy now" |
| Other users' runs | Reading or approving someone else's run | Guessing a run id, calling the API from another machine |
| Budget and availability | Runaway loops, abuse, provider outages | A task that never finishes; a script starting 1,000 runs; a 529 from the model API |
| Answer integrity | Wrong or invented answers | The model claims success without doing the task |

## Controls

### Agent guardrails (`app/agent/guardrails.py`, `app/agent/agent.py`)

| Control | Guarantee |
|---|---|
| **URL policy** (`check_url`) | Only `http(s)`. The host must be in the allow-list (or be a subdomain), compared after lowercasing, stripping the trailing dot and IDN/punycode normalization. `javascript:`, `file:` and `data:` are blocked, and so are lookalikes (`example.com.evil.io`, `notexample.com`, `exämple.com`) and userinfo tricks (`http://127.0.0.1@evil.example`). |
| **SSRF protection** | Private, loopback, link-local (cloud metadata `169.254.169.254`), reserved and unspecified IPs are blocked unless listed exactly. Numeric host forms like `http://2130706433/` never match the allow-list. `BROWSER_DENIED_PATHS` blocks the app's own `/api/`, `/docs`, `/openapi.json`, `/health` and `/sandbox/_state` even on an allowed host, so the agent can't read other runs or approve itself. |
| **Secret placeholders** | The model writes `{{secret:store_password}}`, and the value is substituted at the browser layer after the model call. |
| **Redaction** | Any secret value anywhere in the page view (text *or* element descriptions) is replaced by its placeholder before the model sees it. |
| **Literal password block** | Typing anything other than a placeholder into a `type=password` field is refused. |
| **Human approval** | Clicks on *Place order, Pay, Buy now, Delete, Transfer…* and typing into card, CVV or IBAN fields pause for a human. A timeout counts as a reject, and MCP calls always reject. |
| **Untrusted-content fencing** | Page text sits between `<<<PAGE` and `PAGE>>>`, and the system prompt says it is never instructions. |
| **Injection detection** | Pattern signals add a SECURITY WARNING to the page view and a flag to the trace. |
| **One action per turn** | Each decision is made on a fresh page state. |
| **Budgets** | Per run: `MAX_STEPS`, `MAX_TOKENS_PER_RUN`, `MAX_COST_PER_RUN_USD` (status `budget_exceeded`) and `RUN_TIMEOUT_S`. |
| **Model API failures** | SDK timeouts and retries with exponential backoff on 408/409/429/5xx. If the call still fails, the run ends with status `error` and a clear message, and it never hangs. |

### Open-web mode (the default: `ALLOWED_DOMAINS=["*", ...]`)

The default, so the agent works on any public site. Still enforced: http(s) only; private, loopback, link-local and reserved IPs; internal names (`localhost`, `*.local`, `*.internal`, single-label hosts); disguised numeric IPs; this app's own internal paths; secret placeholders and redaction; human approval. **Given up:** the allow-list's guarantee against exfiltration to an attacker-controlled public site. It's a deliberate trade-off for flexibility, so keep the allow-list for anything that handles sensitive data. The security evals always run with the default allow-list, whatever the local `.env` says.

### Browser network guard (`app/browser/driver.py`)

The URL policy is also installed as a Playwright route on the browser context, so **every request** passes through it: typed URLs, clicked links, form submissions, scripts, images and fetches. Playwright doesn't re-route redirects, so navigation requests are fetched with `max_redirects=0` and the `Location` is checked before the browser may follow it. A `framenavigated` backstop sends the page to `about:blank` if a main frame ever lands off-policy. Service workers (whose requests bypass routing) and downloads are disabled. Blocked requests are reported to the model in the action's outcome.

This closed a real gap in v1.0.0, where the allow-list was checked only for `navigate`. The evals `offsite-link`, `open-redirect` and `form-exfiltration` now prove that all three routes are blocked, using the browser's own network log.

### API (`app/main.py`, `app/runs.py`)

| Control | Guarantee |
|---|---|
| **Authentication** | `Authorization: Bearer <token>`, with tokens mapped to users in `API_KEYS`. Comparison is constant-time (`hmac.compare_digest`). |
| **Secure by default** | With no `API_KEYS`, only loopback clients are accepted. A container or server is closed until tokens are configured, and Docker Compose refuses to start without them. |
| **Authorization** | Runs belong to the user who created them. Another user's run returns `404`, not `403`, so run ids can't be probed. Run ids are 96-bit random. |
| **Rate and concurrency limits** | `RUNS_PER_MINUTE` and `MAX_CONCURRENT_RUNS` per user. Over the limit returns `429` with `Retry-After`. |
| **Security headers** | CSP `default-src 'self'; script-src 'self'; frame-ancestors 'none'…`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`. The UI has no inline scripts, and all model output is HTML-escaped. |
| **Input limits** | Tasks are 3–500 characters, validated by Pydantic. |

### Defense in depth, tested

`tests/test_agent.py::test_gullible_model_cannot_follow_injection` uses a fake model that **does obey** the injected text. The browser still never makes the request. Detection is a signal; the network guard is the guarantee.

## OWASP Top 10 for LLM Applications (2025)

| Risk | Status |
|---|---|
| LLM01 Prompt injection | Mitigated: fencing, detection, network allow-list, approvals |
| LLM02 Sensitive information disclosure | Mitigated: placeholders and redaction, spy-checked in evals |
| LLM05 Improper output handling | Mitigated: tool arguments validated, UI escapes output, CSP |
| LLM06 Excessive agency | Mitigated: small tool set, allow-list, human approval, budgets |
| LLM10 Unbounded consumption | Mitigated: rate/concurrency limits; step, token, cost and time budgets |

## OWASP Top 10 (2025) for the web API

| Risk | Status |
|---|---|
| A01 Broken access control (incl. SSRF) | Owner-scoped runs, 404 on foreign ids, SSRF IP and path blocking |
| A02 Security misconfiguration | Secure-by-default loopback mode, strict headers, non-root Docker user |
| A03 Software supply chain failures | Pinned dependencies, Dependabot for pip, Actions and Docker |
| A07 Authentication failures | Bearer tokens, constant-time comparison, no default token |
| A09 Logging and alerting failures | Structured logs for every step and every blocked request, plus OpenTelemetry traces |
| A10 Mishandling of exceptional conditions | Model/API/browser errors become clean run statuses; timeouts everywhere; fail-closed URL policy |

## Known limitations

- Pattern-based injection detection can be bypassed by paraphrase or encoding. That's why it isn't a guarantee.
- Approval rules are keyword-based. Unusual labels (an icon-only "confirm") need custom rules or a classifier.
- **DNS rebinding:** an allowed domain that resolves to an internal IP isn't detected. Enforce egress at a proxy or firewall in production.
- **WebSockets** aren't routed through the network guard.
- Rate limits and runs are in process memory, so they reset on restart and aren't shared across replicas. Use Redis and a database in production.
- Secrets come from environment variables. In production, use a secrets manager and scope them per user.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
