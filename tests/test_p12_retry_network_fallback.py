"""P12: a transport failure must keep its network category across the retry layer.

`call_with_retry` dropped the category for non-retryable exceptions by raising a
bare `LLMError`, which normalises to UNKNOWN (not fallback-eligible). A DNS
failure (`httpx.ConnectError`) therefore never failed over even though direct
`normalize` correctly yields NETWORK_ERROR.
"""

from __future__ import annotations

import httpx
import pytest

from rla.llm.errors import ErrorCategory, ProviderError
from rla.llm.retry import call_with_retry, is_retryable
from rla.store.cache import RateLimiter


def _no_wait():
    return RateLimiter(0.0)


async def test_connect_error_keeps_network_category_without_retries(monkeypatch):
    """Non-retryable path must still normalise, not wrap in bare LLMError."""
    monkeypatch.setattr("rla.llm.retry.retry_delay", lambda exc, attempt, cap=60.0: 0.0)
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise httpx.ConnectError("dns fail")

    with pytest.raises(ProviderError) as caught:
        await call_with_retry(_boom, stage="extraction", limiter=_no_wait(), max_retries=5)

    assert caught.value.category is ErrorCategory.NETWORK_ERROR
    assert caught.value.fallback_eligible is True


def test_httpx_transport_errors_are_retryable():
    assert is_retryable(httpx.ConnectError("dns fail")) is True
    assert is_retryable(httpx.NetworkError("unreachable")) is True


def test_httpx_4xx_stays_non_retryable():
    """Extending retryability must not weaken bad-input semantics."""
    request = httpx.Request("POST", "http://localhost:11434/api/generate")
    response = httpx.Response(400, request=request)
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)
    assert is_retryable(exc) is False
