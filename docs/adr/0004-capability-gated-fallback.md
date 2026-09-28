# ADR-004: Capability-gated fallback, with quota failover opt-in

## Status
Accepted

## Context

A routing layer makes cross-model fallback possible. The decisive question is which
failures should trigger it.

The motivating observation is real and was reproduced on 2026-09-28: `gemini-2.5-flash-lite`
hit its **per-model** daily quota (20/day) while `gemini-2.5-flash` still had budget,
because the quota is per model rather than global. A fallback would have kept a run
alive.

The counter-argument is equally real. `config.py:59-63` documents why the local budget
exists: *"Stops a large batch from spending the whole day's allowance on the first pass
and leaving nothing for resolution, graph building, or answering."* Silently redirecting
to a second model's budget on quota exhaustion re-creates exactly that failure one level
up, and does so invisibly.

## Decision

**Fallback triggers on recoverable transport faults only. Quota exhaustion raises by
default; failing over on quota requires an explicit opt-in.**

| Category | Retry | Auto-fallback |
|---|---|---|
| `TIMEOUT`, `RATE_LIMITED`, `SERVER_ERROR`, `NETWORK_ERROR` | Yes | Yes |
| `QUOTA_EXHAUSTED` | No | **Opt-in** (`RLA_FALLBACK_ON_QUOTA`, default off) |
| `AUTH_FAILED`, `INVALID_REQUEST`, `UNSUPPORTED`, `BUDGET_EXHAUSTED`, `STRUCTURED_OUTPUT` | No | No |

Separately, **a model may only serve as a fallback for a structured stage if it is
capability-qualified for structured output.** An unqualified model is refused rather than
used with degraded validation.

## Consequences

### Positive
- A 401 does not silently retry against four more models, burning quota and masking a
  configuration error that needs operator action.
- A structured-output-incapable provider cannot quietly become the extraction engine.
- Quota reserve is preserved unless the operator explicitly trades it away.
- The capability gate prevents "lowest common denominator" degradation, which the brief
  explicitly forbids.

### Negative
- The most common real-world failure on a free tier (quota exhaustion) does **not** get
  automatic relief, which will feel like the feature "isn't working" until
  `RLA_FALLBACK_ON_QUOTA=1` is understood. Mitigated by an error message that names the
  exact exhausted quota and the model that still has headroom.
- Two similar-looking failures (transient 5xx vs exhausted daily quota) get deliberately
  different treatment, which requires accurate normalisation to be worth anything.

### Neutral
- Opting in is per-deployment, not per-call.

## Alternatives Considered

- **Fall back on any error, including auth.** Rejected: an invalid key would fan out
  across every configured model, multiplying the cost of a one-line config fix.
- **Never fall back.** Rejected: wastes the real benefit that motivated the migration.

## References
- `docs/llm_provider_migration_plan.md` §6
- `src/rla/config.py:59-63`, `src/rla/llm/retry.py:40-51`
