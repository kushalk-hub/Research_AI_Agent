"""Entity resolution: collapse many names for one concept into a single node.

Spec §9. The pipeline is three tiers, cheapest first, because over-merging is the
expensive mistake here — a wrongly fused node silently deletes a lineage path,
whereas a missed merge only leaves a duplicate to notice later:

1. **Normalised name.** "Graph Attention Networks" and "graph attention
   networks" are the same string. Costs nothing and needs no model, so it also
   makes this stage work with no API key at all.
2. **Embedding similarity, decisively high.** Same centroid text and cosine above
   `AUTO_MERGE` is treated as identity. The threshold is deliberately strict.
3. **LLM judge, borderline only.** Similarity in `[MAYBE_MERGE, AUTO_MERGE)` is
   the one genuinely ambiguous band, so it is the only thing that spends a call.

Every decision — merge *and* refusal to merge — is recorded with its evidence, so
the over-merge check in the milestone gate is auditable rather than a vibe.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from rla.events import Event, Phase, event
from rla.llm.base import LLMClient, LLMError
from rla.llm.embedding_base import cosine
from rla.llm.embeddings import Embedder
from rla.llm.errors import ProviderError
from rla.llm.prompts.templates import CONCEPT_RESOLUTION
from rla.models import Concept, Extraction
from rla.store.cache import CostTracker

STAGE = "resolution"
#: At or above this cosine, two clusters are the same thing without asking anyone.
AUTO_MERGE = 0.92
#: Below this they are certainly different. Only the band between is judged.
MAYBE_MERGE = 0.70
#: Judging is the only per-pair spend, so the budget is bounded and reported.
MAX_JUDGE_CALLS = 40
#: Representative text handed to the judge and the embedder.
DESCRIPTION_CHARS = 200


def normalise_name(name: str) -> str:
    """Case/punctuation-insensitive key. Deliberately does *not* expand acronyms:
    turning GAT into graph attention networks is a judgement, not a string op.

    Full stops are dropped rather than spaced, so "G.A.T." folds onto "GAT";
    every other separator becomes a space, so "graph-net" folds onto "graph net".
    """
    cleaned = (name or "").casefold().replace(".", "")
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class Mention:
    name: str
    description: str
    paper_id: str
    year: int | None = None
    role: str = "uses"

    def centroid_text(self) -> str:
        description = " ".join(self.description.split())[:DESCRIPTION_CHARS]
        return f"{self.name}: {description}" if description else self.name


@dataclass
class MergeDecision:
    """One logged judgement. `kept` is the survivor, `merged` the name absorbed."""

    kept: str
    merged: str
    verdict: Literal["same", "different"]
    reason: str
    evidence: str
    canonical: str = ""
    confidence: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kept": self.kept,
            "merged": self.merged,
            "canonical": self.canonical,
            "verdict": self.verdict,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


class Verdict(BaseModel):
    verdict: Literal["same", "different"]
    confidence: float = Field(ge=0.0, le=1.0)
    canonical: str = ""


class _Union:
    """Union-find over cluster ids; the merge relation must be transitive."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, item: int) -> int:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:  # path compression
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            # Keep the lower id as root so the survivor is deterministic.
            low, high = sorted((root_a, root_b))
            self.parent[high] = low


def collect_mentions(
    extractions: Sequence[Extraction], paper_years: dict[str, int] | None = None
) -> list[Mention]:
    """Flatten every concept mention across papers into one list."""
    years = paper_years or {}
    mentions: list[Mention] = []
    for extraction in extractions:
        for mention in extraction.concepts:
            if mention.name:
                mentions.append(
                    Mention(
                        name=mention.name.strip(),
                        description=(mention.description or "").strip(),
                        paper_id=extraction.paper_id,
                        year=years.get(extraction.paper_id),
                    )
                )
    return mentions


def group_by_name(mentions: Sequence[Mention]) -> list[list[Mention]]:
    """Tier 1: merge on the normalised name, preserving first-seen order."""
    groups: dict[str, list[Mention]] = {}
    for mention in mentions:
        groups.setdefault(normalise_name(mention.name), []).append(mention)
    return list(groups.values())


def canonical_name(members: Sequence[Mention], preferred: dict[str, str] | None = None) -> str:
    """Most-used surface form wins; ties break toward the more descriptive one.

    Frequency beats elegance here because the dominant spelling is the one a
    reader searching the corpus will type — except where the judge was asked and
    gave an explicit preference, which outranks both.
    """
    if preferred:
        votes: dict[str, int] = {}
        for member in members:
            choice = preferred.get(normalise_name(member.name))
            if choice:
                votes[choice] = votes.get(choice, 0) + 1
        if votes:
            return max(votes, key=lambda name: (votes[name], len(name), name))
    counts: dict[str, int] = {}
    for member in members:
        counts[member.name] = counts.get(member.name, 0) + 1
    return max(counts, key=lambda name: (counts[name], len(name), name))


def _describe(members: Sequence[Mention]) -> str:
    descriptions = [m.description for m in members if m.description]
    return max(descriptions, key=len)[:DESCRIPTION_CHARS] if descriptions else ""


def build_concept(members: Sequence[Mention], preferred: dict[str, str] | None = None) -> Concept:
    name = canonical_name(members, preferred)
    years = [m.year for m in members if m.year is not None]
    return Concept(
        id=Concept.slug(name),
        name=name,
        description=_describe(members),
        first_seen_year=min(years) if years else None,
        aliases=list(dict.fromkeys(m.name for m in members)),
        paper_ids=list(dict.fromkeys(m.paper_id for m in members)),
    )


def _similar_pairs(vectors: Sequence[Sequence[float]]) -> list[tuple[float, int, int]]:
    """All pairs at or above MAYBE_MERGE, most similar first, for a bounded budget."""
    pairs: list[tuple[float, int, int]] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine(vectors[i], vectors[j])
            if score >= MAYBE_MERGE:
                pairs.append((score, i, j))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    return pairs


async def _judge(
    a: str,
    a_desc: str,
    b: str,
    b_desc: str,
    llm: LLMClient,
    semaphore: asyncio.Semaphore,
    model: str = "",
) -> tuple[Verdict | None, Exception | None]:
    async with semaphore:
        try:
            # Forwarded for the same reason as extraction: the audit found this
            # stage accepted `model` and only used it to label a cost report, so
            # the configured judge model never actually judged anything.
            verdict = await llm.generate_structured(
                CONCEPT_RESOLUTION.format(a=a, a_desc=a_desc, b=b, b_desc=b_desc),
                Verdict,
                stage=STAGE,
                model=model or None,
            )
        except (LLMError, ValueError) as exc:
            return None, exc
    return verdict, None


def _reason(error: Exception, limit: int = 140) -> str:
    text = " ".join(str(error).split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


async def resolve_concepts(
    extractions: Sequence[Extraction],
    llm: LLMClient | None = None,
    embedder: Embedder | None = None,
    concurrency: int = 4,
    tracker: CostTracker | None = None,
    model: str = "",
    paper_years: dict[str, int] | None = None,
) -> AsyncIterator[Event]:
    """Merge duplicate concept names.

    The final event carries `concepts` and `decisions` in its payload: the caller
    needs the result, but this stage returns nothing but events by contract.
    """
    mentions = collect_mentions(extractions, paper_years)
    if not mentions:
        yield event(
            Phase.RESOLVE,
            "No concepts to resolve",
            kind="ok",
            concepts=0,
            concept_nodes=[],
            decisions=[],
        )
        return

    clusters = group_by_name(mentions)
    yield event(
        Phase.RESOLVE,
        f"{len(mentions)} mentions -> {len(clusters)} distinct names",
        kind="ok",
        mentions=len(mentions),
        names=len(clusters),
    )

    decisions: list[MergeDecision] = []
    #: judge-chosen spelling per normalised name; beats the frequency heuristic
    preferred: dict[str, str] = {}
    union = _Union()
    for index in range(len(clusters)):
        union.find(index)

    if embedder is None and llm is None:
        yield event(
            Phase.RESOLVE,
            "no embedder or LLM configured: merged on normalised name only",
            kind="warn",
        )

    texts = [canonical_name(group) for group in clusters]
    vectors: list[Sequence[float]] = []
    if embedder is not None:
        yield event(Phase.RESOLVE, f"Embedding {len(texts)} concept names", kind="ok")
        try:
            vectors = await embedder.embed_many([g[0].centroid_text() for g in clusters])
        except (LLMError, ProviderError) as exc:
            # Losing embeddings degrades to name-only resolution: fewer merges, but
            # never a wrong one. Every embedding failure is fatal *to this
            # capability* and none of them are reasons to abandon the run.
            yield event(
                Phase.RESOLVE,
                f"embedding failed ({_reason(exc)}); keeping name-only resolution",
                kind="warn",
            )
            vectors = []

    judged = 0
    semaphore = asyncio.Semaphore(concurrency)
    if vectors:
        for score, i, j in _similar_pairs(vectors):
            if score >= AUTO_MERGE:
                union.union(i, j)
                decisions.append(
                    MergeDecision(
                        kept=texts[min(i, j)],
                        merged=texts[max(i, j)],
                        verdict="same",
                        reason="auto-similarity",
                        evidence=f"cosine={score:.3f} >= {AUTO_MERGE}",
                        confidence=score,
                    )
                )
                continue
            if judged >= MAX_JUDGE_CALLS or llm is None:
                continue
            judged += 1
            verdict, error = await _judge(
                texts[i],
                _describe(clusters[i]),
                texts[j],
                _describe(clusters[j]),
                llm,
                semaphore,
                model,
            )
            if verdict is None:
                # No verdict means no merge: the safe direction to fail in.
                decisions.append(
                    MergeDecision(
                        kept=texts[i],
                        merged=texts[j],
                        verdict="different",
                        reason="judge-failed",
                        evidence=_reason(error) if error else "no verdict returned",
                    )
                )
                continue
            if verdict.verdict == "same":
                union.union(i, j)
                choice = verdict.canonical or texts[i]
                # The judge's chosen spelling outranks frequency, so record it
                # against both names that were folded together.
                preferred[normalise_name(texts[i])] = choice
                preferred[normalise_name(texts[j])] = choice
                decisions.append(
                    MergeDecision(
                        kept=choice,
                        merged=texts[j],
                        verdict="same",
                        reason="llm-judge",
                        evidence=f"cosine={score:.3f}",
                        canonical=choice,
                        confidence=verdict.confidence,
                    )
                )
            else:
                decisions.append(
                    MergeDecision(
                        kept=texts[i],
                        merged=texts[j],
                        verdict="different",
                        reason="llm-judge",
                        evidence=f"cosine={score:.3f}",
                        confidence=verdict.confidence,
                    )
                )
        if judged >= MAX_JUDGE_CALLS:
            yield event(
                Phase.RESOLVE,
                f"judge budget reached ({MAX_JUDGE_CALLS} calls); borderline pairs beyond it "
                "are left unmerged rather than guessed",
                kind="warn",
                judged=judged,
            )

    grouped: dict[int, list[Mention]] = {}
    for index, group in enumerate(clusters):
        grouped.setdefault(union.find(index), []).extend(group)

    concepts = [build_concept(members, preferred) for members in grouped.values()]
    concepts.sort(key=lambda c: (-len(c.paper_ids), c.name))
    for decision in decisions:
        if decision.verdict == "same" and not decision.canonical:
            decision.canonical = decision.kept

    refused = sum(1 for d in decisions if d.verdict == "different")
    cost = tracker.stage_report(STAGE, model) if tracker else None
    yield event(
        Phase.RESOLVE,
        f"{len(clusters)} names -> {len(concepts)} concepts "
        f"({len(clusters) - len(concepts)} merged, {refused} borderline pairs kept separate, "
        f"{judged} judged)",
        kind="ok",
        concepts=len(concepts),
        concept_nodes=[c.model_dump() for c in concepts],
        decisions=[d.to_dict() for d in decisions],
        cost=cost,
    )
