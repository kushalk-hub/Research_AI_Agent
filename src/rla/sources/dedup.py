"""Cross-source deduplication (spec section 9).

The same paper arrives from Semantic Scholar, OpenAlex, arXiv, DBLP and CrossRef
with different ids, different title formatting, and different amounts of
metadata. Merging on DOI first, then arXiv id, then normalised title, and
unioning the rest, is what keeps duplicate nodes out of the graph.
"""

from __future__ import annotations

from rla.models import Paper
from rla.sources.base import dedup_keys, make_paper_id, normalise_doi

#: Namespaces a native id may belong to. Sources report bare ids in their
#: reference lists (e.g. Semantic Scholar returns raw paperIds), so resolution
#: has to try each namespace rather than assume one.
NAMESPACES: tuple[str, ...] = ("s2", "openalex", "crossref", "dblp", "arxiv")


def merge_papers(base: Paper, incoming: Paper) -> Paper:
    """Field-level merge that never discards information the other copy has.

    `base` keeps identity (its id and primary provenance); the richer value wins
    for every metadata field.
    """
    merged = base.model_copy(deep=True)

    if len(incoming.abstract) > len(merged.abstract):
        merged.abstract = incoming.abstract
    if len(incoming.authors) > len(merged.authors):
        merged.authors = incoming.authors
    if not merged.venue and incoming.venue:
        merged.venue = incoming.venue
    if not merged.doi and incoming.doi:
        merged.doi = normalise_doi(incoming.doi)
    if not merged.arxiv_id and incoming.arxiv_id:
        merged.arxiv_id = incoming.arxiv_id
    if not merged.url and incoming.url:
        merged.url = incoming.url
    if merged.year is None and incoming.year is not None:
        merged.year = incoming.year
    if incoming.citation_count > merged.citation_count:
        merged.citation_count = incoming.citation_count
    if merged.relevance_score is None:
        merged.relevance_score = incoming.relevance_score

    merged.external_ids = {**incoming.external_ids, **merged.external_ids}
    merged.keywords = list(dict.fromkeys([*merged.keywords, *incoming.keywords]))
    merged.sources = list(dict.fromkeys([*merged.sources, *incoming.sources]))
    merged.references = list(dict.fromkeys([*merged.references, *incoming.references]))
    merged.citations = list(dict.fromkeys([*merged.citations, *incoming.citations]))
    merged.ensure_hash()
    return merged


class Deduplicator:
    """Accumulates papers, collapsing duplicates onto one record per real paper."""

    def __init__(self) -> None:
        self._papers: dict[str, Paper] = {}
        self._key_to_id: dict[str, str] = {}
        self.duplicates_merged = 0
        self.by_source: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._papers)

    @property
    def papers(self) -> list[Paper]:
        return list(self._papers.values())

    def by_id(self, paper_id: str) -> Paper | None:
        return self._papers.get(paper_id)

    def keys_for(self, paper: Paper) -> list[str]:
        """Every key this paper can be matched on, plus its own native ids.

        The paper's own id is always a key. `lookup` accepts a bare value, so a
        source that reports an already-internal id has to resolve; without this
        a paper carrying no DOI or arXiv id drops every citation edge it takes
        part in, which is silent rather than loud.
        """
        keys = dedup_keys(paper)
        keys.append(paper.id)
        for namespace, native in paper.external_ids.items():
            if native:
                keys.append(f"{namespace}:{native}")
        return keys

    def add(self, paper: Paper) -> Paper:
        """Insert or merge, returning the canonical record."""
        if not paper.id:
            paper.id = make_paper_id(paper)
        paper.ensure_hash()
        for source in paper.sources:
            self.by_source[source] = self.by_source.get(source, 0) + 1

        keys = self.keys_for(paper)
        existing_id = next((self._key_to_id[key] for key in keys if key in self._key_to_id), None)

        if existing_id is None:
            self._papers[paper.id] = paper
            for key in keys:
                self._key_to_id[key] = paper.id
            return paper

        canonical = self._papers[existing_id]
        merged = merge_papers(canonical, paper)
        merged.id = existing_id
        self._papers[existing_id] = merged
        for key in self.keys_for(merged):
            self._key_to_id[key] = existing_id
        self.duplicates_merged += 1
        return merged

    def extend(self, papers: list[Paper]) -> None:
        for paper in papers:
            self.add(paper)

    def lookup(self, value: str) -> str | None:
        """Resolve any id a source might report onto an internal paper id."""
        candidates = [value, f"doi:{normalise_doi(value)}"]
        if ":" not in value:
            candidates.extend(f"{namespace}:{value}" for namespace in NAMESPACES)
        for candidate in candidates:
            if target := self._key_to_id.get(candidate):
                return target
        return None

    def resolve_citations(self) -> tuple[int, int]:
        """Rewrite native reference/citation ids to internal ids, dropping unknowns.

        Sources return their own identifier space; citation edges are only useful
        once both endpoints are corpus members. Returns (resolved, dropped).
        """
        resolved = dropped = 0
        for paper in self._papers.values():
            for field_name in ("references", "citations"):
                internal: list[str] = []
                for value in getattr(paper, field_name):
                    target = self.lookup(value)
                    if target is None or target == paper.id:
                        dropped += 1
                        continue
                    resolved += 1
                    internal.append(target)
                setattr(paper, field_name, list(dict.fromkeys(internal)))
        return resolved, dropped
