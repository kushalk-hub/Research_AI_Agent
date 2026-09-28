"""LLM abstraction.

Only GEMINI_API_KEY is present on this machine, so Gemini is the shipped
implementation. The protocol is deliberately small: another provider needs one
class implementing `LLMClient` plus a key in config — no call sites change.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from rla.store.cache import CostTracker


class LLMError(RuntimeError):
    """Raised when a model call fails or returns unusable output."""


@runtime_checkable
class LLMClient(Protocol):
    """Structured-output contract shared by every provider."""

    @property
    def fast_model(self) -> str: ...

    @property
    def strong_model(self) -> str: ...

    async def generate_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> str:
        """Free-text completion."""
        ...

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> BaseModel:
        """Completion constrained to `schema`. Must raise LLMError if unparseable."""
        ...

    async def stream_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> Any:
        """Async iterator over answer chunks, for the streamed answer panel."""
        ...


def usage_from_response(response: Any) -> tuple[int, int]:
    """Pull (input, output) token counts out of a provider response, tolerantly."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return (0, 0)
    return (
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
    )


def record_usage(tracker: CostTracker, stage: str, response: Any) -> None:
    input_tokens, output_tokens = usage_from_response(response)
    tracker.record(stage, input_tokens, output_tokens)
