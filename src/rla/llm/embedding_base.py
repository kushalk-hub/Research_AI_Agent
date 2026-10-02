"""Provider-neutral embedding contract.

`Embedder` was concrete and sat outside `LLMClient`, so nothing about embeddings was
portable. This adds the missing seam.

The important part is not the Protocol -- it is the dimension check. `cosine` used to
return `0.0` for vectors of different lengths, which is the most dangerous possible
behaviour here: swapping the embedding model changes the vector width, every similarity
score silently becomes 0.0, and the entity-resolution tiers that depend on those scores
stop merging anything. The result is indistinguishable from "these concepts really are
unrelated", so the failure is invisible. It now raises.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from rla.llm.errors import EmbeddingDimensionMismatch


@runtime_checkable
class EmbedderClient(Protocol):
    """What a stage may ask of any embedding backend."""

    @property
    def dimensions(self) -> int | None:
        """Observed vector width, or None before the first call.

        Reported so a mismatch can be named rather than merely detected.
        """
        ...

    async def embed_one(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingProvider(Protocol):
    """What entity resolution needs from an embedding backend.

    Declared so the pipeline can be pointed at Gemini or at a local Ollama model by
    configuration alone. `key` is part of the contract rather than an
    implementation detail: the embedding model id is part of the cache identity,
    so vectors from two different models can never be served to, or compared
    with, each other.
    """

    @property
    def model_id(self) -> str:
        """Canonical `provider/model` id, and part of the cache key."""
        ...

    @property
    def dimensions(self) -> int | None:
        """Measured width, or None before the first successful call."""
        ...

    def key(self, text: str) -> str: ...

    async def embed_one(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, with an explicit failure on mismatched dimensions.

    Raising rather than returning 0.0 is the whole point. A zero is a legitimate
    answer for orthogonal vectors; using it to mean "wrong input" conflates "not
    similar" with "broken", and the first is a research result while the second is a
    bug that must be fixed.
    """
    if len(a) != len(b):
        raise EmbeddingDimensionMismatch(
            f"cannot compare vectors of different dimensions: {len(a)} vs {len(b)}. "
            "This usually means the embedding model changed between calls; "
            "re-embed before comparing."
        )
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def assert_uniform_dimension(vectors: Sequence[Sequence[float]]) -> int:
    """Verify a batch shares one dimensionality, returning it.

    Guards `embed_many` before callers compare pairwise, so the failure names the
    offending batch rather than surfacing later inside a cosine call.
    """
    if not vectors:
        return 0
    first = len(vectors[0])
    for index, vector in enumerate(vectors):
        if len(vector) != first:
            raise EmbeddingDimensionMismatch(
                f"batch is not dimensionally uniform: vector {index} has "
                f"{len(vector)} dims, expected {first}"
            )
    return first


def batch_cosine(vectors: Sequence[Sequence[float]]) -> list[float]:
    """Pairwise cosine matrix for a batch, dimension-checked up front."""
    assert_uniform_dimension(vectors)
    return [[cosine(a, b) for b in vectors] for a in vectors]


def describe(vector: Sequence[float]) -> dict[str, Any]:
    """Small diagnostic view of a vector, for `rla doctor` and error messages."""
    norm = math.sqrt(sum(x * x for x in vector)) if vector else 0.0
    return {"dimensions": len(vector), "l2_norm": round(norm, 6)}


__all__ = [
    "EmbedderClient",
    "EmbeddingDimensionMismatch",
    "EmbeddingProvider",
    "assert_uniform_dimension",
    "batch_cosine",
    "cosine",
    "describe",
]
