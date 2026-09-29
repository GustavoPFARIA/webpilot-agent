# ADR 0004: A deterministic scripted policy as the model's test double

**Status:** Accepted

## Context
CI and a public demo can't depend on an API key, network calls or nondeterministic model output. But unit tests with fakes don't exercise the real browser, server and guardrails together.

## Decision
Implement `ScriptedLLM`, which speaks the same message and tool protocol as the real adapters and reads the same page-state text. It knows a few task shapes (search, compare, read, log in, forms, buy) and runs the full stack end to end.

## Consequences
- The evals are deterministic and free. They measure the *system*, not model quality.
- The policy is not a general agent, and the UI says so in demo mode.
- Model quality is measured by running the same dataset with a real provider.
