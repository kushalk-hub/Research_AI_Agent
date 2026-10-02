"""P12: dispatch each model id to the provider that owns it.

`MultiBackend` is a backend, not a router. `ProviderRouter` keeps every policy
it owns; this only answers "who serves this model". Because `_dispatch` already
loops candidates and calls `run(model=candidate)`, resolving per candidate is
what makes cross-provider fallback work with no router change.
"""

from __future__ import annotations

import pytest
import respx
from pydantic import BaseModel, Field

from rla.config import Settings
from rla.errors import ModelResolutionError
from rla.llm.factory import build_backend
from rla.llm.gemini import GeminiClient
from rla.llm.multi import MultiBackend
from rla.llm.ollama_backend import OllamaBackend


class Out(BaseModel):
    value: str = Field(default="ok")


#: Module-level router shared by decorator and route registration: `respx.post`
#: registers on the global default router, which is a different object from a
#: fresh `@respx.mock(...)` decorator, so mixing the two silently leaves the
#: request unmatched.
http_mock = respx.mock(base_url="http://localhost:11434", assert_all_called=False)


def multi(tmp_path, **kw) -> MultiBackend:
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        llm_provider="ollama",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        **kw,
    )
    return MultiBackend(settings, None, None)


# -- resolution ---------------------------------------------------------------


def test_each_model_reaches_the_backend_that_owns_it(tmp_path):
    m = multi(tmp_path)
    assert isinstance(m.backend_for("gemini/gemini-2.5-flash"), GeminiClient)
    assert isinstance(m.backend_for("ollama/qwen3:4b"), OllamaBackend)
    assert m.backend_for("openrouter/ling-3.0-flash-sante:free").name == "litellm"


def test_the_canonical_id_decides_the_backend_not_the_default(tmp_path):
    """`llm_provider` is the default for provider-agnostic ids only."""
    m = multi(tmp_path)
    assert m.provider_for("gemini/gemini-2.5-flash") == "gemini"
    assert m.provider_for("ollama/qwen3:4b") == "ollama"
    assert m.provider_for("gpt-4o-mini") == "openai"


def test_an_unknown_provider_resolves_to_nothing_rather_than_a_guess(tmp_path):
    with pytest.raises(ModelResolutionError):
        multi(tmp_path).provider_for("foo/bar")


# -- laziness -----------------------------------------------------------------


def test_a_backend_is_constructed_only_when_a_model_needs_it(tmp_path):
    m = multi(tmp_path)
    assert m.live_backends() == {}

    m.backend_for("ollama/qwen3:4b")
    assert set(m.live_backends()) == {"ollama"}

    m.backend_for("gemini/gemini-2.5-flash")
    assert set(m.live_backends()) == {"ollama", "gemini"}


# -- delegation ---------------------------------------------------------------


def test_capability_is_delegated_to_the_owning_backend(tmp_path):
    m = multi(tmp_path)
    assert m.supports("ollama/qwen3:4b", "supports_structured_output") is True
    assert m.supports("ollama/nomic-embed-text", "supports_structured_output") is False


@http_mock
async def test_a_structured_call_reaches_the_owning_backend(tmp_path):
    """Delegation, not a live-server test: the response is mocked, so this proves
    the call was routed to the Ollama backend rather than anywhere else."""
    import json as _json

    http_mock.post("/api/generate").respond(
        json={
            "model": "qwen3:4b",
            "response": _json.dumps({"value": "from-ollama"}),
            "done": True,
            "eval_count": 3,
            "prompt_eval_count": 5,
        }
    )
    m = multi(tmp_path)
    result, _ = await m.generate_structured(
        "p", Out, model="ollama/qwen3:4b", stage="extraction"
    )
    assert isinstance(result, Out)
    assert result.value == "from-ollama"
    assert set(m.live_backends()) == {"ollama"}


# -- cross-provider fallback --------------------------------------------------


async def test_a_fault_on_one_provider_fails_over_to_another(tmp_path, monkeypatch):
    """Primary fails on Ollama, the router selects the Gemini fallback, and the
    facade resolves each candidate to its own backend. No fallback logic lives in
    `MultiBackend` itself -- it only answers "who serves this model"."""
    from rla.llm.errors import ProviderServerError
    from rla.llm.router import ProviderRouter

    calls: list[tuple[str, str]] = []

    class FakeOllama:
        name = "ollama"

        def supports(self, model, capability):
            return True

        async def generate_text(self, prompt, *, model, temperature, stage):
            calls.append(("ollama", model))
            raise ProviderServerError("ollama is down")

    class FakeGemini:
        name = "gemini"

        def supports(self, model, capability):
            return True

        async def generate_text(self, prompt, *, model, temperature, stage):
            calls.append(("gemini", model))
            return "text from gemini", None

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        fallback_models="gemini/gemini-2.5-flash",
    )
    facade = MultiBackend(settings, None, None)
    monkeypatch.setattr(facade, "_backends", {"ollama": FakeOllama(), "gemini": FakeGemini()})
    router = ProviderRouter(facade, settings)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from gemini"
    assert calls == [("ollama", "ollama/qwen3:4b"), ("gemini", "gemini/gemini-2.5-flash")]
    assert router.fallbacks, "the router must record the failover it performed"


# -- factory ------------------------------------------------------------------


def test_the_factory_builds_the_facade(tmp_path):
    settings = Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                        raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph")
    assert isinstance(build_backend(settings), MultiBackend)


def test_an_unknown_llm_provider_is_still_a_configuration_error(tmp_path):
    settings = Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                        raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph",
                        llm_provider="nonsense")
    with pytest.raises(ValueError, match="RLA_LLM_PROVIDER"):
        build_backend(settings)
