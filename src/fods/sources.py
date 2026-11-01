"""Adapters exposing one academic-source request per runtime task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rla.config import Settings
from rla.store.cache import Cache
from rla.store.rate_limits import RequestAttemptBudget


@dataclass
class LiveSourcePool:
    searchers: dict[str, Any]
    reference_resolvers: dict[str, Any]
    client: Any

    async def close(self) -> None:
        await self.client.aclose()


SOURCE_ORDER = ("semantic_scholar", "openalex", "arxiv", "crossref", "dblp")


def selected_live_source_names(settings: Settings, limit: int) -> list[str]:
    enabled = set(settings.enabled_sources())
    return [name for name in SOURCE_ORDER if name in enabled][:limit]


def build_live_source_pool(
    settings: Settings,
    cache: Cache,
    limit: int = 3,
    *,
    attempt_budget: RequestAttemptBudget | None = None,
) -> LiveSourcePool:
    """Build source adapters, returning each source's single-request operation.

    The FODS scheduler invokes these operations separately. This intentionally
    does not call `Acquisition.run()`, whose internal fan-out would hide scheduling.
    """
    from rla.pipeline.acquisition import build_sources

    sources = build_sources(settings, cache, attempt_budget=attempt_budget)
    selected = {
        name: sources[name]
        for name in selected_live_source_names(settings, limit)
        if name in sources
    }
    if len(selected) < 2:
        raise RuntimeError("at least two live academic sources must be enabled")
    client = next(iter(sources.values())).fetcher.client
    return LiveSourcePool(
        searchers={name: source.search for name, source in selected.items()},
        reference_resolvers={
            name: source.references
            for name, source in selected.items()
            if name in {"semantic_scholar", "openalex"}
            and callable(getattr(source, "references", None))
        },
        client=client,
    )
