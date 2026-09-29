## What and why

<!-- What does this change and why is it needed? -->

## How it was tested

- [ ] `ruff check . && ruff format --check .`
- [ ] `pytest -q`
- [ ] `python -m evals.run_evals --min-pass-rate 1.0`
- [ ] New agent behavior has an eval case in `evals/dataset.json`

## Safety

- [ ] Guardrail guarantees are preserved: allow-list, secret placeholders, redaction, human approval (explain below if touched)
- [ ] No real credentials or personal data added
