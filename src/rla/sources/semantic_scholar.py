"""Semantic Scholar Graph API - primary source (spec section 3a).

Also the only adapter that exposes a full citation graph, so it drives
snowball sampling. Anonymous access is throttled to roughly 1 request/second,
hence `min_interval`.
"""

from __future__ import annotations

from typing import Any

from rla.models import Paper
from rla.sources.base import HttpSource, normalise_doi

FIELDS = ",".join(
    [
        "paperId",
        "externalIds",
        "title",
        "abstract",
        "year",
        "authors",
        "venue",
        "citationCount",
        "referenceCount",
        "openAccessPdf",
        "references.paperId",
        "citations.paperId",
    ]
)


class SemanticScholarSource(HttpSource):
    name = "semantic_scholar"
    base_url = "https://api.semanticscholar.org/graph/v1"
    min_interval = 1.1

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_json(
            f"{self.base_url}/paper/search",
            {"query": query, "limit": min(limit, 100), "fields": FIELDS},
            prefix=self.name,
        )
        return self.collect((payload or {}).get("data") or [], limit)

    async def references(self, paper: Paper, limit: int) -> list[Paper]:
        s2_id = paper.external_ids.get("s2")
        if not s2_id:
            return []
        payload = await self.fetcher.get_json(
            f"{self.base_url}/paper/{s2_id}/references",
            {"limit": min(limit, 100), "fields": FIELDS},
            prefix=f"{self.name}:references",
        )
        items = [item.get("citedPaper") for item in (payload or {}).get("data") or []]
        return self.collect([i for i in items if i], limit)

    async def citations(self, paper: Paper, limit: int) -> list[Paper]:
        s2_id = paper.external_ids.get("s2")
        if not s2_id:
            return []
        payload = await self.fetcher.get_json(
            f"{self.base_url}/paper/{s2_id}/citations",
            {"limit": min(limit, 100), "fields": FIELDS},
            prefix=f"{self.name}:citations",
        )
        items = [item.get("citingPaper") for item in (payload or {}).get("data") or []]
        return self.collect([i for i in items if i], limit)

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        external = raw.get("externalIds") or {}
        oa_pdf = (raw.get("openAccessPdf") or {}).get("url") or ""
        references = [
            r.get("paperId")
            for r in (raw.get("references") or [])
            if isinstance(r, dict) and r.get("paperId")
        ]
        citations = [
            c.get("paperId")
            for c in (raw.get("citations") or [])
            if isinstance(c, dict) and c.get("paperId")
        ]
        return Paper(
            id=raw.get("paperId") or "",
            title=raw.get("title") or "",
            year=raw.get("year"),
            authors=[a.get("name", "") for a in (raw.get("authors") or []) if a.get("name")],
            abstract=(raw.get("abstract") or "").strip(),
            venue=raw.get("venue") or "",
            doi=normalise_doi(external.get("DOI", "")),
            arxiv_id=(external.get("ArXiv") or "").strip(),
            url=oa_pdf or f"https://www.semanticscholar.org/paper/{raw.get('paperId', '')}",
            external_ids={"s2": raw.get("paperId") or ""},
            citation_count=int(raw.get("citationCount") or 0),
            references=references,
            citations=citations,
        )
