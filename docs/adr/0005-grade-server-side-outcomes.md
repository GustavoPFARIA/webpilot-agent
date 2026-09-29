# ADR 0005: Grade evals on observed outcomes, not the agent's answer

**Status:** Accepted

## Context
Agents often report success they didn't achieve. Grading only on the final text rewards confident wrong answers.

## Decision
Evals verify evidence: the test store's server-side state (submissions, orders), every network request the browser made, whether an approval was requested, the security flags in the trace, and a spy that inspects every payload sent to the LLM for secret values.

## Consequences
- Catches silent failures and leaks. The first eval run found a real redaction gap.
- Needs a controllable target site, which is why the Acme sandbox exists. Evals against real sites would need their own oracles.
