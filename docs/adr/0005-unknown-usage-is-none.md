# ADR-005: Unknown token usage is `None`, never `0`

## Status
Accepted

## Context

`usage_from_response()` (`src/rla/llm/base.py:66-74`) reads
`usage_metadata.prompt_token_count` — a Gemini-specific attribute name — and returns
`(0, 0)` when it is absent.

For Gemini this works. For any other provider the attribute is simply missing, so the
function returns `(0, 0)` and the cost report renders **$0.00**. Nothing is logged, no
exception is raised, and the run looks free.

This is the most dangerous coupling the audit found, because it is invisible: the other
defects (mismatched pricing, unmetered streaming) produce a visibly wrong number, while
this one produces a plausible number that is simply fabricated.

The audit also found that streaming is never metered at all (`record_usage` is absent
from `stream_text`), so the answer stage — the only consumer of the nominally stronger
model — contributes zero tokens. Reported cost is therefore a lower bound that excludes
the most expensive stage.

## Decision

**Introduce a `TokenUsage` value object where unknown is `None`, and make the cost report
distinguish "computed" from "unknown".**

```python
input_tokens: int | None
output_tokens: int | None
total_tokens: int | None
@property
def known(self) -> bool
```

`CostTracker` reports `estimated_usd` **only** when tokens are known *and* the model is
priced. Otherwise it emits `estimated_usd: None` plus an explicit `cost_status` of
`ok` / `unknown_usage` / `unpriced_model`.

Streaming is metered from the final chunk's usage (LiteLLM with
`stream_options={"include_usage": True}`) or from the aggregated response (direct path).
If a backend supplies neither, the result is `known=False` — reported, not zeroed.

## Consequences

### Positive
- A missing-usage provider produces a visible "unknown" instead of a silent $0.00.
- A cost regression becomes detectable: previously, any provider change that broke usage
  parsing would have *lowered* reported spend.
- The answer stage's cost finally appears.

### Negative
- More code paths must handle `None`, including any consumer of the cost report.
- The run summary can now legitimately read `estimated_usd: null`, which is a visible
  change from a number.
- The pricing table must gain explicit entries for each configured model; an unlisted
  model reports `unpriced_model` rather than defaulting to $0.00.

### Neutral
- `LLMClient` implementations that never reported usage now must, which is why the
  Protocol gained a normalised result rather than leaving each backend to its own habit.

## Alternatives Considered

- **Keep `tuple[int, int]` and return 0 for unknown.** Rejected: this *is* the current
  defect.
- **Estimate unknown usage from prompt length via a tokenizer.** Rejected as a default:
  it manufactures numbers. It remains a reasonable opt-in approximation, but it must be
  labelled as an estimate.

## References
- `docs/llm_architecture_audit.md` §16.2, §16.3, Q11
- `src/rla/llm/base.py:66-74`, `src/rla/store/cache.py:49-111`
