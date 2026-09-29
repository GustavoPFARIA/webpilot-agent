# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com) and [Semantic Versioning](https://semver.org).

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
