"""P12: embeddings as a provider, not a Gemini special case.

`/api/embed` is batched, so 163 concept names is ONE request rather than 163 --
which materially changes how long entity resolution takes when it is local.
"""

from __future__ import annotations

import pytest
import respx

from rla.config import Settings
from rla.llm.embedding_base import EmbeddingDimensionMismatch, assert_uniform_dimension
from rla.llm.factory import build_embedder
from rla.llm.ollama_embedder import OllamaEmbedder
from rla.llm.retry import reset_limiter, reset_spender
from rla.store.cache import CostTracker

OLLAMA = "http://localhost:9999"
http_mock = respx.mock(base_url=OLLAMA, assert_all_called=False)


@pytest.fixture(autouse=True)
def _clean_shared_state():
    reset_limiter()
    reset_spender()
    yield
    reset_limiter()
    reset_spender()


def embedder(tmp_path, model="ollama/nomic-embed-text", **kw) -> OllamaEmbedder:
    settings = Settings(
        _env_file=None, gemini_api_key="k", data_dir=tmp_path,
        ollama_url=OLLAMA, embedding_model=model, llm_rpm=60, **kw,
    )
    return OllamaEmbedder(settings, None, CostTracker())


def test_the_factory_selects_an_embedder_by_provider(tmp_path):
    from rla.llm.embeddings import Embedder

    assert isinstance(
        build_embedder(Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                                embedding_model="ollama/nomic-embed-text")),
        OllamaEmbedder,
    )
    assert isinstance(
        build_embedder(Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                                embedding_model="gemini/gemini-embedding-001")),
        Embedder,
    )


@http_mock
async def test_many_texts_cost_exactly_one_request(tmp_path):
    http_mock.post("/api/embed").respond(
        json={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2] for _ in range(163)]}
    )
    vectors = await embedder(tmp_path).embed_many([f"concept {i}" for i in range(163)])

    assert len(vectors) == 163
    assert len(http_mock.calls) == 1, "embedding must be batched, not one call per text"


@http_mock
async def test_the_dimension_is_measured_not_assumed(tmp_path):
    http_mock.post("/api/embed").respond(json={"embeddings": [[0.1, 0.2, 0.3]]})
    e = embedder(tmp_path)
    assert e.dimensions is None

    assert len(await e.embed_one("a")) == 3
    assert e.dimensions == 3


def test_the_cache_key_is_canonical_and_model_aware(tmp_path):
    """Two models must not share an index; one model reached two ways must."""
    a = embedder(tmp_path, model="ollama/nomic-embed-text")
    assert a.key("same text") == a.key("same text")

    b = embedder(tmp_path, model="ollama/other-embed")
    assert a.key("same text") != b.key("same text")


def test_a_dimension_mismatch_still_raises(tmp_path):
    """The guard that stopped resolution silently scoring every pair 0.0."""
    with pytest.raises(EmbeddingDimensionMismatch):
        assert_uniform_dimension([[0.1, 0.2], [0.1, 0.2, 0.3]])


@http_mock
async def test_an_unknown_embedding_model_names_the_pull_command(tmp_path):
    http_mock.post("/api/embed").respond(404, json={"error": "model 'nope' not found"})

    with pytest.raises(Exception) as excinfo:
        await embedder(tmp_path, model="ollama/nope").embed_one("a")

    assert "ollama pull nope" in str(excinfo.value)
