"""LiteLLM-backed provider implementation.

The only module in the project that imports `litellm`. It is imported lazily inside
`_litellm()` so that:

- the default `pip install -e .` (7 runtime deps) keeps working with no LiteLLM present;
- the test suite runs without the `[router]` extra installed;
- removing the extra cannot break the direct Gemini path.

`litellm` is not a universal equaliser and is not treated as one here. Its structured
output support is genuinely provider-dependent, so this backend *asks* LiteLLM
(`supports_response_schema`) and reports the answer to the router, which refuses
unqualified fallbacks rather than degrading to unvalidated JSON (ADR-004).

Retry ownership: LiteLLM is called with `num_retries=0` and RLA's `call_with_retry` does
the retrying, so a single logical call never passes through two retry loops (ADR-003).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ValidationError

from rla.config import Settings, get_settings
from rla.llm.base import record_usage
from rla.llm.error_map import normalize
from rla.llm.errors import ProviderUnsupported, StructuredOutputError
from rla.llm.gemini import extract_json
from rla.llm.prompts.templates import prompt_hash
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import Cache, CostTracker

_STRUCTURED = "supports_structured_output"

_MISSING = (
    "the LiteLLM backend needs the optional 'router' extra.\n"
    'Install it with:  pip install -e ".[router]"\n'
    "Alternatively set RLA_LLM_PROVIDER=gemini to use the direct backend."
)


class LiteLLMUnavailable(RuntimeError):
    """LiteLLM is not installed. Configuration error, not a provider failure."""


def _litellm() -> Any:
    """Import litellm on demand, with a message that says how to fix it."""
    try:
        import litellm
    except ImportError as exc:
        raise LiteLLMUnavailable(_MISSING) from exc
    # Non-deterministic retries are RLA's job (ADR-003); silence LiteLLM's own so
    # a single failure is not retried in two places.
    litellm.drop_params = True
    return litellm


def route_model(model: str) -> str:
    """Give a bare model id the `provider/` prefix LiteLLM routes on.

    A bare id is accepted so the same configuration works for both backends:
    `RLA_FAST_MODEL=gemini-2.5-flash-lite` and
    `RLA_FAST_MODEL=gemini/gemini-2.5-flash` both mean the same model.
    """
    if "/" in model:
        return model
    if model.startswith("gemini"):
        return f"gemini/{model}"
    if model.startswith(("gpt", "o1", "o3", "text-embedding")):
        return f"openai/{model}"
    if model.startswith("claude"):
        return f"anthropic/{model}"
    return model


class LiteLLMBackend:
    """`RoutingBackend` implementation delegating to LiteLLM."""

    name = "litellm"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._capability_cache: dict[str, bool] = {}

    # -- capabilities -------------------------------------------------------
    def supports(self, model: str, capability: str) -> bool:
        """Ask LiteLLM what this model can do.

        An unanswerable question is answered "no". Assuming a capability for an
        unknown model is exactly how structured output degrades silently, so the
        safe default is refusal and the router surfaces a clear reason.
        """
        if capability != _STRUCTURED:
            return False
        routed = route_model(model)
        if routed in self._capability_cache:
            return self._capability_cache[routed]
        try:
            litellm = _litellm()
            supported = bool(
                litellm.supports_response_schema(model=routed)
            )
        except LiteLLMUnavailable:
            raise
        except Exception:
            supported = False
        self._capability_cache[routed] = supported
        return supported

    # -- internals ---------------------------------------------------------
    def _key(self, prompt: str, model: str, schema: str, temperature: float, tag: str) -> str:
        return "llm:" + content_hash(tag, model, prompt, schema, temperature, prompt_hash(prompt))

    def _cached(self, key: str) -> str | None:
        if self.cache is None:
            return None
        hit = self.cache.get(key, kind="llm")
        return hit

    def _store(self, key: str, value: str) -> None:
        if self.cache is not None:
            self.cache.set(key, value, kind="llm")

    async def _acompletion(self, **kwargs: Any) -> Any:
        """One LiteLLM completion, paced/retried/budgeted by RLA and normalised.

        `num_retries=0` is deliberate: RLA owns the retry loop (ADR-003).

        A per-provider `base_url` is attached here rather than at each call site, so
        every request path -- text, structured, streaming -- picks up the endpoint
        override uniformly. `None` means "provider default", which is left absent
        from the kwargs so LiteLLM keeps its own default.
        """
        litellm = _litellm()

        base_url = self.settings.base_url_for(kwargs.get("model", ""))
        if base_url:
            kwargs["base_url"] = base_url

        def _invoke() -> Any:
            return litellm.completion(num_retries=0, **kwargs)

        try:
            return await call_with_retry(
                _invoke,
                stage="litellm call failed",
                limiter=self.settings.llm_limiter,
                max_retries=self.settings.llm_max_retries,
                spender=self.settings.llm_spender,
                timeout=self.settings.llm_timeout_seconds,
            )
        except Exception as exc:
            raise normalize(exc, provider="litellm", model=kwargs.get("model", "")) from exc

    @staticmethod
    def _content(response: Any) -> str:
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise normalize(exc, provider="litellm") from exc

    # -- public API --------------------------------------------------------
    async def generate_text(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        stage: str,
    ) -> tuple[str, Any]:
        routed = route_model(model)
        key = self._key(prompt, routed, "", temperature, "text")
        hit = self._cached(key)
        if hit is not None:
            return hit, None

        response = await self._acompletion(
            model=routed, messages=[{"role": "user", "content": prompt}], temperature=temperature
        )
        record_usage(self.tracker, stage, response)
        text = self._content(response)
        self._store(key, text)
        return text, response

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str,
        temperature: float,
        stage: str,
        retries: int = 2,
    ) -> tuple[BaseModel, Any]:
        routed = route_model(model)
        if not self.supports(model, _STRUCTURED):
            raise ProviderUnsupported(
                f"model {model!r} does not support schema-constrained output; "
                "refusing rather than degrading to unvalidated JSON",
                model=model,
                stage=stage,
            )

        json_schema = schema.model_json_schema()
        key = self._key(prompt, routed, json.dumps(json_schema, sort_keys=True), temperature,
                        schema.__name__)
        last_error: Exception | None = None
        current = prompt
        for _ in range(retries + 1):
            hit = self._cached(key)
            if hit is not None:
                try:
                    return schema.model_validate_json(hit), None
                except (ValidationError, json.JSONDecodeError) as exc:
                    last_error = exc
                    current = (
                        f"{prompt}\n\nYour previous output failed schema validation: {exc}."
                        " Return valid JSON only."
                    )
                    continue

            response = await self._acompletion(
                model=routed,
                messages=[{"role": "user", "content": current}],
                temperature=temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": json_schema,
                        "strict": True,
                    },
                },
            )
            record_usage(self.tracker, stage, response)
            text = extract_json(self._content(response))
            self._store(key, text)
            try:
                return schema.model_validate_json(text), response
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                current = (
                    f"{prompt}\n\nYour previous output failed schema validation: {exc}."
                    " Return valid JSON only."
                )
        raise StructuredOutputError(
            f"could not coerce response into {schema.__name__} after {retries + 1} attempts"
        ) from last_error

    async def stream_text(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        stage: str,
    ) -> AsyncIterator[str]:
        routed = route_model(model)
        key = self._key(prompt, routed, "", temperature, "stream")
        hit = self._cached(key)
        if hit is not None:
            yield hit
            return

        litellm = _litellm()

        base_url = self.settings.base_url_for(routed)
        stream_kwargs: dict[str, Any] = {
            "num_retries": 0,
            "model": routed,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if base_url:
            stream_kwargs["base_url"] = base_url

        def _open() -> Any:
            return litellm.completion(**stream_kwargs)

        try:
            stream = await call_with_retry(
                _open,
                stage="litellm stream failed",
                limiter=self.settings.llm_limiter,
                max_retries=self.settings.llm_max_retries,
                spender=self.settings.llm_spender,
            )
        except Exception as exc:
            raise normalize(exc, provider="litellm", model=routed, stage=stage) from exc

        collected: list[str] = []

        def _drain() -> tuple[list[str], Any]:
            """Drain the sync iterator off-thread, keeping the usage-bearing tail.

            `stream_options={"include_usage": True}` makes the provider emit a
            final chunk carrying usage; without reading it, streamed calls would
            remain unmetered, which was one of the audit's findings.
            """
            pieces: list[str] = []
            tail: Any = None
            for chunk in stream:
                tail = chunk
                delta = getattr(chunk, "choices", None)
                text = ""
                if delta:
                    choice = delta[0]
                    text = getattr(getattr(choice, "delta", None), "content", "") or ""
                if text:
                    pieces.append(text)
            return pieces, tail

        try:
            pieces, tail = await asyncio.to_thread(_drain)
        except Exception as exc:
            raise normalize(exc, provider="litellm", model=routed, stage=stage) from exc

        for piece in pieces:
            collected.append(piece)
            yield piece

        if tail is not None:
            record_usage(self.tracker, stage, tail)
        self._store(key, "".join(collected))


__all__ = ["LiteLLMBackend", "LiteLLMUnavailable", "route_model"]
