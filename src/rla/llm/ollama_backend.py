"""Native Ollama text backend.

The only reason this exists is a measured penalty. Routing Ollama through
LiteLLM's OpenAI-compatible route costs ~4096 prompt tokens per extraction,
because that route implements structured output by prepending ~3.4k tokens of
format instructions. Ollama's native `/api/generate` grammar-constrains the same
schema with a ~662-token prompt: measured 8.1s versus 97.6s on 2026-10-02.

Retry ownership: `call_with_retry` retries, never this module (ADR-003).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from rla.config import Settings, get_settings
from rla.llm.base import LLMError, record_usage
from rla.llm.error_map import normalize
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.gemini import extract_json
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import CostTracker

_STRUCTURED = "supports_structured_output"
_PULL_HINT = re.compile(r"model '([^']+)' not found")


class OllamaBackend:
    """Cache-first, grammar-constrained backend for a local Ollama server."""

    name = "ollama"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()

    # -- capabilities -------------------------------------------------------
    def supports(self, model: str, capability: str) -> bool:
        """Report what this backend can actually do, rather than what the model
        is called.

        Ollama grammar-constrains any JSON schema supplied as `format`, so this
        answers honestly and needs no operator declaration -- unlike the LiteLLM
        route, whose static table answers `False` for a model it has no entry for.
        """
        if capability != _STRUCTURED:
            return False
        return "embed" not in model

    # -- internals ---------------------------------------------------------
    def _model_name(self, model: str) -> str:
        """Strip the `ollama/` prefix: the server knows the bare tag."""
        return model.split("/", 1)[1] if "/" in model else model

    def _key(self, prompt: str, model: str, schema: str, temperature: float, tag: str) -> str:
        return "llm:" + content_hash(tag, model, prompt, schema, temperature)

    def _payload(
        self, prompt: str, model: str, temperature: float, schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_name(model),
            "prompt": prompt,
            "stream": stream,
            "think": self.settings.ollama_think,
            "options": {"temperature": temperature},
        }
        if schema is not None:
            # The schema is a grammar constraint, not prompt text. Keeping it
            # out of the prompt is the entire performance reason this backend
            # exists; a test pins that the prompt is never rewritten.
            payload["format"] = schema
        return payload

    def _post_sync(self, payload: dict[str, Any]) -> Any:
        response = httpx.post(
            f"{self.settings.ollama_url.rstrip('/')}/api/generate",
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        if response.status_code == 404:
            raise self._pull_hint(response, payload["model"])
        response.raise_for_status()
        return response

    def _pull_hint(self, response: httpx.Response, model: str) -> ProviderInvalidRequest:
        match = _PULL_HINT.search(response.text)
        name = match.group(1) if match else model
        return ProviderInvalidRequest(
            f"model {name!r} is not available on the Ollama server at "
            f"{self.settings.ollama_url}. Load it with: ollama pull {name}"
        )

    async def _generate(
        self, prompt: str, model: str, temperature: float,
        schema: dict[str, Any] | None, stage: str, tag: str,
    ) -> tuple[str, Any]:
        cache_key = self._key(
            prompt, model, json.dumps(schema, sort_keys=True) if schema else "",
            temperature, tag,
        )
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                return hit, None

        payload = self._payload(prompt, model, temperature, schema, stream=False)

        def _invoke() -> Any:
            return self._post_sync(payload)

        try:
            response = await call_with_retry(
                _invoke,
                stage=f"ollama call failed for stage {stage}",
                limiter=self.settings.llm_limiter,
                max_retries=self.settings.llm_max_retries,
                spender=self.settings.llm_spender,
                timeout=self.settings.llm_timeout_seconds,
            )
        except ProviderInvalidRequest:
            raise
        except Exception as exc:
            raise normalize(exc, provider="ollama", model=model, stage=stage) from exc

        record_usage(self.tracker, stage, response.json())
        text = response.json().get("response", "") or ""
        if schema is not None:
            text = extract_json(text)
        if self.cache is not None:
            self.cache.set(cache_key, text, kind="llm")
        return text, response

    # -- public API --------------------------------------------------------
    async def generate_text(
        self, prompt: str, *, model: str | None = None, temperature: float = 0.0,
        stage: str = "llm",
    ) -> tuple[str, Any]:
        chosen = model or self.settings.fast_model
        return await self._generate(prompt, chosen, temperature, None, stage, "text")

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], *, model: str | None = None,
        temperature: float = 0.0, stage: str = "llm", retries: int = 2,
    ) -> tuple[BaseModel, Any]:
        chosen = model or self.settings.model_for_structured
        json_schema = schema.model_json_schema()
        current = prompt
        last: Exception | None = None
        for _ in range(retries + 1):
            text, response = await self._generate(
                current, chosen, temperature, json_schema, stage, schema.__name__
            )
            try:
                return schema.model_validate_json(text), response
            except (ValueError, json.JSONDecodeError) as exc:
                last = exc
                current = (
                    f"{prompt}\n\nYour previous output failed schema validation: {exc}. "
                    "Return valid JSON only."
                )
        from rla.llm.errors import StructuredOutputError

        raise StructuredOutputError(
            f"could not coerce response into {schema.__name__} after {retries + 1} attempts"
        ) from last

    async def stream_text(
        self, prompt: str, *, model: str | None = None, temperature: float = 0.0,
        stage: str = "llm",
    ) -> AsyncIterator[str]:
        chosen = model or self.settings.strong_model
        cache_key = self._key(prompt, chosen, "", temperature, "stream")
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                yield hit
                return

        payload = self._payload(prompt, chosen, temperature, None, stream=True)
        collected: list[str] = []
        try:
            with httpx.stream(
                "POST", f"{self.settings.ollama_url.rstrip('/')}/api/generate",
                json=payload, timeout=self.settings.llm_timeout_seconds,
            ) as response:
                if response.status_code == 404:
                    raise self._pull_hint(response, payload["model"])
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = chunk.get("response") or ""
                    if piece:
                        collected.append(piece)
                        yield piece
        except LLMError:
            raise
        except Exception as exc:
            raise normalize(exc, provider="ollama", model=chosen, stage=stage) from exc

        if self.cache is not None:
            self.cache.set(cache_key, "".join(collected), kind="llm")
