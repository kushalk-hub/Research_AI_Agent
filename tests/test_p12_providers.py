"""P12: one canonical identity for every model id.

Canonicalisation is the single place a model string is interpreted. Everything
downstream — provider dispatch, cache keys, threshold lookup, display — consumes
the canonical form, so no two subsystems can grow different resolution rules.
"""

from __future__ import annotations

import pytest

from rla.config import KNOWN_PROVIDERS, Settings
from rla.errors import ModelResolutionError


def settings(**kw) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **kw)


# -- explicit prefixes --------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("ollama/qwen3:4b", "ollama/qwen3:4b"),
        ("openrouter/ling-3.0-flash-sante:free", "openrouter/ling-3.0-flash-sante:free"),
        ("openai/gpt-4o-mini", "openai/gpt-4o-mini"),
    ],
)
def test_an_explicit_prefix_is_authoritative(model, expected):
    assert settings().canonical_model(model) == expected


# -- bare ids that name their provider ---------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("gpt-4o-mini", "openai/gpt-4o-mini"),
        ("claude-sonnet-4", "anthropic/claude-sonnet-4"),
        ("text-embedding-3-small", "openai/text-embedding-3-small"),
    ],
)
def test_a_bare_id_that_names_its_provider_is_accepted(model, expected):
    assert settings().canonical_model(model) == expected


# -- bare ids that name nothing ----------------------------------------------


def test_an_ambiguous_bare_id_is_refused_before_any_request():
    with pytest.raises(ModelResolutionError) as excinfo:
        settings().canonical_model("qwen3:4b")

    message = str(excinfo.value)
    assert "Ambiguous model id 'qwen3:4b'" in message
    assert "ollama/qwen3:4b" in message, "the error must name the fix"


def test_an_unknown_provider_prefix_is_refused():
    with pytest.raises(ModelResolutionError) as excinfo:
        settings().canonical_model("foo/bar")

    message = str(excinfo.value)
    assert "Unknown provider prefix 'foo'" in message
    assert "gemini" in message and "ollama" in message


def test_an_empty_model_is_refused():
    with pytest.raises(ModelResolutionError):
        settings().canonical_model("")


# -- invariants ---------------------------------------------------------------


def test_canonicalisation_is_idempotent():
    s = settings()
    once = s.canonical_model("ollama/qwen3:4b")
    assert s.canonical_model(once) == once


def test_two_spellings_of_one_model_share_one_identity():
    """Whitespace must not create a second identity: `ollama/qwen3:4b` padded with
    spaces is the same model, so it canonicalises to the same id and therefore the
    same provider, the same cache key, and the same threshold entry."""
    s = settings()
    assert s.canonical_model("  ollama/qwen3:4b  ") == s.canonical_model("ollama/qwen3:4b")


def test_surrounding_whitespace_is_stripped_not_fatal():
    assert settings().canonical_model("  ollama/qwen3:4b  ") == "ollama/qwen3:4b"


def test_the_provider_table_covers_the_backends_that_exist():
    assert {"gemini", "ollama", "openai", "openrouter"} <= KNOWN_PROVIDERS
