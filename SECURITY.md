# Security policy

## Reporting a vulnerability

Please **don't open a public issue**. Report privately through [GitHub Security Advisories](https://github.com/GustavoPFARIA/webpilot-agent/security/advisories/new).

Especially welcome:
- A prompt-injection payload that makes the agent open a non-allowed domain, reveal a secret value to the model, or perform a sensitive action without approval.
- Bypasses of `check_url` (encodings, IDN or lookalike hosts, redirects).

Include the task, the page content and the step trace if possible. You'll get a response within 7 days.

## Scope and design

See [docs/security.md](docs/security.md) for the threat model, the controls and known limitations.
