# ADR 0003: Exactly one browser action per model turn

**Status:** Accepted

## Context
Models can return several tool calls at once. In a browser, the first action usually changes the page, so later calls act on stale element ids.

## Decision
Execute only the first tool call. Every other call gets an error `tool_result` saying it was skipped, which keeps the message history valid for both providers.

## Consequences
- Every decision is made on a fresh page state, which is safer and more predictable.
- Tasks take more steps, and so more latency and tokens, than batching would. Prompt caching and the compact page view offset part of the cost.
