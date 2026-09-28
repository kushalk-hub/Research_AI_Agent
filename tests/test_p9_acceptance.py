"""Acceptance criteria A1-A8 from docs/llm_provider_migration_plan.md.

These assert the *architecture* properties, as opposed to test_p9_provider_routing.py
which asserts routing behaviour. A1 in particular is a structural guard: it is what
stops provider SDK syntax from leaking back into the pipeline.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import BaseModel, Field

from rla.config import Settings
from rla.llm.embeddings import Embedder
from rla.llm.factory import build_backend, build_client, build_embedder
from rla.llm.gemini import GeminiClient
from rla.llm.router import ProviderRouter
from rla.store.cache import Cache, CostTracker

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "rla"

#: Modules allowed to import a provider SDK. Everything else must go through the
#: Protocol, which is the entire point of ADR-001.
PROVIDER_SDKS = ("google.genai", "google import genai", "litellm", "openai", "anthropic")

#: The provider implementation layer, where SDK imports belong.
ADAPTER_MODULES = ("llm/gemini.py", "llm/litellm_backend.py", "llm/embeddings.py")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


# ---------------------------------------------------------------------------
# A1: no pipeline module may import a provider SDK
# ---------------------------------------------------------------------------


def _provider_sdk_imports(path: pathlib.Path) -> list[str]:
    """Provider-SDK imports found in a module, by real AST inspection.

    Text matching would flag the *docstrings* that discuss `google.genai` and
    `litellm`, which is exactly the kind of false positive that gets a
    structural guard deleted. Imports are resolved from the AST instead.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            root = module.split(".")[0]
            if root in ("google", "litellm", "openai", "anthropic", "cohere", "ollama"):
                # `from rla.llm...` is internal; only third-party roots count.
                found.append(module)
    return found


def test_a1_no_pipeline_module_imports_a_provider_sdk():
    """A1: provider SDK syntax must not reach the pipeline stages.

    This is the invariant that makes a provider swap a configuration change. If
    `from google import genai` ever appears in a stage, the abstraction has been
    bypassed and the swap becomes a code change again.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("llm/"):
            continue
        for module in _provider_sdk_imports(path):
            offenders.append(f"{rel}: {module}")
    assert not offenders, f"provider SDK imported outside llm/: {offenders}"


def test_a1_provider_sdks_are_confined_to_the_adapter_layer():
    """A1: the SDKs may appear under `llm/`, and only where a backend lives."""
    allowed = {pathlib.Path(p).name for p in ADAPTER_MODULES}
    for path in sorted((SRC / "llm").rglob("*.py")):
        imports = _provider_sdk_imports(path)
        if not imports:
            continue
        assert path.name in allowed, f"{path.name} imports a provider SDK: {imports}"


def test_a1_the_litellm_backend_imports_litellm_lazily_not_at_module_scope():
    """A1: `litellm` is an optional extra, so a top-level import would break
    the default install for everyone who does not use routing."""
    backend = (SRC / "llm" / "litellm_backend.py").read_text(encoding="utf-8")
    tree = ast.parse(backend)
    for node in tree.body:
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        assert not any(m.split(".")[0] == "litellm" for m in modules), (
            "litellm must be imported inside a function, not at module scope"
        )


def test_a1_the_cli_builds_through_the_factory_not_a_concrete_client():
    """A1: the CLI must not name a provider implementation directly."""
    cli = (SRC / "cli.py").read_text(encoding="utf-8")
    assert "GeminiClient" not in cli
    assert "build_client" in cli


def test_a1_the_orchestrator_constructs_nothing_provider_specific():
    orchestrator = (SRC / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    assert "GeminiClient" not in orchestrator
    assert "build_embedder" in orchestrator


# ---------------------------------------------------------------------------
# Factory / provider swap
# ---------------------------------------------------------------------------


def test_a8_selecting_a_provider_is_configuration_only(tmp_path):
    """A8: change the provider, change no code."""
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    assert isinstance(build_backend(settings), GeminiClient)

    settings.llm_provider = "litellm"
    backend = build_backend(settings)
    assert backend.name == "litellm"
    assert not isinstance(backend, GeminiClient)


def test_an_unknown_provider_is_a_configuration_error_not_a_silent_default(tmp_path):
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        llm_provider="nonsense",
    )
    with pytest.raises(ValueError, match="RLA_LLM_PROVIDER"):
        build_backend(settings)


def test_the_keyless_case_still_degrades_rather_than_raising(tmp_path):
    """Degrade mode is a product feature: acquisition works with no key."""
    settings = Settings(
        gemini_api_key="",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    assert build_client(settings) is None
    assert build_embedder(settings) is None


def test_the_factory_returns_a_router_satisfying_the_protocol(tmp_path):
    """The object stages receive must satisfy the Protocol they are typed against."""
    from rla.llm.base import LLMClient

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    client = build_client(settings, Cache(tmp_path / "c.db"), CostTracker())
    assert isinstance(client, ProviderRouter)
    assert isinstance(client, LLMClient)


# ---------------------------------------------------------------------------
# A2: the four production schemas validate
# ---------------------------------------------------------------------------


def a2_schema_cases() -> list[tuple[str, type[BaseModel]]]:
    from rla.pipeline.extraction import PaperFacts
    from rla.pipeline.query_expansion import QuerySet
    from rla.pipeline.resolve import Verdict
    from rla.pipeline.scoring import ScoreSet

    return [
        ("QuerySet", QuerySet),
        ("ScoreSet", ScoreSet),
        ("PaperFacts", PaperFacts),
        ("Verdict", Verdict),
    ]


def test_a2_every_production_schema_is_a_valid_json_schema():
    """The contract the router's capability gate protects must be expressible."""
    for name, schema in a2_schema_cases():
        json_schema = schema.model_json_schema()
        assert json_schema.get("type") == "object", name
        assert "properties" in json_schema, name


def test_a2_the_gemini_backend_declares_structured_support_for_text_models(tmp_path):
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    backend = GeminiClient(settings)
    assert backend.supports(settings.model_for_structured, "supports_structured_output")
    # The embedding model is not a text model and must not be offered for schema work.
    assert not backend.supports(settings.embedding_model, "supports_structured_output")


# ---------------------------------------------------------------------------
# A3/A4: streaming and embeddings
# ---------------------------------------------------------------------------


async def test_a3_the_router_streams_every_chunk(tmp_path):
    from tests.test_p9_provider_routing import FakeBackend

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    router = ProviderRouter(FakeBackend(), settings, Cache(tmp_path / "c.db"), CostTracker())
    chunks = [c async for c in router.stream_text("x", stage="answer")]
    assert chunks == ["one ", "two ", "three"]


async def test_a3_the_pipeline_answer_stage_consumes_a_stream(tmp_path):
    """The answer stage must still work against the Protocol-shaped client."""
    from rla.models import Concept, EdgeType, Paper, Relation, RelationType
    from rla.pipeline.answer import answer_question
    from rla.store.graph_store import build_graph

    class StreamingLLM:
        async def stream_text(self, prompt, *, model=None, temperature=0.0, stage="llm"):
            yield "GAT was proposed in "
            yield "2018 [P1]."

    paper = Paper(id="p1", title="Graph Attention Networks", year=2018)
    relation = Relation(
        source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES, relation=None
    )
    graph, _ = build_graph(
        [paper],
        [Concept(id="c:gat", name="graph attention networks", first_seen_year=2018)],
        [relation],
    )
    del EdgeType, RelationType  # imported for the schema vocabulary only

    events = [e async for e in answer_question(graph, "how did GAT evolve?", StreamingLLM())]
    deltas = [e.message for e in events if e.kind == "delta"]
    assert deltas, "expected streamed answer chunks"


async def test_a4_embeddings_are_measured_and_reported(tmp_path):
    """A4: the embedder must expose its dimensionality, not hide it."""
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    embedder = Embedder(settings, Cache(tmp_path / "c.db"), CostTracker())
    assert embedder.dimensions is None  # unknown until the first real call

    class FakeResponse:
        embeddings = [type("E", (), {"values": [0.1, 0.2, 0.3]})()]

    embedder._client = type("C", (), {"models": type("M", (), {"embed_content": staticmethod(
        lambda model, contents: FakeResponse())})()})()
    vector = await embedder.embed_one("graph attention networks")

    assert len(vector) == 3
    assert embedder.dimensions == 3


async def test_a4_embedding_cache_keys_are_model_aware(tmp_path):
    """A vector from one model must never be served to another."""
    from rla.models import content_hash

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        embedding_model="model-a",
    )
    embedder = Embedder(settings, Cache(tmp_path / "c.db"), CostTracker())
    key_a = embedder._key("same text")

    settings.embedding_model = "model-b"
    key_b = embedder._key("same text")
    assert key_a != key_b
    del content_hash


# ---------------------------------------------------------------------------
# A6: cache
# ---------------------------------------------------------------------------


async def test_a6_a_cache_hit_prevents_any_provider_call(tmp_path):
    """A6 / PLAN.md P1 gate: a re-run must cost zero network."""
    from rla.llm.gemini import GeminiClient

    calls: list[str] = []

    class CountingModels:
        def generate_content(self, **kwargs):
            calls.append("generate_content")

            class Response:
                text = '{"value": "ok"}'
                usage_metadata = type(
                    "U", (), {"prompt_token_count": 5, "candidates_token_count": 2}
                )()

            return Response()

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    cache = Cache(tmp_path / "c.db")
    client = GeminiClient(settings, cache, CostTracker())
    client._client = type("C", (), {"models": CountingModels()})()

    class Sch(BaseModel):
        value: str = Field(default="ok")

    first, response = await client.generate_structured("p", Sch, stage="extraction")
    assert isinstance(first, Sch)
    assert calls == ["generate_content"], "first call should reach the provider"
    assert response is not None

    # Second call must be served entirely from the cache.
    second, cached_response = await client.generate_structured("p", Sch, stage="extraction")
    assert second == first
    assert calls == ["generate_content"], "a cache hit must not call the provider"
    assert cached_response is None, "a cache hit has no provider response to meter"

    # And the same holds for streaming: the second identical call is a pure
    # cache replay, with no provider call at all.
    class StreamChunk:
        def __init__(self, text):
            self.text = text

    class Models:
        def __init__(self):
            self.stream_calls = 0

        def generate_content_stream(self, **kwargs):
            self.stream_calls += 1
            return iter([StreamChunk("a"), StreamChunk("b")])

    models = Models()
    client._client = type("C", (), {"models": models})()

    first_pass = [c async for c in client.stream_text("prompt", stage="answer")]
    assert "".join(first_pass) == "ab"
    assert models.stream_calls == 1

    # A cached stream is replayed as a single chunk, which the answer stage
    # handles identically (it joins chunks and validates citations per chunk).
    second_pass = [c async for c in client.stream_text("prompt", stage="answer")]
    assert "".join(second_pass) == "ab"
    assert models.stream_calls == 1, "a cached stream must not call the provider"
    cache.close()


async def test_a3_streaming_usage_is_metered_from_the_final_chunk(tmp_path):
    """A3: the answer stage used to contribute zero tokens to the cost report.

    The audit found `record_usage` was never called from `stream_text`, so the
    only consumer of the strong model was invisible in the cost summary and
    reported spend was a lower bound.
    """
    from rla.llm.gemini import GeminiClient

    class Chunk:
        def __init__(self, text, usage=None):
            self.text = text
            if usage is not None:
                self.usage_metadata = usage

    class StreamingModels:
        def generate_content_stream(self, **kwargs):
            return iter(
                [
                    Chunk("one ", type("U", (), {"prompt_token_count": 11,
                                                "candidates_token_count": 4})()),
                    Chunk("two "),
                    Chunk("three", type("U", (), {"prompt_token_count": 11,
                                                  "candidates_token_count": 9})()),
                ]
            )

    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    tracker = CostTracker()
    client = GeminiClient(settings, None, tracker)
    client._client = type("C", (), {"models": StreamingModels()})()

    chunks = [c async for c in client.stream_text("p", stage="answer")]

    assert chunks == ["one ", "two ", "three"]
    report = tracker.to_dict(settings.strong_model)
    assert report["calls"] == 1
    assert report["input_tokens"] == 11
    assert report["output_tokens"] == 9  # from the usage-bearing final chunk
    assert report["estimated_usd"] is not None
    assert report["cost_status"] == "ok"


# ---------------------------------------------------------------------------
# A7: cost
# ---------------------------------------------------------------------------


def test_a7_every_default_model_is_priced():
    """A7: a configured model with no rate would silently understate spend."""
    from rla.store.cache import price_for

    settings = Settings()
    for model in (
        settings.fast_model,
        settings.strong_model,
        settings.embedding_model,
        settings.model_for_structured,
        settings.model_for_answer,
    ):
        assert price_for(model) is not None, model


def test_a7_router_describes_its_own_configuration(tmp_path):
    settings = Settings(
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    router = ProviderRouter(GeminiClient(settings), settings)
    described = router.describe()
    assert described["backend"] == "gemini"
    assert described["structured_model"] == settings.model_for_structured
    assert described["answer_model"] == settings.model_for_answer
    assert "fallback_chain" in described
    assert described["timeout_seconds"] == settings.llm_timeout_seconds
