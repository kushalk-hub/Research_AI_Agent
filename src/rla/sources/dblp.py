"""DBLP - bibliographic index for CS/AI, keyless (spec section 3a)."""

from __future__ import annotations

from typing import Any

from rla.models import Paper
from rla.sources.base import HttpSource, normalise_doi


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _flat_text(value: Any) -> str:
    """DBLP wraps single values inconsistently: bare string, {"text": ...}, or a list."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("@type") or "")
    if isinstance(value, list):
        for item in value:
            text = _flat_text(item)
            if text:
                return text
    return ""


class DblpSource(HttpSource):
    name = "dblp"
    base_url = "https://dblp.org/search/publ/api"

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            self.base_url,
            {"q": query, "format": "json", "h": min(limit, 50)},
            prefix=self.name,
        )
        hits = ((payload or {}).get("result") or {}).get("hits") or {}
        return self.collect([h.get("info") or {} for h in _as_list(hits.get("hit"))], limit)

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        dblp_url = raw.get("ee") or raw.get("url") or ""
        dblp_key = raw.get("key") or dblp_url
        year_text = _flat_text(raw.get("year"))
        authors = [
            name
            for name in (
                _flat_text(a.get("text") if isinstance(a, dict) else a) if a else ""
                for a in _as_list((raw.get("authors") or {}).get("author"))
            )
            if name
        ]
        return Paper(
            id=f"dblp:{dblp_key}",
            title=_flat_text(raw.get("title")),
            year=int(year_text) if year_text.isdigit() else None,
            authors=authors,
            abstract="",
            venue=_flat_text(raw.get("venue")),
            doi=normalise_doi(raw.get("doi") or ""),
            url=dblp_url,
            external_ids={"dblp": dblp_key},
        )
