# ADR 0007: Secure-by-default API access

**Status:** Accepted

## Context
The approval endpoint decides whether money is spent. In v1.0.0 anyone who could reach the server could list every run and approve any purchase.

## Decision
Use bearer tokens mapped to user ids (`API_KEYS`), compared in constant time. Runs belong to their creator, and foreign run ids return 404. With no tokens configured, accept only loopback clients. Local development needs no setup, and any deployment is closed until tokens are added. Docker Compose refuses to start without `API_KEYS`. The browser's URL policy also denies the app's own `/api`, so the agent can't use the loopback exception to approve itself.

## Consequences
- Safe to run locally and to deploy by mistake.
- Static tokens, not OAuth or OIDC. For multi-tenant production, put the API behind an identity-aware proxy and map its user header to `owner`.
