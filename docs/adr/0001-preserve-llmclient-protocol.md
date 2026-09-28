# ADR-001: Preserve the `LLMClient` Protocol as the application seam

## Status
Accepted

## Context

The audit found the LLM integration single-provider (Google Gemini via `google-genai`),
but also found that the application-level seam is already correct: `LLMClient`
(`src/rla/llm/base.py:22-63`) is a three-method `Protocol` with no Gemini types in its
signatures, and all five production call sites (`query_expansion.py:51`,
`scoring.py:76`, `extraction.py:197`, `resolve.py:214`, `answer.py:112`) type against it
rather than against `GeminiClient`.

The brief offers two readings:

1. Rewrite stages around LiteLLM-native calls (`litellm.completion(...)`).
2. Keep the Protocol and put a routing layer underneath it.

## Decision

**Keep `LLMClient` and put the provider-routing layer beneath it.**

Stages continue to receive an `LLMClient` and never learn which provider serves them.

## Consequences

### Positive
- A provider swap is a configuration change, and rollback to the direct path is one env
  var (`RLA_LLM_PROVIDER=gemini`) with no code change.
- The five call sites are untouched by this migration, which is what makes the change
  reviewable and makes `git revert` safe.
- Existing tests that construct fake `LLMClient` objects keep working unchanged.

### Negative
- The Protocol is not a *complete* provider contract. It does not cover embeddings,
  token usage, or error categories, so those had to be modelled separately
  (`EmbedderClient`, `TokenUsage`, `ProviderError`) rather than folded in. A reader
  looking for "the one interface" will find three.
- `cli.py` originally named `GeminiClient` at three construction sites rather than going
  through a factory, so a factory had to be introduced.

### Neutral
- The Protocol grew two members (capability declaration, normalised usage). This is
  additive; existing implementations remain structurally valid.

## Alternatives Considered

- **Rewrite stages onto LiteLLM-native calls.** Rejected: every stage would acquire
  provider vocabulary, and a provider swap would stop being a config change. It would
  also break 425 passing tests for no architectural gain.
- **Rely solely on the SDK being provider-abstracted.** Rejected: the SDK is
  provider-specific; nothing below the seam would be portable.

## References
- `docs/llm_architecture_audit.md` §9, §11
- `src/rla/llm/base.py:22-63`
