"""OpenAlex - free open complement to Semantic Scholar (spec section 3a).

Supplies citation edges (`referenced_works`) and built-in concept tags that can
seed the concept vocabulary in P3.
"""

from __future__ import annotations

from typing import Any

from rla.models import Paper
from rla.sources.base import HttpSource, normalise_doi, reconstruct_abstract

OPENALEX = "https://api.openalex.org"


class OpenAlexSource(HttpSource):
    name = "openalex"
    base_url = OPENALEX

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            f"{self.base_url}/works",
            {"search": query, "per-page": min(limit, 50)},
            prefix=self.name,
        )
        return self.collect((payload or {}).get("results") or [], limit)

    async def _filter(self, filter_expr: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            f"{self.base_url}/works",
            {"filter": filter_expr, "per-page": min(limit, 50)},
            prefix=f"{self.name}:graph",
        )
        return self.collect((payload or {}).get("results") or [], limit)

    async def references(self, paper: Paper, limit: int) -> list[Paper]:
        """`cited_by` selects the works this paper references."""
        work_id = paper.external_ids.get("openalex")
        if not work_id:
            return []
        return await self._filter(f"cited_by:{work_id}", limit)

    async def citations(self, paper: Paper, limit: int) -> list[Paper]:
        """`cites` selects the works that reference this paper."""
        work_id = paper.external_ids.get("openalex")
        if not work_id:
            return []
        return await self._filter(f"cites:{work_id}", limit)

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        openalex_id = raw.get("id") or ""
        short_id = openalex_id.rsplit("/", 1)[-1] if openalex_id else ""
        location = raw.get("primary_location") or {}
        source = location.get("source") or {}
        authors = [
            ((a.get("author") or {}).get("display_name") or "")
            for a in (raw.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]
        concepts = [
            c.get("display_name", "") for c in (raw.get("concepts") or []) if c.get("display_name")
        ]
        return Paper(
            id=short_id,
            title=raw.get("display_name") or raw.get("title") or "",
            year=raw.get("publication_year"),
            authors=authors,
            abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
            venue=source.get("display_name") or "",
            doi=normalise_doi(raw.get("doi") or ""),
            url=location.get("landing_page_url") or openalex_id,
            external_ids={"openalex": short_id},
            citation_count=int(raw.get("cited_by_count") or 0),
            references=[r.rsplit("/", 1)[-1] for r in (raw.get("referenced_works") or [])],
            citations=[c.rsplit("/", 1)[-1] for c in (raw.get("cited_by") or [])],
            keywords=concepts[:5],
        )
