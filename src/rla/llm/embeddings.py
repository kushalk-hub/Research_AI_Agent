"""Concept embeddings for entity resolution (spec section 9).

Direct Gemini embedding backend. Implements `EmbedderClient`, so a provider swap is
handled by the factory rather than by any caller.

Local `cosine` is re-exported from `llm.embedding_base` so there is exactly one
implementation of the similarity maths, and it raises on a dimension mismatch instead
of returning 0.0.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from rla.config import Settings, get_settings
from rla.llm.base import record_usage
from rla.llm.embedding_base import assert_uniform_dimension, cosine, describe
from rla.llm.error_map import normalize
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import Cache, CostTracker

__all__ = ["Embedder", "assert_uniform_dimension", "cosine", "describe"]


class Embedder:
    """Cache-first embedder over `name + description` strings."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._client: object | None = None
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int | None:
        """Width observed from the provider, or None before the first call."""
        return self._dimensions

    @property
    def client(self) -> object:
        if self._client is None:
            if not self.settings.gemini_api_key:
                from rla.llm.errors import ProviderAuthFailed

                raise ProviderAuthFailed("GEMINI_API_KEY is not set")
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    @property
    def model_id(self) -> str:
        """Canonical id. Keeps Gemini and a local model from sharing a cache entry."""
        return self.settings.canonical_model(self.settings.embedding_model)

    def _key(self, text: str) -> str:
        return "embed:" + content_hash(self.model_id, text)

    def key(self, text: str) -> str:
        """Public cache identity, part of the `EmbeddingProvider` contract."""
        return self._key(text)

    async def embed_one(self, text: str) -> list[float]:
        cache_key = self._key(text)
        if self.cache is not None:
            hit = self.cache.get_json(cache_key, kind="embed")
            if hit is not None:
                vector = [float(x) for x in hit]
                self._dimensions = len(vector)
                return vector

        def _invoke() -> object:
            return self.client.models.embed_content(
                model=self.settings.embedding_model, contents=text
            )

        try:
            response = await call_with_retry(
                _invoke,
                stage="embedding failed",
                limiter=self.settings.llm_limiter,
                max_retries=self.settings.llm_max_retries,
                spender=self.settings.llm_spender,
                timeout=self.settings.llm_timeout_seconds,
            )
        except Exception as exc:
            raise normalize(
                exc, provider="gemini", model=self.settings.embedding_model, stage="embed"
            ) from exc

        record_usage(self.tracker, "embed", response)
        vector = [float(x) for x in response.embeddings[0].values]
        self._dimensions = len(vector)
        if self.cache is not None:
            self.cache.set_json(cache_key, vector, kind="embed")
        return vector

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = list(await asyncio.gather(*(self.embed_one(t) for t in texts)))
        # Fail here, naming the batch, rather than later inside a cosine call.
        assert_uniform_dimension(vectors)
        return vectors

    async def similarity(self, a: str, b: str) -> float:
        va, vb = await self.embed_many([a, b])
        return cosine(va, vb)
