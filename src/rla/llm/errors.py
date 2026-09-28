"""Provider-neutral error categories.

The audit found that reliability was being inferred from provider error *strings*
(`retry.is_daily_quota` matching Gemini's 429 body, `extraction._is_auth_error`
matching message markers). That couples the reliability architecture to whichever
SDK happens to be installed, and it fails open: an unrecognised error string is
treated as a generic retryable failure and burns the retry budget on something
that will never succeed.

The categories here are the vocabulary the rest of the application reasons about.
Backends translate whatever their SDK raises into one of these, and the router
decides retry/fallback from the category rather than from a message.

Every class subclasses `LLMError`, itself a `RuntimeError`, so the existing
`except (LLMError, RuntimeError)` handlers in the pipeline keep working.
"""

from __future__ import annotations

import enum
from typing import Any

from rla.llm.base import LLMError


class ErrorCategory(enum.StrEnum):
    """What kind of failure this is, in terms the application can act on."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    AUTH_FAILED = "auth_failed"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    STRUCTURED_OUTPUT = "structured_output"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"


class ProviderError(LLMError):
    """A provider call failed, in a form the application can reason about.

    Subclasses `LLMError` (and therefore `RuntimeError`) so every pre-existing
    `except LLMError` / `except RuntimeError` handler in the pipeline keeps
    working. `category` is the real payload: `retryable` and `fallback_eligible`
    are derived from it, so no caller re-derives the policy in its own way.
    """

    category: ErrorCategory = ErrorCategory.UNKNOWN

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory | None = None,
        provider: str = "",
        model: str = "",
        stage: str = "",
    ) -> None:
        super().__init__(message)
        if category is not None:
            self.category = category
        self.provider = provider
        self.model = model
        self.stage = stage

    @property
    def retryable(self) -> bool:
        """Transient conditions worth another attempt on the same model."""
        return self.category in _RETRYABLE

    @property
    def fallback_eligible(self) -> bool:
        """Whether the router may transparently try another model.

        Quota exhaustion is deliberately excluded. It is a capacity condition
        rather than a fault, and silently moving to a second model's budget
        spends the reserve the operator wanted kept. See ADR-004.
        """
        return self.category in _FALLBACK_ELIGIBLE

    def with_context(
        self, *, provider: str = "", model: str = "", stage: str = ""
    ) -> ProviderError:
        """Fill in context discovered after construction, without losing the type."""
        self.provider = self.provider or provider
        self.model = self.model or model
        self.stage = self.stage or stage
        return self


#: Transient: the same request may succeed later.
_RETRYABLE: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.TIMEOUT,
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.NETWORK_ERROR,
    }
)

#: Transient *and* worth trying elsewhere. Deliberately excludes QUOTA_EXHAUSTED.
_FALLBACK_ELIGIBLE: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.TIMEOUT,
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.NETWORK_ERROR,
    }
)


class ProviderTimeout(ProviderError):
    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.TIMEOUT, **kw)


class ProviderRateLimited(ProviderError):
    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.RATE_LIMITED, **kw)


class ProviderQuotaExhausted(ProviderError):
    """A per-model daily/period allowance is spent.

    Not retryable: the limit does not reset by waiting within a run, so retrying
    just spends wall-clock to arrive at the same answer.
    """

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.QUOTA_EXHAUSTED, **kw)


class ProviderServerError(ProviderError):
    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.SERVER_ERROR, **kw)


class ProviderNetworkError(ProviderError):
    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.NETWORK_ERROR, **kw)


class ProviderAuthFailed(ProviderError):
    """Credentials are missing, malformed, or lack access.

    Terminal by design. Retrying a 401 against more models multiplies the cost of
    a one-line configuration fix.
    """

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.AUTH_FAILED, **kw)


class ProviderInvalidRequest(ProviderError):
    """Malformed request, unknown model, or a contract the provider rejected.

    Terminal: this is a bug or a configuration error, not a transient condition.
    """

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.INVALID_REQUEST, **kw)


class ProviderUnsupported(ProviderError):
    """The provider or model lacks a capability the stage requires."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.UNSUPPORTED, **kw)


class StructuredOutputError(ProviderError):
    """The provider could not produce output satisfying the requested schema.

    Raised only after the inner self-correcting retry has been exhausted, so it
    represents a genuine contract failure rather than a single bad response.
    """

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.STRUCTURED_OUTPUT, **kw)


class EmbeddingDimensionMismatch(ProviderError):
    """Two embedding vectors of different lengths were compared.

    The previous behaviour returned 0.0 for a length mismatch, which is the
    dangerous kind of bug: it silently disabled the cosine-similarity tiers of
    entity resolution and the result looked like "these concepts are unrelated"
    rather than "the model changed underneath us".
    """

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, category=ErrorCategory.INVALID_REQUEST, **kw)


__all__ = [
    "EmbeddingDimensionMismatch",
    "ErrorCategory",
    "ProviderAuthFailed",
    "ProviderError",
    "ProviderInvalidRequest",
    "ProviderNetworkError",
    "ProviderQuotaExhausted",
    "ProviderRateLimited",
    "ProviderServerError",
    "ProviderTimeout",
    "ProviderUnsupported",
    "StructuredOutputError",
]
