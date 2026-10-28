"""Adapters exposing one academic-source request per runtime task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rla.config import Settings
from rla.store.cache import Cache


@dataclass
class LiveSourcePool:
    searchers: dict[str, Any]
    client: Any

    async def close(self) -> None:
        await self.client.aclose()


def build_live_source_pool(settings: Settings, cache: Cache, limit: int = 3) -> LiveSourcePool:
    """Build source adapters, returning each source's single-request operation.

    The FODS scheduler invokes these operations separately. This intentionally
    does not call `Acquisition.run()`, whose internal fan-out would hide scheduling.
    """
    from rla.pipeline.acquisition import build_sources

    sources = build_sources(settings, cache)
    preferred = ("semantic_scholar", "openalex", "arxiv", "crossref", "dblp")
    selected: dict[str, Any] = {}
    for name in preferred:
        if name in sources:
            selected[name] = sources[name]
        if len(selected) == limit:
            break
    if len(selected) < 2:
        raise RuntimeError("at least two live academic sources must be enabled")
    client = next(iter(sources.values())).fetcher.client
    return LiveSourcePool(
        searchers={name: source.search for name, source in selected.items()},
        client=client,
    )
