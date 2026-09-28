"""Retry and pacing for LLM calls.

The Gemini free tier allows roughly 20 requests per minute per project. A
corpus build issues one extraction call per paper, so it blows straight through
that ceiling and the API answers `429 RESOURCE_EXHAUSTED`.

Retrying alone is not enough to make that safe, because a 429 mid-stage used to
end the request for good: the HTTP fetcher had backoff, the LLM client had none,
so a single throttle response silently discarded a paper's extraction. Both
halves now share this module so they pace against one global budget rather than
each racing the other.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Callable
from typing import Any, TypeVar

from rla.llm.base import LLMError
from rla.store.cache import RateLimiter

T = TypeVar("T")

#: Status codes worth trying again. 400/401/403/404 are the caller's fault and
#: will fail identically forever, so retrying them only burns quota.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

#: Free-tier quota ids that are counted per day rather than per minute. The 429
#: body names the quota id directly, so the distinction is observable rather than
#: guessed at: a run that paced at 15 rpm and still exhausted its allowance was
#: hitting `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, 20 requests per
#: day per model. Pacing cannot help there, so these raise at once instead of
#: burning five attempts against a bucket that resets in hours.
_DAILY_QUOTA_MARKERS = ("perday", "per_day", "per-day")


def is_daily_quota(exc: BaseException) -> bool:
    """True when a 429 is a daily allowance rather than a per-minute one.

    Checked before the generic retry path so a 20-requests-per-day ceiling stops
    the run in seconds rather than holding a worker for five 38-second waits per
    paper, which is how one 20-paper batch previously burned 15 minutes to
    extract nothing.
    """
    text = str(exc).lower()
    if "resource_exhausted" not in text and "429" not in text:
        return False
    return any(marker in text for marker in _DAILY_QUOTA_MARKERS)


def quota_summary(exc: BaseException) -> str:
    """Pull the human-readable quota line out of a 429 body, if there is one."""
    match = re.search(r"Quota exceeded for metric: ([^\n]+)", str(exc))
    return " ".join(match.group(1).split()) if match else ""

#: Free-tier ceiling observed in practice; stay under it rather than at it.
DEFAULT_LLM_RPM = 15

#: One limiter for the whole process, so text and embedding calls queue up
#: against the same allowance instead of each assuming they have it to themselves.
_limiter: RateLimiter | None = None
_limiter_loop: Any = None


def get_limiter(rpm: int = DEFAULT_LLM_RPM) -> RateLimiter:
    """Return the shared limiter, rebuilding it if the event loop changed.

    `RateLimiter` holds an `asyncio.Lock`, which belongs to the loop that first
    awaited it. Tests drive the client through several `asyncio.run` calls, so a
    cached limiter would otherwise raise "bound to a different event loop".
    """
    global _limiter, _limiter_loop
    try:
        loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if (
        _limiter is None
        or _limiter.min_interval != 60.0 / rpm
        or (loop is not None and _limiter_loop is not loop)
    ):
        _limiter = RateLimiter(60.0 / max(1, rpm))
        _limiter_loop = loop
    return _limiter


def reset_limiter() -> None:
    """Drop the shared limiter. For tests, and for switching tiers mid-process."""
    global _limiter, _limiter_loop
    _limiter = None
    _limiter_loop = None


class BudgetExhausted(LLMError):
    """The per-run request allowance ran out. Not a provider error."""


class Spender:
    """Counts metered calls and refuses to go past a per-run allowance.

    The daily ceiling is the hard constraint, and it is per model. Without a
    local budget the first stage in a run spends the whole day on whatever it is
    asked to process, leaving nothing for the stages after it; with one, the
    failure is a clean "budget exhausted" at a predictable point instead of a
    429 several minutes later.
    """

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.spent = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    @property
    def enabled(self) -> bool:
        return self.budget > 0

    async def acquire(self, stage: str) -> None:
        self.spent += 1
        if not self.enabled:
            return
        if self.spent > self.budget:
            self.spent = self.budget
            raise BudgetExhausted(
                f"{stage}: local request budget of {self.budget} is spent. "
                "The free tier also allows only a fixed number of requests per day "
                "per model, so continuing would fail with 429s anyway. Re-run later, "
                "or raise llm_daily_budget."
            )

    def remaining_for(self, count: int) -> int:
        return max(0, self.budget - self.spent - count)


_spender: Spender | None = None
_spender_loop: Any = None


def get_spender(budget: int) -> Spender:
    """Return the shared spender, rebuilding it if the loop or budget changed."""
    global _spender, _spender_loop
    try:
        loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _spender is None or _spender.budget != budget or (loop and _spender_loop is not loop):
        _spender = Spender(budget)
        _spender_loop = loop
    return _spender


def reset_spender() -> None:
    """Drop the shared spender. For tests."""
    global _spender, _spender_loop
    _spender = None
    _spender_loop = None


def _status(exc: BaseException) -> int | None:
    """Pull an HTTP status out of the SDK's several error shapes."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def is_retryable(exc: BaseException) -> bool:
    """True for throttling, overload, and dropped connections. Not for bad input."""
    status = _status(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    # The SDK surfaces a severed stream as a plain message, with no status.
    text = str(exc).lower()
    return any(
        phrase in text
        for phrase in (
            "disconnected",
            "connection reset",
            "connection refused",
            "timed out",
            "timeout",
            "overloaded",
            "unavailable",
            "resource_exhausted",
            "too many requests",
        )
    )


def retry_delay(exc: BaseException, attempt: int, cap: float = 60.0) -> float:
    """Back off exponentially, preferring the server's own Retry-After hint.

    Jitter is applied so a corpus-wide burst does not retry in lockstep and
    re-trip the limiter it is already waiting on.
    """
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
    if match:
        return min(float(match.group(1)), cap)
    return min(2.0**attempt, cap) * (0.5 + random.random() / 2)


async def call_with_retry(
    fn: Callable[[], Any],
    *,
    stage: str,
    limiter: RateLimiter | None = None,
    max_retries: int = 5,
    retryable: Callable[[BaseException], bool] = is_retryable,
    spender: Spender | None = None,
) -> Any:
    """Run a blocking SDK call off-thread, pacing and retrying as needed.

    `spender` is charged once per attempt that actually leaves the process, not
    once per logical call, because a retried request is a second metered
    request. Cached calls never reach here and so are never charged.
    """
    pace = limiter or get_limiter()
    last: BaseException | None = None
    for attempt in range(max_retries):
        if spender is not None:
            await spender.acquire(stage)
        await pace.acquire()
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:  # SDK raises a broad family of errors
            if not retryable(exc):
                raise LLMError(f"{stage}: {exc}") from exc
            if is_daily_quota(exc):
                summary = quota_summary(exc)
                raise LLMError(
                    f"{stage}: daily free-tier quota exhausted"
                    + (f" ({summary})" if summary else "")
                    + ". This limit is per day per model and does not reset by "
                    "waiting; stop here, switch to a model with quota remaining, "
                    "or resume after the daily reset."
                ) from exc
            last = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay(exc, attempt))
    raise LLMError(f"{stage}: still failing after {max_retries} attempts: {last}") from last


__all__ = [
    "DEFAULT_LLM_RPM",
    "BudgetExhausted",
    "Spender",
    "call_with_retry",
    "get_limiter",
    "get_spender",
    "is_daily_quota",
    "is_retryable",
    "quota_summary",
    "reset_limiter",
    "reset_spender",
    "retry_delay",
]
