# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com) and [Semantic Versioning](https://semver.org).

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
