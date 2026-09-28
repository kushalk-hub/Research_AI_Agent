"""Retry and pacing policy for LLM calls (P2 live gate, free-tier limits)."""

from __future__ import annotations

import asyncio

import pytest

from rla.llm.base import LLMError
from rla.llm.retry import (
    call_with_retry,
    get_limiter,
    is_retryable,
    reset_limiter,
    retry_delay,
)
from rla.store.cache import RateLimiter


class Status(Exception):
    """Stand-in for the SDK's error objects, which carry a bare `code`."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"{code} {message}".strip())
        self.code = code
        self.message = message


@pytest.fixture(autouse=True)
def _no_pacing():
    """Most tests here care about policy, not waiting. Pace only where asserted."""
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def instant_backoff(monkeypatch):
    """Skip the real backoff sleeps, which are asserted separately above.

    Pacing still applies, because the limiter is not what this stubs out.
    """
    monkeypatch.setattr("rla.llm.retry.retry_delay", lambda exc, attempt, cap=60.0: 0.0)


# -- what is worth retrying ----------------------------------------------------


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(code):
    assert is_retryable(Status(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_the_callers_own_faults_fail_fast(code):
    """Retrying a bad key or a retired model only burns quota and time."""
    assert not is_retryable(Status(code))


def test_a_severed_stream_is_retried_even_without_a_status():
    assert is_retryable(RuntimeError("Server disconnected without sending a response."))
    assert is_retryable(TimeoutError("timed out"))
    assert is_retryable(ConnectionError("connection reset by peer"))


def test_an_unrelated_error_is_not_retried():
    assert not is_retryable(ValueError("schema validation exploded"))


# -- backoff -------------------------------------------------------------------


def test_the_servers_retry_after_hint_wins_over_our_own_curve():
    """429 bodies say 'retry in Ns'; guessing shorter just re-trips the limit."""
    exc = Status(429, "quota exceeded. Please retry in 39.5s.")
    assert retry_delay(exc, attempt=0) == pytest.approx(39.5)


def test_backoff_grows_when_the_server_gives_no_hint():
    later = retry_delay(Status(503), attempt=4)
    earlier = retry_delay(Status(503), attempt=1)
    assert earlier < later <= 60.0


def test_backoff_is_jittered_so_a_burst_does_not_retry_in_lockstep():
    delays = {retry_delay(Status(503), attempt=2) for _ in range(12)}
    assert len(delays) > 1


# -- the retry loop ------------------------------------------------------------


async def test_a_throttled_call_is_retried_and_then_succeeds(
    instant_backoff,
):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Status(429, "slow down")
        return "extracted"

    result = await call_with_retry(
        flaky, stage="extraction", limiter=RateLimiter(0.0), max_retries=5
    )

    assert result == "extracted"
    assert calls["n"] == 3, "should have recovered, not given up"


async def test_retries_are_bounded_and_then_reported(
    instant_backoff,
):
    def always_throttled():
        raise Status(429, "still throttled")

    with pytest.raises(LLMError, match="after 3 attempts"):
        await call_with_retry(
            always_throttled, stage="extraction", limiter=RateLimiter(0.0), max_retries=3
        )


async def test_a_permanent_error_is_not_retried_at_all(
    instant_backoff,
):
    """One 404 should cost one call, not five."""
    calls = {"n": 0}

    def retired_model():
        calls["n"] += 1
        raise Status(404, "model retired")

    with pytest.raises(LLMError, match="retired"):
        await call_with_retry(
            retired_model, stage="extraction", limiter=RateLimiter(0.0), max_retries=5
        )

    assert calls["n"] == 1


async def test_retries_stay_paced_so_they_do_not_outrun_the_allowance(
    instant_backoff,
):
    import time

    limiter = RateLimiter(0.02)
    started = time.monotonic()

    def throttled():
        raise Status(429, "nope")

    with pytest.raises(LLMError):
        await call_with_retry(throttled, stage="extraction", limiter=limiter, max_retries=4)

    # Four attempts must be spaced by the limiter, not fired back to back.
    assert time.monotonic() - started >= 0.06


# -- shared pacing -------------------------------------------------------------


def test_the_limiter_is_shared_across_text_and_embedding_calls():
    """Two call sites with separate budgets would jointly exceed the ceiling."""
    assert get_limiter(15) is get_limiter(15)


def test_changing_the_rate_replaces_the_limiter():
    assert get_limiter(15) is not get_limiter(5)


def test_a_new_event_loop_gets_a_fresh_limiter():
    """A limiter's lock belongs to the loop that first awaited it."""
    first = asyncio.run(_capture_limiter())
    second = asyncio.run(_capture_limiter())
    assert first is not second


async def _capture_limiter():
    return get_limiter(15)
