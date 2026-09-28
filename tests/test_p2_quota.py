"""Quota-awareness gate.

The bug these tests lock down cost 15 minutes of wall clock to extract nothing.
The free tier allows ~20 requests *per day per model*; the client paced at 15 rpm
as if the limit were per minute, then retried five times per paper against a
bucket that resets at midnight. Three behaviours are asserted:

1. A daily 429 is recognised and raises immediately, not after five waits.
2. A local per-run budget stops the batch at a predictable point.
3. Cached results are never charged, so resuming is free.
"""

from __future__ import annotations

import pytest

from rla.llm.base import LLMError
from rla.llm.retry import (
    BudgetExhausted,
    Spender,
    call_with_retry,
    is_daily_quota,
    quota_summary,
    reset_limiter,
    reset_spender,
)

#: A real Gemini 429 body, trimmed. The quotaId is the load-bearing part.
DAILY_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota, please check your plan and billing details. \\n* Quota exceeded "
    "for metric: generativelanguage.googleapis.com/generate_content_free_tier_"
    "requests, limit: 20, model: gemini-2.5-flash-lite\\nPlease retry in 38.4s.', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaDimensions': "
    "{'location': 'global', 'model': 'gemini-2.5-flash-lite'}, 'quotaValue': '20'}]}]}}"
)

PER_MINUTE_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Resource has been "
    "exhausted (e.g. check quota).', 'status': 'RESOURCE_EXHAUSTED'}}"
)


@pytest.fixture(autouse=True)
def _clean_shared_state():
    reset_limiter()
    reset_spender()
    yield
    reset_limiter()
    reset_spender()


# -- detection -----------------------------------------------------------------


def test_a_daily_quota_429_is_recognised():
    assert is_daily_quota(Exception(DAILY_429))


def test_a_per_minute_429_is_not_treated_as_daily():
    """A transient burst is worth retrying; only the daily bucket is not."""
    assert not is_daily_quota(Exception(PER_MINUTE_429))


def test_a_non_quota_error_is_not_a_quota_error():
    assert not is_daily_quota(Exception("500 internal error"))


def test_the_quota_line_is_extracted_for_the_message():
    summary = quota_summary(Exception(DAILY_429))
    assert "generate_content_free_tier_requests" in summary
    assert "20" in summary


def test_quota_summary_is_empty_when_there_is_nothing_to_summarise():
    assert quota_summary(Exception("boom")) == ""


# -- fail-fast behaviour -------------------------------------------------------


async def test_a_daily_quota_raises_on_the_first_attempt():
    """One attempt, not five. The old path waited ~190s per paper for nothing."""
    calls = 0

    def _boom():
        nonlocal calls
        calls += 1
        raise RuntimeError(DAILY_429)

    with pytest.raises(LLMError) as caught:
        await call_with_retry(_boom, stage="extraction", max_retries=5)

    assert calls == 1, "a daily ceiling must not be retried"
    assert "daily free-tier quota" in str(caught.value)


async def test_the_daily_message_names_the_model_and_the_reset():
    def _boom():
        raise RuntimeError(DAILY_429)

    with pytest.raises(LLMError) as caught:
        await call_with_retry(_boom, stage="extraction", max_retries=3)

    message = str(caught.value)
    assert "gemini-2.5-flash-lite" in message
    assert "per day per model" in message
    assert "does not reset by waiting" in message


async def test_a_per_minute_429_still_retries():
    calls = 0

    def _boom():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError(PER_MINUTE_429)
        return "ok"

    result = await call_with_retry(_boom, stage="extraction", max_retries=5)
    assert result == "ok"
    assert calls == 3


async def test_a_non_retryable_error_raises_immediately():
    calls = 0

    def _boom():
        nonlocal calls
        calls += 1
        raise RuntimeError("401 UNAUTHENTICATED")

    with pytest.raises(LLMError):
        await call_with_retry(_boom, stage="extraction", max_retries=5)
    assert calls == 1


# -- the local budget ----------------------------------------------------------


async def test_the_spender_allows_exactly_its_budget():
    spender = Spender(3)
    for _ in range(3):
        await spender.acquire("extraction")
    assert spender.remaining == 0


async def test_the_spender_refuses_the_call_after_its_budget():
    spender = Spender(2)
    await spender.acquire("extraction")
    await spender.acquire("extraction")
    with pytest.raises(BudgetExhausted) as caught:
        await spender.acquire("extraction")
    assert "budget of 2 is spent" in str(caught.value)


async def test_a_zero_budget_means_unlimited():
    spender = Spender(0)
    assert not spender.enabled
    for _ in range(50):
        await spender.acquire("extraction")
    assert spender.spent == 50


async def test_the_spender_message_explains_why_waiting_will_not_help():
    spender = Spender(1)
    await spender.acquire("extraction")
    with pytest.raises(BudgetExhausted) as caught:
        await spender.acquire("extraction")
    assert "per day per model" in str(caught.value)
    assert "429" in str(caught.value)


async def test_a_spent_budget_prevents_the_call_entirely():
    calls = 0

    def _ok():
        nonlocal calls
        calls += 1
        return "value"

    spender = Spender(1)
    assert await call_with_retry(_ok, stage="s", spender=spender) == "value"
    with pytest.raises(BudgetExhausted):
        await call_with_retry(_ok, stage="s", spender=spender)
    assert calls == 1, "the refused call must never reach the provider"


async def test_retries_are_charged_because_each_one_is_a_real_request():
    """A retried attempt costs quota, so it must be charged as a request."""
    spender = Spender(10)
    calls = 0

    def _flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError(PER_MINUTE_429)
        return "value"

    await call_with_retry(_flaky, stage="s", max_retries=5, spender=spender)
    assert spender.spent == 3


async def test_without_a_spender_nothing_is_counted():
    spender = Spender(5)
    await call_with_retry(lambda: "value", stage="s")
    assert spender.spent == 0


def test_get_spender_is_shared_and_resettable():
    from rla.llm.retry import get_spender

    first = get_spender(5)
    assert get_spender(5) is first
    reset_spender()
    assert get_spender(5) is not first


def test_get_spender_rebuilds_when_the_budget_changes():
    from rla.llm.retry import get_spender

    first = get_spender(5)
    second = get_spender(9)
    assert second is not first
    assert second.budget == 9
