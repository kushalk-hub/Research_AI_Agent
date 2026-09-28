"""arXiv API - Atom feed of preprints (spec section 3a).

arXiv is the main defence against index lag: recent work often appears here
before it reaches Semantic Scholar.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

from rla.models import Paper
from rla.sources.base import HttpSource, clean_markup, normalise_doi

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: ElementTree.Element | None) -> str:
    return re.sub(r"\s+", " ", (node.text or "")).strip() if node is not None else ""


class ArxivSource(HttpSource):
    name = "arxiv"
    base_url = "https://export.arxiv.org/api/query"

    async def search(self, query: str, limit: int) -> list[Paper]:
        payload = await self.fetcher.get_text(
            self.base_url,
            {"search_query": f"all:{query}", "max_results": min(limit, 50)},
            prefix=self.name,
        )
        if not payload:
            return []
        try:
            root = ElementTree.fromstring(payload)  # noqa: S314 - trusted upstream API
        except ElementTree.ParseError:
            return []
        entries = root.findall(f"{ATOM}entry")
        return self.collect([self._entry(e) for e in entries], limit)

    def _entry(self, node: ElementTree.Element) -> dict[str, Any]:
        raw_id = _text(node.find(f"{ATOM}id"))
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
        published = _text(node.find(f"{ATOM}published"))
        return {
            "id": arxiv_id,
            "title": _text(node.find(f"{ATOM}title")),
            "summary": _text(node.find(f"{ATOM}summary")),
            "published": published,
            "authors": [_text(a.find(f"{ATOM}name")) for a in node.findall(f"{ATOM}author")],
            "doi": normalise_doi(_text(node.find(f"{ARXIV}doi"))),
            "journal_ref": _text(node.find(f"{ARXIV}journal_ref")),
            "url": raw_id,
            "categories": [c.get("term", "") for c in node.findall(f"{ATOM}category")],
        }

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        published = raw.get("published") or ""
        return Paper(
            id=f"arxiv:{raw.get('id', '')}",
            title=raw.get("title") or "",
            year=int(published[:4]) if published[:4].isdigit() else None,
            authors=[a for a in (raw.get("authors") or []) if a],
            abstract=clean_markup(raw.get("summary") or ""),
            venue=raw.get("journal_ref") or "arXiv preprint",
            doi=raw.get("doi") or "",
            arxiv_id=raw.get("id") or "",
            url=raw.get("url") or "",
            external_ids={"arxiv": raw.get("id") or ""},
            keywords=[c for c in (raw.get("categories") or []) if c][:5],
        )
