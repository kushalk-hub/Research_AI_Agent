# ADR-002: Introduce LiteLLM as an optional extra, not a hard dependency

## Status
Accepted

## Context

The brief proposes LiteLLM as the routing layer. Before deciding, the wheel
(`litellm-1.103.0-cp310-abi3-win_amd64.whl`, 28.1 MB) was inspected without installing it.
Two facts came out of that inspection:

1. **16 core dependencies**, including `boto3`, `tiktoken`, `tokenizers`, `aiohttp`,
   `jsonschema`, and `openai`. The project's current runtime dependency count is 7.
2. **LiteLLM's exception classes subclass `openai.*`**
   (`litellm/exceptions.py`: `AuthenticationError(openai.AuthenticationError)`,
   `RateLimitError(openai.RateLimitError)`, `Timeout(openai.APITimeoutError)`, …). So
   importing LiteLLM transitively imports the OpenAI SDK — LiteLLM is not
   provider-neutral at the exception layer, it is OpenAI-shaped.

The project is a single-user research CLI whose only real provider is Gemini, on a
free tier with ~20 calls/day/model.

## Decision

**Add LiteLLM under an optional extra (`[router]`) and import it lazily.**

```toml
[project.optional-dependencies]
router = ["litellm>=1.103,<2"]
```

`LiteLLMBackend` is the only module that imports `litellm`, and it does so inside a
function. The default `rla` install stays at 7 runtime dependencies, and `RLA_LLM_PROVIDER`
defaults to the direct `gemini` backend so the LiteLLM path is opt-in.

## Consequences

### Positive
- Default install and the test suite are unaffected by 16 new transitive packages.
- The supply-chain surface grows only for those who want routing.
- If LiteLLM is abandoned, deleting one extra and one module removes it.

### Negative
- Two code paths must be kept behaviourally equivalent, which is the main ongoing cost of
  this decision.
- A LiteLLM API break is possible without the suite catching it, because the suite runs
  with the direct backend. Mitigated by a dedicated mocked-backend test module that runs
  whenever the extra is installed.
- The OpenAI SDK enters the environment regardless, when the extra is installed.

### Neutral
- `pyproject.toml` grows an optional-dependency group; nothing else changes.

## Alternatives Considered

- **Hard runtime dependency.** Rejected: every install would carry `boto3` and `tiktoken`
  whether or not routing is used, on a project that runs on a free tier.
- **Hand-rolled thin router over provider SDKs.** Genuinely attractive: zero new
  dependencies, full control, and the project already wraps one SDK. Rejected *for now*
  because it means owning provider-by-provider schema, usage, and error handling —
  several hundred lines of code and tests to maintain. This remains the strongest
  alternative and should be revisited if LiteLLM proves troublesome.
- **LiteLLM Proxy (HTTP gateway).** Rejected for now: it introduces a running service,
  an extra deployment surface, and a new failure mode, for a single-user CLI.

## References
- `docs/llm_architecture_audit.md` §3, §9
- `docs/llm_provider_migration_plan.md` §4, §12 (R1-R3)
