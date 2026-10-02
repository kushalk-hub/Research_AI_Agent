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
    if not settings.gemini_api_key:
        return None
    return ProviderRouter(build_backend(settings, cache, tracker), settings, cache, tracker)


def build_embedder(
    settings: Settings | None = None,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> Embedder | None:
    """Build the embedder, or None without a key.

    Only the direct Gemini embedder is wired for now. A LiteLLM embedding backend is
    deliberately not stubbed in: half-implemented embedding routing would be worse
    than none, because a dimension mismatch is exactly the failure that must not
    appear silently. See the migration plan's open questions.
    """
    settings = settings or get_settings()
    if not settings.gemini_api_key:
        return None
    return Embedder(settings, cache, tracker)


__all__ = ["BACKENDS", "build_backend", "build_client", "build_embedder"]
