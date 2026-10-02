"""Native Ollama embeddings via the batched `/api/embed` endpoint.

Entity resolution embeds one string per distinct concept name, which is 160-odd
strings for a 30-paper corpus. Ollama's `/api/embed` accepts a list, so that is
ONE request rather than 163 -- the difference between resolution being usable
locally and not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from rla.config import Settings, get_settings
from rla.llm.error_map import normalize
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import CostTracker

_PULL_HINT = "not found"


class OllamaEmbedder:
    """Cache-first batched embeddings from a local Ollama server."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._dimensions: int | None = None

    @property
    def model_id(self) -> str:
        return self.settings.canonical_model(self.settings.embedding_model)

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def _bare(self) -> str:
        model = self.model_id
        return model.split("/", 1)[1] if "/" in model else model

    def key(self, text: str) -> str:
        # The `embed:` namespace is shared with the Gemini embedder on purpose, so
        # the two providers are visibly the same kind of stored artefact.
        return "embed:" + content_hash(self.model_id, text)

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        cached: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            hit = None if self.cache is None else self.cache.get(self.key(text), kind="llm")
            if hit is None:
                pending.append((index, text))
            else:
                cached[index] = [float(v) for v in hit.split(",") if v != ""]

        if pending:
            payload = {"model": self._bare(), "input": [t for _, t in pending]}

            def _invoke() -> Any:
                response = httpx.post(
                    f"{self.settings.ollama_url.rstrip('/')}/api/embed",
                    json=payload, timeout=self.settings.llm_timeout_seconds,
                )
                if response.status_code == 404:
                    raise ProviderInvalidRequest(
                        f"embedding model {self._bare()!r} is not available on the "
                        f"Ollama server. Load it with: ollama pull {self._bare()}"
                    )
                response.raise_for_status()
                return response

            try:
                response = await call_with_retry(
                    _invoke,
                    stage="ollama embed call failed",
                    limiter=self.settings.llm_limiter,
                    max_retries=self.settings.llm_max_retries,
                    spender=self.settings.llm_spender,
                    timeout=self.settings.llm_timeout_seconds,
                )
            except ProviderInvalidRequest:
                raise
            except Exception as exc:
                raise normalize(
                    exc, provider="ollama", model=self.model_id, stage="embedding"
                ) from exc

            vectors = response.json().get("embeddings") or []
            if len(vectors) != len(pending):
                raise ProviderInvalidRequest(
                    f"expected {len(pending)} embeddings from Ollama, got {len(vectors)}"
                )
            for (index, text), vector in zip(pending, vectors, strict=True):
                cached[index] = [float(v) for v in vector]
                if self.cache is not None:
                    self.cache.set(
                        self.key(text), ",".join(str(v) for v in vector), kind="llm"
                    )

        out = [v for v in cached if v is not None]
        if out:
            self._dimensions = len(out[0])
        return out  # type: ignore[return-value]

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed_many([text])
        return vectors[0]
