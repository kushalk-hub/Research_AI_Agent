"""Translate provider/SDK exceptions into application error categories.

The audit found reliability inferred from error *strings* -- `is_daily_quota` matching
Gemini's 429 body, `_is_auth_error` matching message markers. That couples the reliability
architecture to one SDK and, worse, fails open: an unrecognised string is treated as a
generic retryable error, so a permanent fault burns the full retry budget before surfacing.

Mapping here is by exception **type and HTTP status** wherever the SDK provides them.
String inspection is kept in exactly one place -- `_looks_like_period_quota` -- as an
early pre-classifier, because a period quota is cheap to recognise from a message and
otherwise indistinguishable from a burst 429 by status code alone. It is a supplement to
type-based mapping, not the mechanism.
"""

from __future__ import annotations

import re
from typing import Any

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
)

#: Free-tier quota ids name the *period*, which a 429 status code does not. The
#: markers are narrow on purpose: "perday" is a strong signal, "limit" is not.
_PERIOD_QUOTA_MARKERS = ("perday", "per_day", "per-day", "daily free-tier", "dailyquota")


def _status(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an SDK exception of any common shape."""
    for attr in ("status_code", "code", "http_status", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    return None


def _looks_like_period_quota(exc: BaseException) -> bool:
    """True when a 429 describes a per-day/period allowance rather than a burst.

    Retained as a *pre-classifier only*. Matching on a message is a heuristic; it
    is used to separate two conditions that share a status code, never to
    distinguish one SDK's errors from another's.

    The load-bearing signal is the `quotaId` in the body -- Gemini names it
    `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. A "please retry in 38s"
    hint alongside it is NOT evidence of a burst bucket: a real captured per-day
    429 carries both. An experiment treating a short retry window as an override
    was tried during live validation and reverted for exactly this reason -- it
    made every daily-cap failure retryable, tripling the wait before the same
    terminal error.
    """
    text = str(exc).lower()
    if "resource_exhausted" not in text and "429" not in text:
        return False
    return any(marker in text for marker in _PERIOD_QUOTA_MARKERS)


def _class_name(exc: BaseException) -> str:
    return type(exc).__name__.lower()


def _classify(exc: BaseException) -> ErrorCategory:
    """Map an exception to a category using type and status, not prose."""
    name = _class_name(exc)
    status = _status(exc)
    # A Gemini-style structured error body ("400 INVALID_ARGUMENT: ...") lives in
    # the message rather than on the exception. Typed SDK errors are matched by
    # status above; this recovers the code from a plain-Exception wrapper, which
    # is what the SDKs raise when an error body is not mapped to a typed class.
    if status is None:
        numeric = re.search(r"\b([45]\d\d)\b", str(exc))
        if numeric:
            status = int(numeric.group(1))

    if isinstance(exc, TimeoutError) or "timeout" in name or "timeout" in str(exc).lower():
        return ErrorCategory.TIMEOUT
    if "budgetexhausted" in name or "quotaexhausted" in name:
        return ErrorCategory.BUDGET_EXHAUSTED
    if "unsupported" in name or "notimplemented" in name:
        return ErrorCategory.UNSUPPORTED
    # Auth must precede the status-code checks: 401 and 403 are 4xx, and
    # "treat 4xx as invalid request" would otherwise misfile a bad credential as a
    # programming error, sending the operator to the prompt instead of the key.
    text = str(exc).lower()
    if (
        "authentication" in name
        or "permissiondenied" in name
        or "unauthenticated" in text
        or "permission_denied" in text
        or "invalid api key" in text
        or "api_key_invalid" in text
        or "invalid credentials" in text
        or "credential" in text
        or status in (401, 403)
    ):
        return ErrorCategory.AUTH_FAILED
    if "contextwindow" in name or "context_length" in text:
        return ErrorCategory.INVALID_REQUEST
    if "ratelimit" in name or status == 429:
        return (
            ErrorCategory.QUOTA_EXHAUSTED
            if _looks_like_period_quota(exc)
            else ErrorCategory.RATE_LIMITED
        )
    if "notfound" in name or status == 404:
        return ErrorCategory.INVALID_REQUEST
    if "badrequest" in name or "invalidrequest" in name or "unprocessable" in name:
        return ErrorCategory.INVALID_REQUEST
    if "serviceunavailable" in name or "internalserver" in name or "badgateway" in name:
        return ErrorCategory.SERVER_ERROR
    if status is not None and 500 <= status < 600:
        return ErrorCategory.SERVER_ERROR
    if "apiconnection" in name or "connect" in name or isinstance(exc, ConnectionError):
        return ErrorCategory.NETWORK_ERROR
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return ErrorCategory.NETWORK_ERROR
    if status is not None and 400 <= status < 500:
        return ErrorCategory.INVALID_REQUEST
    return ErrorCategory.UNKNOWN


_CONSTRUCTORS = {
    ErrorCategory.TIMEOUT: ProviderTimeout,
    ErrorCategory.RATE_LIMITED: ProviderRateLimited,
    ErrorCategory.QUOTA_EXHAUSTED: ProviderQuotaExhausted,
    ErrorCategory.SERVER_ERROR: ProviderServerError,
    ErrorCategory.NETWORK_ERROR: ProviderNetworkError,
    ErrorCategory.AUTH_FAILED: ProviderAuthFailed,
    ErrorCategory.INVALID_REQUEST: ProviderInvalidRequest,
    ErrorCategory.UNSUPPORTED: ProviderUnsupported,
}


def normalize(exc: BaseException, **context: Any) -> ProviderError:
    """Convert any exception into a `ProviderError` with the right category.

    Idempotent: normalising an already-normalised error returns it unchanged, so
    nested backends can normalise defensively without wrapping categories.
    """
    if isinstance(exc, ProviderError):
        return exc.with_context(**{k: v for k, v in context.items() if isinstance(v, str)})

    category = _classify(exc)
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    constructor = _CONSTRUCTORS.get(category)
    if constructor is None:
        return ProviderError(message, category=category, **context)
    return constructor(message, **context)


def quota_hint(exc: BaseException) -> str:
    """Pull the human-readable quota line out of a 429 body, if there is one."""
    match = re.search(r"Quota exceeded for metric: ([^\n]+)", str(exc))
    return " ".join(match.group(1).split()) if match else ""


__all__ = ["ErrorCategory", "normalize", "quota_hint"]
