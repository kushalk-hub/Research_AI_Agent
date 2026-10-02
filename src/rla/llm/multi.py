"""Dispatch each model id to the provider that owns it.

This sits *below* `ProviderRouter` and *above* the concrete backends. Pipeline
stages never see it; they receive an `LLMClient` and are unaware which provider
served the call (ADR-001).

It owns exactly one decision: which backend serves a given model id. It does not
own retry, pacing, budget, caching, capability policy or fallback order -- those
stay in `ProviderRouter` and `llm/retry.py` (ADR-003).

Cross-provider fallback needs no router change because `ProviderRouter._dispatch`
already iterates candidates and calls `run(model=candidate)`; resolving the owner
per candidate is sufficient.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from rla.config import NATIVE_PROVIDERS, Settings, get_settings
from rla.errors import ModelResolutionError
from rla.llm.gemini import GeminiClient
from rla.store.cache import CostTracker

_STRUCTURED = "supports_structured_output"


class MultiBackend:
    """Resolves a model id to its owning backend, constructing backends lazily.

    Laziness matters: a Gemini-only configuration must never import or construct
    an Ollama or LiteLLM backend, which is what keeps the `[router]` extra
    genuinely optional.
    """

    name = "multi"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._backends: dict[str, Any] = {}

    # -- resolution ---------------------------------------------------------
    def provider_for(self, model: str) -> str:
        """The backend name that serves `model`.

        Derived from the canonical id, so the answer never depends on which
        backend happens to be configured as the default.
        """
        return self.settings.canonical_model(model).split("/", 1)[0]

    def backend_for(self, model: str) -> Any:
        """The backend instance for `model`, built on first use."""
        provider = self.provider_for(model)
        if provider not in self._backends:
            self._backends[provider] = self._construct(provider)
        return self._backends[provider]

    def _construct(self, provider: str) -> Any:
        if provider == "gemini":
            return GeminiClient(self.settings, self.cache, self.tracker)
        if provider == "ollama":
            from rla.llm.ollama_backend import OllamaBackend

            return OllamaBackend(self.settings, self.cache, self.tracker)
        if provider in NATIVE_PROVIDERS:
            raise ModelResolutionError(
                f"provider {provider!r} has no backend; expected one of "
                "gemini, ollama, or a LiteLLM-served provider"
            )
        from rla.llm.litellm_backend import LiteLLMBackend

        return LiteLLMBackend(self.settings, self.cache, self.tracker)

    def live_backends(self) -> dict[str, str]:
        """Provider name to backend name, for `doctor` and diagnostics."""
        return {provider: backend.name for provider, backend in self._backends.items()}

    # -- RoutingBackend -----------------------------------------------------
    def supports(self, model: str, capability: str) -> bool:
        return self.backend_for(model).supports(model, capability)

    async def generate_text(
        self, prompt: str, *, model: str, temperature: float = 0.0, stage: str = "llm"
    ) -> tuple[str, Any]:
        return await self.backend_for(model).generate_text(
            prompt, model=model, temperature=temperature, stage=stage
        )

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], *, model: str, temperature: float = 0.0,
        stage: str = "llm", retries: int = 2,
    ) -> tuple[BaseModel, Any]:
        return await self.backend_for(model).generate_structured(
            prompt, schema, model=model, temperature=temperature, stage=stage, retries=retries
        )

    async def stream_text(
        self, prompt: str, *, model: str, temperature: float = 0.0, stage: str = "llm"
    ) -> AsyncIterator[str]:
        async for chunk in self.backend_for(model).stream_text(
            prompt, model=model, temperature=temperature, stage=stage
        ):
            yield chunk


__all__ = ["MultiBackend"]
