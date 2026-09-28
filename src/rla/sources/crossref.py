"""CrossRef - DOI resolution and metadata gap-filling (spec section 3a).

Best DOI authority of the keyless set, and the only one that reliably returns
outgoing reference DOIs, so it backfills citation edges the other sources miss.
"""

from __future__ import annotations

from typing import Any

from rla.models import Paper
from rla.sources.base import HttpSource, clean_markup, normalise_doi


def _year_from(item: dict[str, Any]) -> int | None:
    for field_name in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(field_name) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


class CrossrefSource(HttpSource):
    name = "crossref"
    base_url = "https://api.crossref.org/works"

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            self.base_url,
            {"query.bibliographic": query, "rows": min(limit, 50)},
            prefix=self.name,
        )
        items = ((payload or {}).get("message") or {}).get("items") or []
        return self.collect(items, limit)

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        doi = normalise_doi(raw.get("DOI") or "")
        if not doi:
            return None
        titles = raw.get("title") or []
        containers = raw.get("container-title") or []
        authors = [
            " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
            for a in (raw.get("author") or [])
        ]
        references = [
            normalise_doi(str(r.get("DOI") or ""))
            for r in (raw.get("reference") or [])
            if isinstance(r, dict) and r.get("DOI")
        ]
        return Paper(
            id=f"doi:{doi}",
            title=titles[0] if titles else "",
            year=_year_from(raw),
            authors=[a for a in authors if a],
            abstract=clean_markup(raw.get("abstract") or ""),
            venue=containers[0] if containers else "",
            doi=doi,
            url=raw.get("URL") or f"https://doi.org/{doi}",
            external_ids={"crossref": doi},
            citation_count=int(raw.get("is-referenced-by-count") or 0),
            references=[r for r in references if r],
        )
