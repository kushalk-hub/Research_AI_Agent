# ADR-0006: MultiBackend facade rather than a multi-backend router

## Status

Accepted (2026-10-02)

## Context

`ProviderRouter` held exactly one backend, so a native Ollama backend had nowhere
to go. The alternatives were to rewrite `ProviderRouter` to hold a registry, or to
let the orchestrator pick a client per stage.

## Decision

Add `MultiBackend` (`src/rla/llm/multi.py:31`), which implements the existing
`RoutingBackend` protocol (`src/rla/llm/router.py:45`) and resolves each model id
to its owning backend. `ProviderRouter` is unchanged and remains the sole owner of
precedence, capability policy, and fallback eligibility and ordering.

## Rationale

`ProviderRouter._dispatch` (`src/rla/llm/router.py:218`) already iterates fallback
candidates and calls `run(model=candidate)`. Resolving the owner per candidate is
therefore sufficient for cross-provider fallback, with **no change to fallback
logic**. A registry in the router would have invalidated most of the routing test
suite and left the A1/A8 acceptance tests describing a different class than the one
they were written for. Letting the orchestrator choose per stage would move routing
policy out of the router, which is exactly what ADR-001 forbids.

Backends are constructed lazily so a Gemini-only configuration never imports or
constructs an Ollama or LiteLLM backend, keeping the `[router]` extra optional.

## Consequences

### Positive

- One code path regardless of how many providers a configuration uses.
- Provider selection is still configuration- and model-driven; A8 now asserts the
  dispatch behaviour rather than a class.
- `doctor` reports live backends through `MultiBackend.live_backends()`.

### Negative

- One more indirection between the router and the provider SDKs; a dispatch failure
  now has two places to look (resolution vs backend) instead of one.

### Neutral

- The precedence contract gained one rung (a transient session override above the
  explicit `model=` argument). Rungs 2 and 3 are unchanged.

## Alternatives Considered

- **Rewrite `ProviderRouter` to hold a backend registry.** Rejected: it would have
  invalidated most of the routing test suite and left the A1/A8 acceptance tests
  describing a different class than the one they were written for.
- **Let the orchestrator pick a client per stage.** Rejected: routing policy would
  move out of the router, which is exactly what ADR-001 forbids.

## References

- `src/rla/llm/multi.py:31`, `src/rla/llm/router.py:45`, `src/rla/llm/router.py:218`
- `src/rla/llm/factory.py:26` (`build_backend`)
- ADR-001 (`docs/adr/0001-preserve-llmclient-protocol.md`)
