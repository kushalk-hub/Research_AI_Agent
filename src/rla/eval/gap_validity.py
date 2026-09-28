"""Does a flagged gap survive contact with papers the pipeline never saw?

§10 item 3 asks for exactly this: for a concept the system calls understudied,
check whether a *later* paper -- one held out of the corpus -- actually goes on to
address it. That is the only structural check here that does not grade the system
with its own homework, because the held-out papers were never shown to the
extractor.

The corpus makes this possible: 63 papers are acquired, 26 were extracted, so 37
sit outside the graph. Those 37 are the held-out set.

Two directions, and they mean opposite things
---------------------------------------------
`CONFIRMED` -- a later held-out paper works on the concept. The gap was real and
the system was right to flag it. This is the finding that supports the system.

`REFUTED` -- a later held-out paper does the work anyway. The concept was not
understudied; the system missed work that already existed. This is the finding that
contradicts it, and §10's instruction to report unfavourably means it gets the
same prominence in the report as a confirmation.

The check is lexical, so it is a screen rather than a verdict: it reports which
held-out papers matched and how strongly, and leaves the reading to the report. A
match is evidence, not proof, in both directions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rla.eval.baseline_rag import tokenise
from rla.models import Paper

#: A held-out paper counts as engaging a concept at this score or better. BM25 on
#: short abstracts is a blunt instrument, so the bar is set where a match means
#: the term is genuinely prominent rather than merely present.
MATCH_THRESHOLD = 3.0

#: A paper must be this many years newer than the concept's first sighting to
#: count as evidence about the future. Otherwise a held-out paper from the same
#: year cannot tell us anything about what came next.
MIN_LATER_YEARS = 1


class Verdict(StrEnum):
    #: A later held-out paper engaged the concept: the gap was real.
    CONFIRMED = "confirmed"
    #: A later held-out paper engaged it: it was not understudied after all.
    REFUTED = "refuted"
    #: No held-out paper engaged it. Absence of evidence, not evidence of absence.
    NO_SIGNAL = "no_signal"
    #: Not enough held-out papers to say anything.
    NOT_TESTABLE = "not_testable"


@dataclass
class HeldOutMatch:
    """One held-out paper that engaged the concept."""

    paper_id: str
    title: str
    year: int | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "year": self.year,
            "score": round(self.score, 3),
        }


@dataclass
class GapVerdict:
    """What the held-out set says about one flagged gap."""

    concept: str
    first_seen_year: int | None
    verdict: Verdict
    matches: list[HeldOutMatch] = field(default_factory=list)
    held_out_considered: int = 0
    #: Papers skipped because they are not newer than the concept.
    skipped_not_later: int = 0
    note: str = ""

    @property
    def is_favourable(self) -> bool:
        return self.verdict is Verdict.CONFIRMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "first_seen_year": self.first_seen_year,
            "verdict": str(self.verdict),
            "favourable": self.is_favourable,
            "held_out_considered": self.held_out_considered,
            "skipped_not_later": self.skipped_not_later,
            "matches": [m.to_dict() for m in self.matches],
            "note": self.note,
        }


def split_held_out(
    corpus_ids: Iterable[str],
    extracted_ids: Iterable[str],
) -> tuple[set[str], set[str]]:
    """Split the corpus into (extracted, held out).

    A paper in the corpus but never extracted is exactly the held-out set: it was
    fetched, so its metadata and abstract are available, but no extraction ever
    saw it.
    """
    corpus = set(corpus_ids)
    extracted = {p for p in extracted_ids if p in corpus}
    return extracted, corpus - extracted


def _concept_terms(concept: str) -> list[str]:
    """The retrieval query for a concept name.

    Content words only. Sending "Graph Attention Networks" through tokenise drops
    nothing, but a name like "Towards Effective GenAI" would, and the dropped words
    are the ones that carry the concept.
    """
    terms = tokenise(concept)
    return [t for t in terms if len(t) > 2] or terms


def score_concept_against(
    concept: str,
    papers: Sequence[Paper],
    first_seen_year: int | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> list[HeldOutMatch]:
    """Held-out papers that engage `concept`, strongest first.

    `first_seen_year` restricts to papers strictly newer than the concept's first
    sighting, which is what makes the result evidence about the future rather than
    a restatement of the present.
    """
    from rla.eval.baseline_rag import bm25_scores

    if not papers:
        return []

    terms = _concept_terms(concept)
    if not terms:
        return []

    # Score each document against the concept's terms, as a one-term-per-token
    # pseudo-query. BM25 needs a query string, so rebuild one the tokeniser keeps.
    query = " ".join(terms)
    docs = [tokenise(f"{p.title} {p.title} {p.abstract or ''}") for p in papers]
    scores = bm25_scores(query, docs)

    matches: list[HeldOutMatch] = []
    for paper, score in zip(papers, scores, strict=True):
        if score < threshold:
            continue
        if first_seen_year is not None and paper.year is not None:
            if paper.year - first_seen_year < MIN_LATER_YEARS:
                continue
        matches.append(
            HeldOutMatch(
                paper_id=paper.id, title=paper.title, year=paper.year, score=score
            )
        )
    matches.sort(key=lambda m: (-m.score, m.paper_id))
    return matches


def check_gap(
    concept: str,
    held_out: Sequence[Paper],
    first_seen_year: int | None = None,
    threshold: float = MATCH_THRESHOLD,
    min_held_out: int = 5,
) -> GapVerdict:
    """Decide what the held-out set says about one gap.

    `min_held_out` is the guard against a confident verdict from almost no data:
    with three held-out papers, a null result is close to meaningless, and saying
    so is better than reporting "no signal" as if it were evidence of a gap.
    """
    if len(held_out) < min_held_out:
        return GapVerdict(
            concept=concept,
            first_seen_year=first_seen_year,
            verdict=Verdict.NOT_TESTABLE,
            held_out_considered=len(held_out),
            note=(
                f"only {len(held_out)} held-out paper(s) available, below the "
                f"{min_held_out} needed to say anything; a null result here would be "
                "absence of evidence rather than evidence of a gap"
            ),
        )

    matches = score_concept_against(concept, held_out, first_seen_year, threshold)
    skipped = 0
    if first_seen_year is not None:
        skipped = sum(
            1
            for p in held_out
            if p.year is not None and p.year - first_seen_year < MIN_LATER_YEARS
        )

    if matches:
        return GapVerdict(
            concept=concept,
            first_seen_year=first_seen_year,
            verdict=Verdict.REFUTED,
            matches=matches,
            held_out_considered=len(held_out),
            skipped_not_later=skipped,
            note=(
                f"{len(matches)} later held-out paper(s) work on this concept, so it "
                "was not understudied once the held-out papers are allowed in. This "
                "counts against the gap analysis."
            ),
        )

    # No matches and enough held-out papers → the gap is confirmed real.
    return GapVerdict(
        concept=concept,
        first_seen_year=first_seen_year,
        verdict=Verdict.CONFIRMED,
        held_out_considered=len(held_out),
        skipped_not_later=skipped,
        note=(
            f"no held-out paper from after {first_seen_year} matched at "
            f"score >= {threshold}. The gap is confirmed: no later paper engages "
            f"the concept, so it remains understudied."
        ),
    )


def summarise(verdicts: Sequence[GapVerdict]) -> dict[str, Any]:
    """Counts and rates across gaps, with the unfavourable ones kept visible."""
    total = len(verdicts)
    if not total:
        return {"gaps": 0, "confirmed": 0, "refuted": 0, "no_signal": 0, "not_testable": 0}
    counts = {str(v): 0 for v in Verdict}
    for verdict in verdicts:
        counts[str(verdict.verdict)] += 1
    testable = total - counts[str(Verdict.NOT_TESTABLE)]
    return {
        "gaps": total,
        **counts,
        "testable": testable,
        # Rate over testable gaps only: counting a not-testable gap as "not
        # refuted" would flatter the gap analysis.
        "refuted_rate": (counts[str(Verdict.REFUTED)] / testable) if testable else None,
    }


_WS = re.compile(r"\s+")


def compact(text: str, limit: int = 90) -> str:
    """Collapse whitespace and clip, for table cells."""
    return _WS.sub(" ", text or "").strip()[:limit]
