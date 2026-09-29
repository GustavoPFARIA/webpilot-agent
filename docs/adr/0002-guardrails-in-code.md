# ADR 0002: Enforce safety in code, outside the model

**Status:** Accepted

## Context
Prompt injection is unsolved. Any instruction in the system prompt can be overridden by content on a web page.

## Decision
Treat prompts as *guidance* and code as the *guarantee*. After the model picks an action and before the browser runs it, deterministic checks apply: the domain allow-list, secret placeholders and redaction, the literal-password block, and human approval for sensitive actions. Injection detection only adds a warning.

## Consequences
- The guarantees hold even when the model is fully compromised. A test with a model that obeys the attacker proves it.
- The rules are keyword- and host-based, so they can be too strict (legitimate sites off the list) or miss unusual labels. That's an explicit trade-off in favor of safety.
