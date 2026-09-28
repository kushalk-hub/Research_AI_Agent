"""Gemini implementation of `LLMClient` (google-genai SDK)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ValidationError

from rla.config import Settings, get_settings
from rla.llm.base import LLMError, record_usage
from rla.llm.prompts.templates import prompt_hash
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import Cache, CostTracker

#: Google's response schema for a pydantic model.
ResponseSchema = dict[str, Any]


def _schema_for(model: type[BaseModel]) -> ResponseSchema:
    return model.model_json_schema()


def extract_json(text: str) -> str:
    """Pull a JSON object out of a response that may be wrapped in prose or fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"no JSON object in response: {text[:200]!r}")
    return text[start : end + 1]


class GeminiClient:
    """Cache-first, schema-constrained Gemini client.

    Every call is keyed on (model, prompt, schema, temperature, prompt-hash) so
    re-running a stage costs nothing and prompt edits invalidate cleanly.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._client: Any | None = None

    # -- properties --------------------------------------------------------
    @property
    def fast_model(self) -> str:
        return self.settings.fast_model

    @property
    def strong_model(self) -> str:
        return self.settings.strong_model

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set")
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    # -- internals ---------------------------------------------------------
    def _key(self, prompt: str, model: str, schema: str, temperature: float, tag: str) -> str:
        return "llm:" + content_hash(tag, model, prompt, schema, temperature, prompt_hash(prompt))

    def _config(self, schema: ResponseSchema | None, temperature: float) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": temperature}
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema
        return config

    async def _call(
        self,
        prompt: str,
        model: str,
        schema: ResponseSchema | None,
        temperature: float,
        stage: str,
        tag: str,
    ) -> str:
        cache_key = self._key(
            prompt, model, json.dumps(schema, sort_keys=True) if schema else "", temperature, tag
        )
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                return hit

        config = self._config(schema, temperature)

        def _invoke() -> Any:
            return self.client.models.generate_content(model=model, contents=prompt, config=config)

        response = await call_with_retry(
            _invoke,
            stage=f"gemini call failed for stage {stage}",
            limiter=self.settings.llm_limiter,
            max_retries=self.settings.llm_max_retries,
            spender=self.settings.llm_spender,
        )

        record_usage(self.tracker, stage, response)
        text = response.text or ""
        if schema is not None:
            text = extract_json(text)
        if self.cache is not None:
            self.cache.set(cache_key, text, kind="llm")
        return text

    # -- public API --------------------------------------------------------
    async def generate_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> str:
        return await self._call(prompt, model or self.fast_model, None, temperature, stage, "text")

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
        retries: int = 2,
    ) -> BaseModel:
        json_schema = _schema_for(schema)
        last_error: Exception | None = None
        for _ in range(retries + 1):
            text = await self._call(
                prompt, model or self.fast_model, json_schema, temperature, stage, schema.__name__
            )
            try:
                return schema.model_validate_json(text)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                prompt = (
                    f"{prompt}\n\nYour previous output failed schema validation: {exc}."
                    " Return valid JSON only."
                )
        raise LLMError(f"could not coerce response into {schema.__name__}") from last_error

    async def stream_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> AsyncIterator[str]:
        cache_key = self._key(prompt, model or self.strong_model, "", temperature, "stream")
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                yield hit
                return

        def _iter() -> Any:
            return self.client.models.generate_content_stream(
                model=model or self.strong_model,
                contents=prompt,
                config=self._config(None, temperature),
            )

        stream = await call_with_retry(
            _iter,
            stage=f"gemini stream failed for stage {stage}",
            limiter=self.settings.llm_limiter,
            max_retries=self.settings.llm_max_retries,
            spender=self.settings.llm_spender,
        )

        collected: list[str] = []
        try:
            for chunk in await asyncio.to_thread(lambda: list(stream)):
                piece = getattr(chunk, "text", "") or ""
                if piece:
                    collected.append(piece)
                    yield piece
        except Exception as exc:
            raise LLMError(f"gemini stream failed for stage {stage}: {exc}") from exc

        if self.cache is not None:
            self.cache.set(cache_key, "".join(collected), kind="llm")
