"""Core data contracts (spec section 5).

These pydantic models are the single source of truth for what crosses a stage
boundary. Each carries a `content_hash` so pipeline stages can be resumed and
LLM calls can be cache-validated without re-reading the source document.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def content_hash(*parts: Any) -> str:
    """Stable hash of any JSON-serialisable parts, used as a cache key."""
    blob = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class NodeType(StrEnum):
    PAPER = "Paper"
    CONCEPT = "Concept"


class EdgeType(StrEnum):
    CITES = "CITES"
    INTRODUCES = "INTRODUCES"
    USES = "USES"
    EXTENDS = "EXTENDS"
    REPLACES = "REPLACES"
    COMBINES_WITH = "COMBINES_WITH"
    HAS_LIMITATION = "HAS_LIMITATION"


class RelationType(StrEnum):
    """Relationship taxonomy requested from the extraction LLM (spec section 2, layer 2)."""

    EXTENDS = "extends"
    REPLACES = "replaces"
    COMBINES = "combines"
    APPLIES_TO_NEW_DOMAIN = "applies-to-new-domain"
    CRITIQUES = "critiques"


class ConceptMention(BaseModel):
    """A concept as it appears inside one paper, before entity resolution (P3)."""

    name: str
    description: str = ""
    role: str = Field(default="uses", description="introduces | uses | limitation")
    canonical_name: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class Paper(BaseModel):
    id: str
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    venue: str = ""
    doi: str = ""
    url: str = ""
    arxiv_id: str = ""
    external_ids: dict[str, str] = Field(
        default_factory=dict,
        help="Native ids per source (s2, openalex, dblp, ...) used to resolve citation edges",
    )
    sources: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(
        default_factory=list,
        description="Source-supplied concept/topic tags; seeds the concept vocabulary in P3",
    )
    citation_count: int = 0
    references: list[str] = Field(default_factory=list, help="Paper ids this paper cites")
    citations: list[str] = Field(default_factory=list, help="Paper ids that cite this paper")
    relevance_score: int | None = Field(default=None, ge=1, le=5)
    content_hash: str = ""

    def computed_hash(self) -> str:
        return content_hash(self.title.lower().strip(), self.year, self.abstract)

    def ensure_hash(self) -> str:
        """Recompute the hash of the current text, overwriting any earlier value.

        Deliberately not memoised on first write: a paper whose abstract is later
        corrected or enriched by a better source must change hash, or downstream
        stages keyed on it (the P2 extraction store) would keep serving output
        derived from text that no longer exists.
        """
        self.content_hash = self.computed_hash()
        return self.content_hash


class Concept(BaseModel):
    id: str
    name: str
    description: str = ""
    first_seen_year: int | None = None
    aliases: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)

    @classmethod
    def slug(cls, name: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"concept:{cleaned}"


class Relation(BaseModel):
    """An edge extracted by the LLM, before it is admitted to the graph."""

    source_id: str
    target_id: str
    edge_type: EdgeType
    relation: RelationType | None = None
    evidence: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Extraction(BaseModel):
    """One paper -> structured knowledge (spec section 2, layer 2)."""

    paper_id: str
    paper_hash: str = Field(
        default="",
        help="Content hash of the paper text this was extracted from; a changed "
        "abstract invalidates the extraction instead of silently keeping a stale one",
    )
    summary: str = ""
    concepts: list[ConceptMention] = Field(default_factory=list)
    builds_on: list[str] = Field(default_factory=list)
    relation: RelationType | None = None
    relation_target: str = ""
    stated_limitation: str = ""
    inferred_open_problem: str = ""
    extraction_hash: str = ""

    def ensure_hash(self) -> str:
        if not self.extraction_hash:
            self.extraction_hash = content_hash(self.paper_id, self.model_dump_json())
        return self.extraction_hash


class Corpus(BaseModel):
    """The working corpus produced by P1 and committed for eval reproducibility."""

    title: str
    papers: list[Paper] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    source_yield: dict[str, int] = Field(default_factory=dict)
    built_at: str = ""

    def by_id(self) -> dict[str, Paper]:
        return {p.id: p for p in self.papers}

    def cited_ids(self) -> dict[str, int]:
        """Map paper id -> 1-based citation label used in generated answers."""
        return {p.id: i + 1 for i, p in enumerate(self.papers)}

    def stats(self) -> dict[str, Any]:
        return {
            "papers": len(self.papers),
            "with_abstract": sum(1 for p in self.papers if p.abstract),
            "with_doi": sum(1 for p in self.papers if p.doi),
            "with_year": sum(1 for p in self.papers if p.year),
        }
