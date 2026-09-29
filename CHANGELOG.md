# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com) and [Semantic Versioning](https://semver.org).

## [1.5.0] - 2026-09-29

### Changed
- **Any public website works out of the box** (`ALLOWED_DOMAINS` defaults to `["*","127.0.0.1","localhost"]`). Private networks, cloud metadata, disguised IPs and this app's API stay blocked. The strict allow-list is one line of configuration away, and the security evals always run in that mode.

## [1.4.0] - 2026-09-29

### Added
- Open-web mode (`ALLOWED_DOMAINS=["*", ...]`): browse any public website while internal networks, cloud metadata, disguised IPs and this app's API stay blocked. Verified with Gemini on python.org.

### Fixed
- Internal-path blocking (`/api/`, `/docs`...) now applies only to this app's own hosts, not to every website.
- Security evals no longer depend on the local `.env`; they always use the default allow-list.

## [1.3.1] - 2026-09-29

### Fixed
- The agent's start page now comes from the address the user opened, so the app works on any port without setting `PUBLIC_URL` (found by testing a fresh clone the way a reviewer would).

## [1.3.0] - 2026-09-29

### Added
- Google Gemini as a model provider through its OpenAI-compatible API, including the **free tier** (no card needed).
- `OPENAI_BASE_URL`, so any OpenAI-compatible server works (Ollama locally, Groq, OpenRouter, vLLM).
- `LLM_PROVIDER=auto` (new default): uses whichever key is configured, and falls back to the offline policy only when there is none.
- Client-side request spacing (`LLM_MIN_INTERVAL_S`) and longer retries for free-tier rate limits.
- Per-provider default prices for cost tracking (Gemini free tier = $0).

- Automatic model fallback with cooldown when a model is overloaded (503) or rate-limited (429), and the model actually used is recorded per call (`usage.models`, `gen_ai.response.model` span attribute).
- **Real-model results: 16/16 evals with Gemini** (`evals/results-gemini-3.8-flash.md`), plus a check against a real public website.

### Changed
- Tool schemas avoid keywords that some providers reject (`default`).
- The system prompt defines when a task counts as successful. The real model had reported success on blocked or impossible tasks.
- Security evals are graded on evidence from the trace and the network log (`blocked_by_policy`), not on exact wording.

### Fixed
- Gemini 3 function calling: thought signatures are round-tripped (`extra_content`), and stripped before calling Claude.
- Eval report filenames are valid on Windows, and multi-line answers no longer break the results table.

## [1.2.0] - 2026-09-29

### Added
- Engineering quality gates in CI: mypy, Ruff security rules (Bandit), pip-audit, coverage floor (85%), Python 3.12 + 3.13 matrix, CodeQL.
- Docker smoke test: CI runs the image and completes a real browser task inside it (`scripts/smoke_test.py`).
- Tests for the Claude and OpenAI adapters, the full stack over HTTP with approval, unreachable sites and sandbox hardening (88 in total, 89% coverage).
- Pre-commit hooks, Makefile, UI example for the open-redirect attack, refreshed demo GIF.

### Fixed
- The OpenAI adapter crashed on custom tool calls, missing `usage` or malformed JSON arguments; it now degrades to a recoverable error.
- An unreachable allowed host crashed the network guard; the navigation now fails cleanly.
- A backstop navigation task could be garbage-collected before running.
- The API-token bar was always visible (`display` overrode `hidden`).
- Clearer messages when a link, redirect or form is blocked.

### Security
- Resolved all CodeQL findings in the test store: pages now render through Jinja2 with autoescaping (XSS), forged session cookies are never echoed back and the session id rotates on login (cookie injection, session fixation), and the deliberate open redirect only targets relative paths or the reserved `.example` TLD, so a deployed copy can't redirect real users.

## [1.1.0] - 2026-09-29

### Security
- **Network-level allow-list:** every browser request (links, forms, scripts, redirects) is checked, not only `navigate`. Redirect targets are checked before they are followed. Closes an exfiltration gap in 1.0.0.
- **SSRF protection:** private, loopback, link-local (cloud metadata) and reserved IPs are blocked unless listed; the app's own `/api` and internal paths are denied to the browser; hosts are normalized (case, trailing dot, IDN).
- **Authentication and authorization:** bearer tokens (`API_KEYS`), owner-scoped runs, 404 on foreign ids, loopback-only when no tokens are configured.
- **Security headers:** CSP without inline scripts, `X-Frame-Options`, `nosniff`, `Referrer-Policy`.

### Added
- Per-user rate and concurrency limits (`429` with `Retry-After`).
- Token, dollar and wall-clock budgets per run (`budget_exceeded`); cost in USD in `usage` and in the UI.
- Model API timeouts and retries with backoff; failures end the run with status `error`.
- OpenTelemetry tracing with GenAI semantic conventions (OTLP or console).
- 5 new evals (off-site link, open redirect, form exfiltration, SSRF to the internal API and to cloud metadata): 16 in total.
- 21 new tests (68 in total). ADRs 0006 and 0007. `docs/observability.md`.

### Fixed
- Page snapshots retry when a late navigation destroys the page context.

## [1.0.0] - 2026-09-28

### Added
- Browser agent loop (observe, decide, check, act) with one action per turn and a step budget.
- Playwright driver and an indexed text page view.
- Claude (tool use, prompt caching) and OpenAI (function calling) adapters, plus a deterministic scripted policy for offline runs.
- Guardrails: domain allow-list, prompt-injection detection, secret placeholders and redaction, literal-password block, human approval for sensitive actions.
- FastAPI API and web UI with a live step trace, screenshots and Approve/Reject.
- MCP server exposing `run_browser_task`.
- Acme Store sandbox and 11 end-to-end evals graded on server-side outcomes.
- 47 tests, CI (lint, tests, evals, Docker build), Dependabot, docs and ADRs.

### Fixed
- Secret values could reach the model through element descriptions after typing. The whole page view is now redacted. Found by the `login-secrets` eval.
