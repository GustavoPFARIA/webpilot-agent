# ADR 0008: Any public website by default, with an opt-in allow-list

**Status:** Accepted (changes the default from ADR 0006; the enforcement mechanism stays)

## Context
Until v1.4.0 the agent could only open hosts in `ALLOWED_DOMAINS`. That is the strongest protection against exfiltration, but anyone trying the project had to edit configuration before a single real website worked. That made a general-purpose browser agent look like it only worked on its own test store.

## Decision
The default is `ALLOWED_DOMAINS=["*","127.0.0.1","localhost"]`: any public website. The protections that don't depend on a list stay enforced on every request in both modes: private, loopback and link-local IPs, cloud metadata, internal names, reserved special-use domains (`.example`, `.test`, `.invalid`), disguised numeric IPs, non-http schemes, this app's own API, secret placeholders and redaction, and human approval. Listing exact hosts switches to allow-list mode.

## Consequences
- The project works on real websites out of the box.
- In the default mode, a manipulated model could send page data to an attacker-controlled *public* site. The README and `docs/security.md` say so, and recommend allow-list mode for anything sensitive.
- The security evals always run in allow-list mode, so the stronger guarantee stays verified in CI regardless of the local `.env`.
