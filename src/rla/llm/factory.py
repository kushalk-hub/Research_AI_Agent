"""Construction of the provider-routing stack from configuration.

The audit found `GeminiClient` named explicitly at three call sites (`cli.py:78, 173,
396`) with no factory, which meant the Protocol's claim that adding a provider needs
"one class plus a key, no call sites change" was slightly overstated: those three lines
still had to be edited. This factory is the missing piece (ADR-001).

Everything provider-specific is decided here and nowhere else, so `RLA_LLM_PROVIDER`
is the only thing that selects a backend.
"""

from __future__ import annotations

from typing import Any

from rla.config import Settings, get_settings
from rla.llm.embedding_base import EmbeddingProvider
from rla.llm.embeddings import Embedder
from rla.llm.router import ProviderRouter
from rla.store.cache import Cache, CostTracker

#: Backend names accepted by `RLA_LLM_PROVIDER`.
BACKENDS = ("gemini", "litellm", "ollama")


def build_backend(
    settings: Settings,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> Any:
    """Instantiate the provider-routing stack.

    Always a `MultiBackend`: one code path regardless of how many providers a
    configuration actually uses, and the concrete backends behind it are built
    lazily on first use. `cache` and `tracker` are threaded through because the
    backend that performs the call is the one that meters it -- a backend holding
    its own empty tracker makes the cost report read $0.00 regardless of what was
    spent, which is the silent-zero defect this migration exists to eliminate.
    """
    choice = (settings.llm_provider or "gemini").strip().lower()
    if choice not in BACKENDS:
        raise ValueError(
            f"unknown RLA_LLM_PROVIDER {settings.llm_provider!r}; expected one of "
            f"{', '.join(BACKENDS)}"
        )
    from rla.llm.multi import MultiBackend

    return MultiBackend(settings, cache, tracker)


def build_client(
    settings: Settings | None = None,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> ProviderRouter | None:
    """Build the router every stage receives, or None when no key is available.

    Returning None for the keyless case preserves the existing degrade-mode
    behaviour: the orchestrator turns a None client into `pending` events and the
    keyless sources still produce a corpus.
    """
    settings = settings or get_settings()
    # A client exists when *any* configured provider is usable, not only when the
    # Gemini key is present. Keying this on one credential would make a fully
    # local pipeline still require a Gemini key, and the orchestrator would read
    # the resulting None as degrade mode.
    if not _has_usable_provider(settings):
        return None
    return ProviderRouter(build_backend(settings, cache, tracker), settings, cache, tracker)


def _has_usable_provider(settings: Settings) -> bool:
    """Whether at least one configured model can actually be served.

    A Gemini model needs the Gemini key. A local Ollama model needs no credential
    at all, only a running server -- so a missing key must not disable it.
    """
    try:
        models = (
            settings.model_for_structured,
            settings.model_for_answer,
            settings.fast_model,
        )
    except Exception:
        return False
    for model in models:
        try:
            provider = settings.canonical_model(model).split("/", 1)[0]
        except Exception:
            continue
        if provider == "ollama":
            return True
        if provider == "gemini" and settings.gemini_api_key:
            return True
        if provider not in ("ollama", "gemini") and settings.gemini_api_key:
            # LiteLLM providers read their own credential; the OpenRouter key is
            # configured here, so its presence is the signal we have.
            return True
    return False


def build_embedder(
    settings: Settings | None = None,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> EmbeddingProvider | None:
    """Build the embedder for the configured embedding model's provider.

    Returns None when no provider is usable. Note this is deliberately *not* keyed
    on the Gemini credential: with a local embedding model configured, a fully
    local pipeline must not require a Gemini key at all.
    """
    settings = settings or get_settings()
    model = settings.canonical_model(settings.embedding_model)
    provider = model.split("/", 1)[0]
    if provider == "ollama":
        from rla.llm.ollama_embedder import OllamaEmbedder

        return OllamaEmbedder(settings, cache, tracker)
    if not settings.gemini_api_key:
        return None
    return Embedder(settings, cache, tracker)


__all__ = ["BACKENDS", "build_backend", "build_client", "build_embedder"]
