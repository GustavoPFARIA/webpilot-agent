# Contributing

Thanks for helping! This project values safety guarantees and measurable behavior over features.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install                                         # deps + Chromium (or export BROWSER_CHANNEL=msedge / chrome)
pre-commit install                                   # ruff, mypy and file checks on every commit
```

## Before opening a pull request

```bash
make check    # ruff, mypy, pip-audit, pytest with coverage >= 85%, evals at 100%
```

## Guidelines

- **Guardrails stay in code.** Don't move a guarantee into the prompt. If you touch `app/agent/guardrails.py`, add tests for both the allowed and the blocked case.
- **New agent behavior needs an eval** in `evals/dataset.json`, graded on observable outcomes.
- **Keep the page view compact.** Every token in `PageState.render` is paid on every step.
- **Never commit real credentials.** Use `.env`, which is git-ignored, and `{{secret:NAME}}` placeholders.
- Commits: short imperative subject ("Add select_option to scripted policy").

## Architecture decisions

Significant design changes get an ADR in `docs/adr/`.
