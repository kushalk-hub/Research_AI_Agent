# ADR-003: One owner per reliability concern; no nested retries

## Status
Accepted

## Context

`src/rla/llm/retry.py` already owns: retry with exponential backoff and jitter, a
process-global rate limiter, a per-run `Spender` budget, and daily-quota fail-fast.
LiteLLM has its own retry and routing.

A naive integration that enables both would produce a nested retry loop — up to
`5 × 5 = 25` attempts for a single logical call, each attempt pacing through the limiter
and each metered attempt charged against a budget that assumes a smaller multiplier. On
a 20-calls/day free tier that is the difference between a clear early failure and an
inexplicable stall.

## Decision

**One clear owner per concern, and exactly one active retry layer at a time.**

| Concern | Owner |
|---|---|
| Retry / backoff / jitter | LiteLLM when the LiteLLM backend is active (`num_retries`); `rla.llm.retry` otherwise |
| Provider-call timeout | RLA |
| Cross-provider fallback | RLA router |
| Per-minute rate limiting | RLA |
| Per-run budget | RLA (never removed) |
| Daily-quota fail-fast | RLA, on a normalised error category |
| Caching | RLA |
| Usage/cost normalisation | RLA |

Concretely, `LiteLLMBackend` calls LiteLLM with `num_retries=0` and lets RLA retry, so a
single logical call never retries twice.

## Consequences

### Positive
- Attempt count is bounded and predictable (`llm_max_retries`).
- Budget accounting stays meaningful, because the spender is charged once per attempt
  that actually leaves the process (`retry.py:221-228`).
- The per-run budget remains an application cost-control semantic rather than being
  absorbed into a library's router.

### Negative
- RLA cannot delegate retry to LiteLLM's more provider-aware backoff, so RLA's backoff is
  provider-agnostic. For Gemini's "retry in 12s" hints this is handled explicitly by
  `retry_delay()` (`retry.py:203-212`), but a provider with a novel backoff signal would
  need an addition here.

### Neutral
- Slightly more configuration on the LiteLLM side (`num_retries=0` must be set, or
  omitted) — a trap worth a comment at the call site.

## Alternatives Considered

- **Let LiteLLM own all retry + fallback.** Rejected: its fallback is per-request and would
  bypass RLA's capability gate and budget accounting, which are application semantics.
- **Remove `rla/llm/retry.py` entirely.** Rejected: the P0 gate requires that every
  outbound request be cacheable and paced; the budget is a first-class product feature
  (`config.py:59-63`).

## References
- `docs/llm_provider_migration_plan.md` §5
- `src/rla/llm/retry.py:215-253`
