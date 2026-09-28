"""Source protocol shared by every acquisition adapter (spec section 3a)."""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from rla.models import Paper, content_hash
from rla.store.cache import Fetcher

#: Query params that must never enter a cache key or a log line.
_NOISE_PARAMS = {"api_key", "apikey", "token", "fields", "select"}


def normalise_doi(doi: str) -> str:
    """Lowercase, strip resolver prefixes. '' when unusable."""
    if not doi:
        return ""
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned if cleaned.startswith("10.") else ""


def normalise_title(title: str) -> str:
    """Aggressive normalisation so the same paper from two sources compares equal."""
    lowered = (title or "").lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def title_key(title: str) -> str:
    """Order-insensitive dedup key: sorted significant words of the title."""
    stop = {"a", "an", "the", "of", "for", "and", "in", "on", "with", "to", "via", "using"}
    words = [w for w in normalise_title(title).split() if w not in stop]
    return " ".join(sorted(words)[:20])


def dedup_keys(paper: Paper) -> list[str]:
    """All keys this paper can be matched on, most reliable first."""
    keys: list[str] = []
    if doi := normalise_doi(paper.doi):
        keys.append(f"doi:{doi}")
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id.strip().lower()}")
    if title := title_key(paper.title):
        keys.append(f"title:{title}")
    return keys


def make_paper_id(paper: Paper) -> str:
    """Stable id: prefer DOI, fall back to arXiv id, then a title hash."""
    if doi := normalise_doi(paper.doi):
        return f"doi:{doi}"
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id.strip().lower()}"
    return "t:" + content_hash(title_key(paper.title))[:16]


@runtime_checkable
class Source(Protocol):
    """One literature source. Implementations must be cache-friendly and keyless
    unless they declare otherwise via `requires_key`."""

    name: str
    requires_key: bool

    async def search(self, query: str, limit: int) -> list[Paper]:
        """Return candidate papers for one query."""
        ...

    async def references(self, paper: Paper, limit: int) -> list[Paper]:
        """Papers this one cites. Used for snowball sampling."""
        ...

    async def citations(self, paper: Paper, limit: int) -> list[Paper]:
        """Papers that cite this one."""
        ...


class HttpSource:
    """Shared plumbing for the HTTP adapters: fetcher, rate limit, id assignment.

    Subclasses implement `search` and `to_paper`. `references`/`citations` default
    to empty, which is honest: not every index exposes a citation graph.
    """

    name: str = "http"
    requires_key: bool = False
    base_url: str = ""
    #: Minimum seconds between calls. Semantic Scholar's anonymous pool is ~1/s.
    min_interval: float = 0.0

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @property
    def available(self) -> bool:
        return True

    def to_paper(self, raw: dict[str, Any]) -> Paper | None:
        raise NotImplementedError

    async def search(self, query: str, limit: int) -> list[Paper]:
        raise NotImplementedError

    async def references(self, paper: Paper, limit: int) -> list[Paper]:
        return []

    async def citations(self, paper: Paper, limit: int) -> list[Paper]:
        return []

    def finalise(self, paper: Paper | None) -> Paper | None:
        """Stamp source provenance and a stable id, or drop the record."""
        if paper is None:
            return None
        title = (paper.title or "").strip()
        if not title:
            return None
        paper.title = title
        if self.name not in paper.sources:
            paper.sources = [*paper.sources, self.name]
        paper.id = paper.id or make_paper_id(paper)
        paper.ensure_hash()
        return paper

    def collect(self, items: list[Any], limit: int) -> list[Paper]:
        """Map raw records to papers, dropping unusable ones and honouring `limit`."""
        papers: list[Paper] = []
        for raw in items[:limit]:
            try:
                paper = self.finalise(self.to_paper(raw))
            except (KeyError, TypeError, ValueError, AttributeError):
                paper = None
            if paper is not None:
                papers.append(paper)
        return papers


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as {token: [positions]}. Rebuild the prose."""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for token, indices in inverted_index.items():
        for index in indices or []:
            positions[index] = token
    return " ".join(positions[i] for i in sorted(positions))


def clean_markup(text: str) -> str:
    """Strip JATS/HTML tags that CrossRef and DBLP embed in abstracts."""
    if not text:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", without_tags).strip()


_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def guess_year(text: str) -> int | None:
    match = _YEAR_RE.search(text or "")
    return int(match.group(1)) if match else None
