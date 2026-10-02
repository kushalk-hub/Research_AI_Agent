"""P12: per-stage model overrides from the CLI, and deduplicated doctor probes.

`doctor --llm` sends real, uncached requests, so probing the same resolved model
once per role costs quota and time for no information.
"""

from __future__ import annotations

from rla.cli import _apply_model_overrides, _probe_plan
from rla.config import Settings


def settings(**kw) -> Settings:
    base = {
        "gemini_api_key": "k",
        "fast_model": "ollama/qwen3:4b",
        "strong_model": "ollama/qwen3:4b",
        "structured_model": "ollama/qwen3:4b",
        "answer_model": "gemini/gemini-2.5-flash",
        "embedding_model": "gemini/gemini-embedding-001",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


# -- overrides ----------------------------------------------------------------


def test_an_override_reaches_settings_without_touching_env(tmp_path):
    out = _apply_model_overrides(
        settings(data_dir=tmp_path), "ollama/qwen3:8b", "gemini/gemini-2.5-pro"
    )
    assert out.model_for_structured == "ollama/qwen3:8b"
    assert out.model_for_answer == "gemini/gemini-2.5-pro"


def test_no_override_leaves_the_configuration_untouched(tmp_path):
    original = settings(data_dir=tmp_path)
    out = _apply_model_overrides(original, None, None)
    assert out.model_for_structured == original.model_for_structured
    assert out.model_for_answer == original.model_for_answer


def test_an_override_is_canonicalised(tmp_path):
    """`gemini-2.5-pro` is accepted and stored canonically, so the cache key and
    the threshold lookup see one identity."""
    out = _apply_model_overrides(settings(data_dir=tmp_path), None, "gemini-2.5-pro")
    assert out.model_for_answer == "gemini/gemini-2.5-pro"


def test_an_ambiguous_override_is_refused_loudly(tmp_path):
    from rla.errors import ModelResolutionError

    try:
        _apply_model_overrides(settings(data_dir=tmp_path), "qwen3:4b", None)
    except ModelResolutionError as exc:
        assert "ollama/qwen3:4b" in str(exc)
        return
    raise AssertionError("expected ModelResolutionError")


# -- probe plan ---------------------------------------------------------------


def test_one_model_serving_three_roles_is_probed_once(tmp_path):
    plan = _probe_plan(settings(data_dir=tmp_path))

    text = [p for p in plan if p.kind == "text"]
    by_model = {p.model: p.roles for p in text}
    assert by_model["ollama/qwen3:4b"] == ("structured", "extraction", "resolution")
    assert len([p for p in text if p.model == "ollama/qwen3:4b"]) == 1


def test_distinct_models_are_probed_separately(tmp_path):
    plan = _probe_plan(settings(data_dir=tmp_path))
    models = {p.model for p in plan if p.kind == "text"}
    assert models == {"ollama/qwen3:4b", "gemini/gemini-2.5-flash"}


def test_the_embedding_model_is_a_separate_probe(tmp_path):
    """`/api/embed` is a different endpoint and a different capability, so an
    embedding probe is never satisfied by a text probe."""
    plan = _probe_plan(settings(data_dir=tmp_path))
    embedding = [p for p in plan if p.kind == "embedding"]
    assert [p.model for p in embedding] == ["gemini/gemini-embedding-001"]


def test_a_shared_model_is_probed_once_across_kinds(tmp_path):
    """If the embedding model and a text model were the same id, one probe
    cannot serve both: the capabilities differ."""
    plan = _probe_plan(
        settings(data_dir=tmp_path, embedding_model="ollama/qwen3:4b")
    )
    assert len([p for p in plan if p.model == "ollama/qwen3:4b"]) == 2
