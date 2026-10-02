"""P12: the native Ollama text backend.

The reason this exists is a measured 12x penalty: routing Ollama through
LiteLLM's OpenAI-compatible route costs ~4096 prompt tokens because that route
implements structured output by prepending format instructions, while the native
route grammar-constrains the same schema for ~662 tokens.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from rla.config import Settings
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.ollama_backend import OllamaBackend
from rla.llm.retry import reset_limiter, reset_spender
from rla.models import Paper
from rla.pipeline.extraction import PaperFacts, build_prompt
from rla.store.cache import CostTracker

OLLAMA = "http://localhost:9999"

#: Module-level router, usable both as a decorator (`@httpx_mock`) and for
#: inspecting what was sent via `httpx_mock.calls[i].request`. respx 0.23 has no
#: `add_handler` and no `get_requests`: a dynamic body is registered with
#: `httpx_mock.post(...).mock(side_effect=fn)`.
httpx_mock = respx.mock(base_url=OLLAMA, assert_all_called=False)


@pytest.fixture(autouse=True)
def _clean_shared_state():
    reset_limiter()
    reset_spender()
    yield
    reset_limiter()
    reset_spender()


def backend(tmp_path, **kw) -> OllamaBackend:
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        ollama_url=OLLAMA,
        llm_rpm=60,
        **kw,
    )
    return OllamaBackend(settings, None, CostTracker())


def test_capability_is_reported_by_the_backend(tmp_path):
    b = backend(tmp_path)
    assert b.supports("ollama/qwen3:4b", "supports_structured_output") is True
    # An embedding model is not a text model and must never be offered for schema work.
    assert b.supports("ollama/nomic-embed-text", "supports_structured_output") is False
    assert b.supports("ollama/qwen3:4b", "some_other_capability") is False


@httpx_mock
async def test_structured_output_is_grammar_constrained_not_prompt_engineered(tmp_path):
    """The regression guard for the 12x penalty.

    `format` carries the schema as a grammar constraint. If the prompt also grew,
    we would be back to the prefill bloat that made this route 12x slower.
    """
    paper = Paper(id="p1", title="Graph Attention Networks", year=2018,
                  abstract="We propose Graph Attention Networks, a novel attention "
                           "architecture for graph-structured data.")
    prompt = build_prompt(paper)
    body = PaperFacts.model_json_schema()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "response": json.dumps({
                    "summary": "Proposes GAT.",
                    "concepts": [
                        {"name": "Graph Attention Networks", "description": "d",
                         "role": "introduces"}
                    ],
                    "relation": "extends",
                    "relation_target": "message passing",
                }),
                "done": True,
                "eval_count": 30,
                "prompt_eval_count": 662,
            },
        )

    httpx_mock.post("/api/generate").mock(side_effect=handler)

    # The backend contract returns `(value, response)`; the router unwraps it.
    # Calling the backend directly means unpacking here.
    facts, _response = await backend(tmp_path).generate_structured(
        prompt, PaperFacts, model="ollama/qwen3:4b", stage="extraction"
    )

    assert isinstance(facts, PaperFacts)
    assert facts.concepts[0].name == "Graph Attention Networks"

    sent = json.loads(httpx_mock.calls[0].request.content)
    assert sent["format"] == body, "the schema must ride in `format`"
    assert sent["prompt"] == prompt, "the prompt must not be rewritten"
    assert sent["stream"] is False
    assert sent["think"] is False


@httpx_mock
async def test_thinking_can_be_switched_on(tmp_path):
    httpx_mock.post("/api/generate").respond(
        json={"response": "hi", "done": True, "prompt_eval_count": 1, "eval_count": 1}
    )
    await backend(tmp_path, ollama_think=True).generate_text(
        "p", model="ollama/qwen3:4b", stage="doctor"
    )
    assert json.loads(httpx_mock.calls[0].request.content)["think"] is True


@httpx_mock
async def test_an_unknown_model_names_the_pull_command(tmp_path):
    httpx_mock.post("/api/generate").respond(404, json={"error": "model 'nope:9b' not found"})

    with pytest.raises(ProviderInvalidRequest) as excinfo:
        await backend(tmp_path).generate_text(
            "p", model="ollama/nope:9b", stage="doctor"
        )

    message = str(excinfo.value)
    assert "ollama pull nope:9b" in message
    assert OLLAMA in message


@httpx_mock
async def test_streaming_chunks_join_into_the_non_streamed_answer(tmp_path):
    httpx_mock.post("/api/generate").respond(
        json={"response": "one two three", "done": True,
              "prompt_eval_count": 1, "eval_count": 3}
    )
    chunks = [
        c async for c in backend(tmp_path).stream_text(
            "p", model="ollama/qwen3:4b", stage="answer"
        )
    ]
    assert "".join(chunks) == "one two three"
    assert json.loads(httpx_mock.calls[0].request.content)["stream"] is True


@httpx_mock
async def test_every_call_goes_through_the_shared_retry_layer(tmp_path):
    """ADR-003: exactly one retry layer, owned by `call_with_retry`."""
    httpx_mock.post("/api/generate").respond(503, json={"error": "unavailable"})

    from rla.llm.errors import ProviderServerError

    with pytest.raises(ProviderServerError):
        await backend(tmp_path).generate_text("p", model="ollama/qwen3:4b", stage="doctor")
