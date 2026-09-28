"""SerpApi Google Scholar - optional supplementary pass (spec section 3a).

Disabled unless SERPAPI_API_KEY is set. Catches recent preprints and grey
literature that citation indexes miss, at the cost of a citation graph it does
not provide, so it contributes candidates only.
"""

from __future__ import annotations

from typing import Any

from rla.models import Paper, content_hash
from rla.sources.base import HttpSource, clean_markup, guess_year
from rla.store.cache import Fetcher


class SerpApiSource(HttpSource):
    name = "serpapi"
    base_url = "https://serpapi.com/search.json"
    requires_key = True

    def __init__(self, fetcher: Fetcher, api_key: str) -> None:
        super().__init__(fetcher)
        self.api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            self.base_url,
            {
                "engine": "google_scholar",
                "q": query,
                "num": min(limit, 20),
                "api_key": self.api_key,
            },
            prefix=self.name,
        )
        return self.collect((payload or {}).get("organic_results") or [], limit)

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        title = raw.get("title") or ""
        if not title:
            return None
        info = raw.get("publication_info") or {}
        summary = info.get("summary") or ""
        return Paper(
            id=f"gs:{content_hash(raw.get('link') or title)[:16]}",
            title=title,
            year=guess_year(summary),
            authors=[a.get("name", "") for a in (info.get("authors") or []) if a.get("name")],
            abstract=clean_markup(raw.get("snippet") or ""),
            venue=summary,
            url=raw.get("link") or "",
            external_ids={},
        )
