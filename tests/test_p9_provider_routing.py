"""Provider routing, error normalisation, and usage accounting.

Gates the provider migration described in docs/llm_provider_migration_plan.md.
Module name follows the milestone it gates, per the repo's test-naming convention.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field

from rla.config import Settings
from rla.llm.base import LLMError
from rla.llm.embedding_base import (
    EmbeddingDimensionMismatch,
    assert_uniform_dimension,
    cosine,
)
from rla.llm.error_map import normalize
from rla.llm.errors import (
    ErrorCategory,
    ProviderAuthFailed,
    ProviderError,
    ProviderInvalidRequest,
    ProviderNetworkError,
    ProviderQuotaExhausted,
    ProviderRateLimited,
    ProviderServerError,
    ProviderTimeout,
    ProviderUnsupported,
    StructuredOutputError,
)
from rla.llm.router import ProviderRouter
from rla.llm.usage import TokenUsage
from rla.store.cache import Cache, CostTracker


class Out(BaseModel):
    value: str = Field(default="ok")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBackend:
    """Backend that records the models it was asked to serve."""

    name = "fake"

    def __init__(self, structured: dict[str, bool] | None = None, fail: dict | None = None):
        self.structured = structured or {}
        self.fail = fail or {}  # model -> exception
        self.calls: list[tuple[str, str]] = []  # (stage, model)
        self.streams: list[tuple[str, str]] = []

    def supports(self, model: str, capability: str) -> bool:
        if capability == "supports_structured_output":
            return self.structured.get(model, True)
        return False

    async def generate_text(self, prompt, *, model, temperature, stage):
        self.calls.append((stage, model))
        if model in self.fail:
            raise self.fail[model]
        return f"text from {model}", object()

    async def generate_structured(self, prompt, schema, *, model, temperature, stage, retries):
        self.calls.append((stage, model))
        if model in self.fail:
            raise self.fail[model]
        return schema(), object()

    async def stream_text(self, prompt, *, model, temperature, stage):
        self.streams.append((stage, model))
        for word in ("one ", "two ", "three"):
            yield word


def make_router(backend, tmp_path, **overrides) -> ProviderRouter:
    # Every routing default is pinned explicitly. Settings reads the developer's
    # real .env, so an unset field here would inherit whatever provider, model or
    # fallback chain the local machine happens to have configured -- and the test
    # would then assert against that instead of the behaviour it means to check.
    # `None` means "use the default below", so a test can still override one field.
    routed: dict = {
        "llm_provider": "gemini",
        "fast_model": "gemini-2.5-flash-lite",
        "strong_model": "gemini-2.5-flash",
        "embedding_model": "gemini-embedding-001",
        "structured_model": "",
        "answer_model": "",
        "fallback_models": "gemini-2.5-flash",
        "fallback_on_quota": False,
        "llm_base_urls": "",
        "openai_api_key": "",
    }
    routed.update({k: v for k, v in overrides.items() if v is not None})
    settings = Settings(
        gemini_api_key="test-key",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        s2_delay_seconds=0.0,
        max_retries=1,
        **routed,
    )
    return ProviderRouter(backend, settings, Cache(tmp_path / "c.db"), CostTracker())


# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------


def test_each_error_category_declares_its_own_policy():
    """Retry and fallback must be derived from the category, not re-decided."""
    assert ProviderTimeout("x").category is ErrorCategory.TIMEOUT
    assert ProviderTimeout("x").retryable is True
    assert ProviderTimeout("x").fallback_eligible is True

    assert ProviderRateLimited("x").retryable is True
    assert ProviderServerError("x").retryable is True
    assert ProviderNetworkError("x").retryable is True

    # Terminal categories must not be retried or fallen back from.
    for err in (
        ProviderAuthFailed("x"),
        ProviderInvalidRequest("x"),
        ProviderUnsupported("x"),
        StructuredOutputError("x"),
    ):
        assert err.retryable is False, type(err).__name__
        assert err.fallback_eligible is False, type(err).__name__


def test_quota_exhaustion_is_neither_retried_nor_auto_fallen_back():
    """ADR-004: quota is a capacity condition, not a fault.

    Silently moving to a second model's budget on the first model's ceiling
    re-creates the exact problem `llm_daily_budget` exists to prevent, one
    level up and invisibly.
    """
    quota = ProviderQuotaExhausted("daily free-tier quota exhausted")
    assert quota.retryable is False
    assert quota.fallback_eligible is False


def test_every_provider_error_is_an_llm_error_so_stages_keep_working():
    """Stages catch `LLMError`; a new category must not escape that contract."""
    for err in (
        ProviderTimeout("x"),
        ProviderQuotaExhausted("x"),
        ProviderAuthFailed("x"),
        ProviderInvalidRequest("x"),
        ProviderUnsupported("x"),
        StructuredOutputError("x"),
    ):
        assert isinstance(err, LLMError)
        assert isinstance(err, RuntimeError)


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------


def test_normalize_maps_status_codes_to_categories():
    class SdkError(Exception):
        def __init__(self, status):
            self.status_code = status
            super().__init__("boom")

    assert normalize(SdkError(429)).category is ErrorCategory.RATE_LIMITED
    assert normalize(SdkError(500)).category is ErrorCategory.SERVER_ERROR
    assert normalize(SdkError(503)).category is ErrorCategory.SERVER_ERROR
    assert normalize(SdkError(401)).category is ErrorCategory.AUTH_FAILED
    assert normalize(SdkError(400)).category is ErrorCategory.INVALID_REQUEST
    assert normalize(SdkError(404)).category is ErrorCategory.INVALID_REQUEST


def test_normalize_recognises_a_daily_quota_429_despite_the_shared_status():
    """A 429 is ambiguous by status alone; the period is in the body.

    Without this distinction a spent daily allowance would be retried like a
    burst limit, burning five waits per paper to reach the same failure.
    """
    burst = normalize(Exception("429 RESOURCE_EXHAUSTED quota exceeded"))
    daily = normalize(
        Exception(
            "429 RESOURCE_EXHAUSTED: metric "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests_perday"
        )
    )
    assert burst.category is ErrorCategory.RATE_LIMITED
    assert daily.category is ErrorCategory.QUOTA_EXHAUSTED


def test_normalize_maps_type_names_when_there_is_no_status():
    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    assert normalize(RateLimitError("x")).category is ErrorCategory.RATE_LIMITED
    assert normalize(AuthenticationError("x")).category is ErrorCategory.AUTH_FAILED
    assert normalize(APITimeoutError("x")).category is ErrorCategory.TIMEOUT


def test_normalize_is_idempotent():
    """Nested backends may normalise defensively without double-wrapping."""
    original = ProviderTimeout("slow")
    again = normalize(original, model="m")
    assert again is original
    assert again.model == "m"


def test_normalize_does_not_treat_a_bare_timeout_error_as_unknown():
    assert normalize(TimeoutError("timed out")).category is ErrorCategory.TIMEOUT


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def test_a_stage_gets_its_configured_role_model(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)

    await router.generate_text("x", stage="extraction")
    await router.generate_text("x", stage="answer")
    await router.generate_text("x", stage="some_other_stage")

    models = dict(backend.calls)
    assert models["extraction"] == settings_structured(router)
    assert models["answer"] == router.settings.strong_model
    assert models["some_other_stage"] == router.settings.fast_model


def settings_structured(router: ProviderRouter) -> str:
    return router.settings.model_for_structured


async def test_structured_model_setting_is_honoured(tmp_path):
    """Per-stage model choice is the fix for the audit's dropped `strong_model`."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path, structured_model="gemini-2.5-flash")

    await router.generate_structured("x", Out, stage="extraction")
    assert backend.calls[-1] == ("extraction", "gemini-2.5-flash")


async def test_an_explicit_model_argument_still_wins(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    await router.generate_text("x", stage="extraction", model="explicit-model")
    assert backend.calls[-1] == ("extraction", "explicit-model")


async def test_streaming_reaches_the_caller(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    chunks = [c async for c in router.stream_text("x", stage="answer")]
    assert chunks == ["one ", "two ", "three"]
    assert backend.streams[-1][1] == router.settings.strong_model


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


async def test_a_transient_server_error_falls_back_to_the_next_model(tmp_path):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from gemini-2.5-flash"
    assert [m for _, m in backend.calls] == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
    assert router.fallbacks[0][0] == "extraction"
    assert router.fallbacks[0][3] == ErrorCategory.SERVER_ERROR


@pytest.mark.parametrize(
    "category_error",
    [
        ProviderTimeout("t"),
        ProviderRateLimited("r"),
        ProviderServerError("s"),
        ProviderNetworkError("n"),
    ],
)
async def test_every_recoverable_fault_is_eligible_for_fallback(
    tmp_path, category_error
):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": category_error})
    router = make_router(backend, tmp_path)
    await router.generate_text("x", stage="extraction")
    assert router.fallbacks, "expected a fallback for a recoverable fault"


@pytest.mark.parametrize(
    "category_error",
    [
        ProviderAuthFailed("bad key"),
        ProviderInvalidRequest("400"),
        ProviderUnsupported("no schema"),
        StructuredOutputError("bad json"),
    ],
)
async def test_a_terminal_fault_never_fans_out_across_models(tmp_path, category_error):
    """An invalid key must not be retried against every configured model.

    Doing so multiplies the cost of a one-line configuration fix by the length
    of the fallback chain.
    """
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": category_error})
    router = make_router(backend, tmp_path)

    with pytest.raises(ProviderError):
        await router.generate_text("x", stage="extraction")

    assert [m for _, m in backend.calls] == ["gemini-2.5-flash-lite"]
    assert not router.fallbacks


async def test_quota_exhaustion_does_not_auto_fail_over_by_default(tmp_path):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderQuotaExhausted("daily")})
    router = make_router(backend, tmp_path)

    with pytest.raises(ProviderQuotaExhausted):
        await router.generate_text("x", stage="extraction")

    assert [m for _, m in backend.calls] == ["gemini-2.5-flash-lite"]
    assert not router.fallbacks


async def test_quota_failover_happens_when_explicitly_enabled(tmp_path):
    # Only the primary is exhausted, so the fallback succeeds -- the scenario the
    # flag exists for, observed live on 2026-09-28 when flash-lite's daily quota
    # was spent while flash still had headroom.
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderQuotaExhausted("daily")})
    router = make_router(backend, tmp_path, fallback_on_quota=True)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from gemini-2.5-flash"
    assert router.fallbacks


async def test_the_primary_falls_back_to_the_next_model_on_a_transient_fault(tmp_path):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from gemini-2.5-flash"


async def test_a_chain_exhausted_raises_the_final_error(tmp_path):
    both = {
        "gemini-2.5-flash-lite": ProviderServerError("primary down"),
        "gemini-2.5-flash": ProviderServerError("fallback down"),
    }
    backend = FakeBackend(fail=both)
    router = make_router(backend, tmp_path)

    with pytest.raises(ProviderServerError):
        await router.generate_text("x", stage="extraction")

    assert len(backend.calls) == 2


# ---------------------------------------------------------------------------
# Capability gate
# ---------------------------------------------------------------------------


async def test_an_incapable_model_is_refused_for_a_structured_stage(tmp_path):
    """ADR-004: refuse rather than degrade to unvalidated JSON.

    Silently accepting a provider that cannot honour the schema is exactly the
    lowest-common-denominator failure the design is meant to prevent.
    """
    backend = FakeBackend(structured={"gemini-2.5-flash-lite": False})
    router = make_router(backend, tmp_path, fallback_models="")

    with pytest.raises(ProviderUnsupported):
        await router.generate_structured("x", Out, stage="extraction")

    assert not backend.calls


async def test_an_incapable_fallback_is_skipped_not_used(tmp_path):
    backend = FakeBackend(
        structured={"gemini-2.5-flash": False},
        fail={"gemini-2.5-flash-lite": ProviderServerError("503")},
    )
    router = make_router(backend, tmp_path)

    with pytest.raises(ProviderServerError):
        await router.generate_structured("x", Out, stage="extraction")

    # The incapable fallback was never asked.
    assert [m for _, m in backend.calls] == ["gemini-2.5-flash-lite"]


async def test_a_capable_fallback_is_used_for_a_structured_stage(tmp_path):
    backend = FakeBackend(
        structured={"gemini-2.5-flash-lite": True, "gemini-2.5-flash": True},
        fail={"gemini-2.5-flash-lite": ProviderServerError("503")},
    )
    router = make_router(backend, tmp_path)

    result = await router.generate_structured("x", Out, stage="extraction")

    assert isinstance(result, Out)
    assert [m for _, m in backend.calls] == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


def test_a_model_named_as_its_own_fallback_is_dropped():
    """Re-issuing an identical failing request is not a retry."""
    settings = Settings(
        gemini_api_key="k",
        fast_model="gemini-2.5-flash-lite",
        fallback_models="gemini-2.5-flash-lite, gemini-2.5-flash",
    )
    assert settings.fallback_chain == ["gemini-2.5-flash"]


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------


def test_unknown_usage_is_not_zero():
    assert TokenUsage().known is False
    assert TokenUsage(input_tokens=0, output_tokens=0).known is True


def test_usage_merges_openai_and_gemini_shapes():
    from rla.llm.usage import usage_from_mapping

    openai = usage_from_mapping({"prompt_tokens": 10, "completion_tokens": 4})
    gemini = usage_from_mapping({"prompt_token_count": 10, "candidates_token_count": 4})
    assert openai == gemini
    assert openai.total_tokens == 14


def test_usage_never_fabricates_a_total_from_a_missing_side():
    from rla.llm.usage import usage_from_mapping

    usage = usage_from_mapping({"prompt_tokens": 10})
    assert usage.input_tokens == 10
    assert usage.output_tokens is None
    assert usage.total_tokens is None


def test_summing_a_known_and_an_unknown_yields_unknown():
    """The aggregate of a knowable and an unknowable call is not knowable."""
    combined = TokenUsage(input_tokens=10, output_tokens=5) + TokenUsage()
    assert not combined.known


def test_usage_from_a_gemini_response_shape():
    from rla.llm.base import usage_from_response

    class Chunk:
        usage_metadata = type(
            "U", (), {"prompt_token_count": 7, "candidates_token_count": 3}
        )()

    usage = usage_from_response(Chunk())
    assert usage.input_tokens == 7
    assert usage.output_tokens == 3


def test_usage_from_a_litellm_style_response_shape():
    from rla.llm.base import usage_from_response

    class Response:
        usage = type("U", (), {"prompt_tokens": 7, "completion_tokens": 3})()

    usage = usage_from_response(Response())
    assert usage.input_tokens == 7
    assert usage.output_tokens == 3


def test_a_response_with_no_usage_is_unknown_not_zero():
    from rla.llm.base import usage_from_response

    class Bare:
        pass

    assert not usage_from_response(Bare()).known


def test_a_cache_hit_records_unknown_usage_rather_than_zero(tmp_path):
    """A cached call has no provider response, so its usage is genuinely unknown.

    Recording zero would make a fully cached run report $0.00 while having spent
    nothing this run -- which happens to be right by accident, and would be wrong
    for a partial cache hit.
    """
    cache = Cache(tmp_path / "c.db")
    cache.set("k", "cached", kind="llm")
    tracker = CostTracker()
    from rla.llm.base import record_usage

    record_usage(tracker, "extraction", None)
    report = tracker.to_dict("gemini-2.5-flash")
    assert report["cost_status"] == "unknown_usage"
    assert report["estimated_usd"] is None
    cache.close()


# ---------------------------------------------------------------------------
# Embedding dimensions
# ---------------------------------------------------------------------------


def test_cosine_of_identical_vectors_is_one():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    """Zero is a real answer for orthogonal vectors, and must stay reachable."""
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_raises_on_a_dimension_mismatch():
    """The audit's silent failure: a model swap made every score 0.0.

    Returning 0.0 here looks exactly like "these concepts are unrelated", so
    entity resolution quietly stopped merging and nothing reported an error.
    """
    with pytest.raises(EmbeddingDimensionMismatch) as excinfo:
        cosine([1.0, 2.0, 3.0], [1.0, 2.0])
    assert "3" in str(excinfo.value) and "2" in str(excinfo.value)


def test_a_non_uniform_batch_is_reported_before_any_pairwise_comparison():
    with pytest.raises(EmbeddingDimensionMismatch):
        assert_uniform_dimension([[1.0, 2.0], [1.0, 2.0, 3.0]])


def test_a_uniform_batch_reports_its_dimension():
    assert assert_uniform_dimension([[1.0, 2.0], [3.0, 4.0]]) == 2


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


async def test_a_provider_call_is_bounded_by_the_timeout():
    """The audit found provider calls had no bound at all.

    `request_timeout_seconds` only ever applied to the academic source HTTP
    calls, so a hung provider connection could block a stage indefinitely.
    """
    from rla.llm.retry import call_with_retry, reset_limiter, reset_spender

    reset_limiter()
    reset_spender()

    def _hang() -> None:
        import time

        time.sleep(5)

    with pytest.raises((TimeoutError, LLMError)):
        await call_with_retry(
            _hang, stage="t", max_retries=1, timeout=0.05, limiter=_NoWait()
        )
    reset_limiter()


class _NoWait:
    min_interval = 0.0

    async def acquire(self) -> None:
        return None


# ---------------------------------------------------------------------------
# The documented quota escape hatch
# ---------------------------------------------------------------------------

#: A real per-day Gemini 429, as captured from the live API on 2026-10-01. The
#: `quotaId` and `quotaValue` are the load-bearing parts: 20 requests per day, per
#: project, per model.
LIVE_DAILY_429 = (
    "429 RESOURCE_EXHAUSTED: Quota exceeded for metric: generativelanguage."
    "googleapis.com/generate_content_free_tier_requests, limit: 20, model: "
    "gemini-2.5-flash-lite\nPlease retry in 53.6s., details: [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': "
    "'20'}]}]"
)


async def test_the_documented_quota_escape_hatch_actually_fires(tmp_path):
    """`RLA_FALLBACK_ON_QUOTA=1` is documented as the way out of a spent daily cap.

    It could not fire. The retry layer re-raised its own text-only message, the
    router saw UNKNOWN instead of QUOTA_EXHAUSTED, and UNKNOWN is not
    fallback-eligible -- so the opt-in was dead code. Driven through the *real*
    retry layer because the defect lived in the gap between the two, not in a rule
    either of them got wrong.
    """
    from rla.llm.retry import call_with_retry

    class RetryingBackend(FakeBackend):
        async def generate_text(self, prompt, *, model, temperature, stage):
            self.calls.append((stage, model))

            def _invoke() -> str:
                if model in self.fail:
                    raise self.fail[model]
                return f"text from {model}"

            return await call_with_retry(
                _invoke, stage=stage, max_retries=5, limiter=_NoWait()
            ), None

    backend = RetryingBackend(fail={"gemini-2.5-flash-lite": RuntimeError(LIVE_DAILY_429)})
    router = make_router(backend, tmp_path, fallback_on_quota=True)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from gemini-2.5-flash"
    assert router.fallbacks, "the opt-in must produce a real failover"


async def test_a_self_hosted_model_can_be_declared_structured_capable(tmp_path):
    """A local server cannot be reached at all without this.

    LiteLLM's `supports_response_schema()` returns False for any model it has no
    static entry for -- including a local llama.cpp/Ollama server that honours
    `response_format` perfectly well. The gate then refuses, and since scoring,
    extraction and resolution are all structured stages, the model becomes
    unusable for exactly the work a local model is wanted for.
    """
    from rla.llm.litellm_backend import LiteLLMBackend

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        llm_provider="litellm",
        structured_output_models="openai/qwen3:4b",
        llm_base_urls='{"openai": "http://localhost:11434/v1"}',
    )
    backend = LiteLLMBackend(settings)

    assert backend.supports("openai/qwen3:4b", "supports_structured_output") is True


async def test_the_opt_in_covers_both_spellings_and_nothing_else(tmp_path):
    """A bare id is how this project writes its defaults, so one entry has to
    cover both spellings -- and it must not widen the gate to unrelated models.

    Asserted on the settings predicate rather than on LiteLLM's own answer:
    `supports_response_schema()` is load-order dependent for models LiteLLM has
    no entry for, returning different values depending on what earlier code in the
    process already touched. That instability is the reason the operator
    declaration exists at all, so a test that depended on it would be flaky.
    """
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        structured_output_models="qwen3:4b",
    )

    assert settings.declares_structured_output("qwen3:4b") is True
    assert settings.declares_structured_output("openai/qwen3:4b") is True
    assert settings.declares_structured_output("openai/other") is False
    assert settings.declares_structured_output("gemini-2.5-flash") is False


async def test_an_empty_opt_in_declares_nothing(tmp_path):
    """The default must be silence, so ADR-004's refusal is untouched."""
    settings = Settings(gemini_api_key="k", data_dir=tmp_path, structured_output_models="")

    assert settings.declared_structured_models() == []
    assert settings.declares_structured_output("openai/qwen3:4b") is False


# ---------------------------------------------------------------------------
# P12: the session-override rung, and fallback observation
# ---------------------------------------------------------------------------


def test_a_session_override_beats_an_explicit_model_argument(tmp_path):
    """The TUI user must be able to say "use Ollama for extraction in this run"
    even where a stage supplies a model explicitly to label its cost report."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")

    asyncio.run(router.generate_text("x", stage="extraction", model="gemini-2.5-flash"))

    assert backend.calls[-1] == ("extraction", "openai/gpt-4o-mini")


def test_an_explicit_argument_still_beats_the_stage_role(tmp_path):
    """Retargeted, not deleted: the old contract survives beneath the new rung."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)

    asyncio.run(router.generate_text("x", stage="extraction", model="explicit-model"))

    assert backend.calls[-1] == ("extraction", "explicit-model")


def test_an_empty_override_does_not_win(tmp_path):
    """`is not None`, never truthiness: an empty string must not beat a real model."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "")

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert backend.calls[-1] == ("extraction", settings_structured(router))


def test_clearing_an_override_restores_the_configured_role(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")
    router.set_override("structured", None)

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert backend.calls[-1] == ("extraction", settings_structured(router))


def test_an_override_does_not_leak_to_another_role(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")

    asyncio.run(router.generate_text("x", stage="answer"))

    assert backend.calls[-1] == ("answer", router.settings.model_for_answer)


def test_a_fallback_is_reported_to_the_observer(tmp_path):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)
    seen: list[tuple[str, str, str, str]] = []
    router.on_fallback = seen.append

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert seen and seen[0][0] == "extraction"


def test_the_observer_cannot_change_the_fallback_decision(tmp_path):
    """It observes; it does not own. A raising observer must not become a second
    mechanism, so the call still succeeds on the fallback."""
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)

    def _explode(_entry: tuple[str, str, str, str]) -> None:
        raise RuntimeError("observer tried to interfere")

    router.on_fallback = _explode

    text = asyncio.run(router.generate_text("x", stage="extraction"))
    assert text == "text from gemini-2.5-flash"
