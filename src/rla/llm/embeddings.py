"""Concept embeddings for entity resolution (spec section 9).

Uses the Gemini embedding endpoint so no local torch install is needed.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

from rla.config import Settings, get_settings
from rla.llm.base import LLMError, record_usage
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import Cache, CostTracker


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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

    @property
    def client(self) -> object:
        if self._client is None:
            if not self.settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set")
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def _key(self, text: str) -> str:
        return "embed:" + content_hash(self.settings.embedding_model, text)

    async def embed_one(self, text: str) -> list[float]:
        cache_key = self._key(text)
        if self.cache is not None:
            hit = self.cache.get_json(cache_key, kind="embed")
            if hit is not None:
                return list(hit)

        def _invoke() -> object:
            return self.client.models.embed_content(
                model=self.settings.embedding_model, contents=text
            )

        response = await call_with_retry(
            _invoke,
            stage="embedding failed",
            limiter=self.settings.llm_limiter,
            max_retries=self.settings.llm_max_retries,
            spender=self.settings.llm_spender,
        )

        record_usage(self.tracker, "embed", response)
        vector = list(response.embeddings[0].values)
        if self.cache is not None:
            self.cache.set_json(cache_key, vector, kind="embed")
        return vector

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return list(await asyncio.gather(*(self.embed_one(t) for t in texts)))

    async def similarity(self, a: str, b: str) -> float:
        va, vb = await self.embed_many([a, b])
        return cosine(va, vb)
