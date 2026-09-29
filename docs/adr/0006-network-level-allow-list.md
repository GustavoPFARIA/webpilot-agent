# ADR 0006: Enforce the allow-list on every network request

**Status:** Accepted (supersedes the navigate-only check in v1.0.0)

## Context
v1.0.0 checked the allow-list only when the model called `navigate`. But a page can send the browser elsewhere without the model typing a URL: a clicked link, a form whose `action` is another domain, an open redirect on an allowed site, a script or an image beacon. Each of these is an exfiltration path.

## Decision
Install the URL policy as a Playwright route on the browser context, so every request is checked. Playwright doesn't route redirects, so navigation requests are fetched with `max_redirects=0` and the `Location` is checked before the browser may follow it. Add a `framenavigated` backstop, and disable service workers, whose requests bypass routing. Report blocked requests in the step outcome.

## Consequences
- The guarantee no longer depends on how a navigation starts. The evals `offsite-link`, `open-redirect` and `form-exfiltration` prove it.
- Every navigation now goes through `route.fetch`, which adds a small overhead.
- WebSockets and DNS rebinding remain out of scope. Production should also enforce egress at a proxy.
