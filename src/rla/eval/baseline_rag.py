"""The baseline the graph has to beat: plain RAG over abstracts.

Deliberately keyless. The comparison is only meaningful if it can be re-run
cheaply, and a baseline that needs the same Gemini budget as the system it is
measuring is neither cheap nor a fair control: a shared budget failure would
disable one arm of the comparison and not the other.

So this is a real retrieval baseline and nothing more:

- BM25 over title + abstract, with the standard k1/b parameters.
- The top-k papers are returned, ranked, and their abstracts are the evidence.

What it is NOT is a reader. It does not generate a fluent answer, because without
an LLM there is nothing to generate one with, and an extractive summary produced
by picking sentences would not be comparable to a generated answer. The comparison
therefore runs on what *is* comparable: whether the evidence a system surfaces
contains what the question needs, measured by `judge.py` on the same rubric for
both arms.

The BM25 implementation is here rather than pulled in because adding a retrieval
dependency to compare against it is a heavier change than the algorithm is.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from rla.models import Paper

#: Standard BM25 term-frequency saturation and length-normalisation.
BM25_K1 = 1.5
BM25_B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+")

#: Words carrying no retrieval signal. Kept short on purpose: a longer list
#: quietly improves the baseline, and a baseline improved to lose is not a
#: baseline.
STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have in is it its of on or that the
    their them these this to was were we with our us can could may might will
    would should using used use based via also more most than then so such which
    while between into over under about after before during through
    """.split()
)


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class RetrievedPaper:
    """One baseline hit, with the score that put it there."""

    paper_id: str
    title: str
    year: int | None
    score: float
    abstract: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "year": self.year,
            "score": round(self.score, 4),
        }


@dataclass
class RagResult:
    """The baseline's answer to one question: retrieved evidence, no prose."""

    question: str
    hits: list[RetrievedPaper] = field(default_factory=list)
    #: Set when retrieval could not run, e.g. an empty corpus.
    note: str = ""

    @property
    def citations(self) -> list[str]:
        return [h.paper_id for h in self.hits]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "note": self.note,
            "hits": [h.to_dict() for h in self.hits],
        }


def bm25_scores(query: str, documents: Sequence[Sequence[str]]) -> list[float]:
    """BM25 score of `query` against pre-tokenised `documents`.

    Documents that match nothing score exactly 0.0 rather than a tiny positive
    number, so an empty-corpus or no-overlap case is visible in the output.
    """
    if not documents:
        return []
    n = len(documents)
    lengths = [len(doc) for doc in documents]
    avg_length = sum(lengths) / n if n else 0.0
    if avg_length == 0:
        return [0.0] * n

    doc_freq: Counter[str] = Counter()
    for doc in documents:
        doc_freq.update(set(doc))

    query_terms = tokenise(query)
    scores = []
    for doc, length in zip(documents, lengths, strict=True):
        counts = Counter(doc)
        score = 0.0
        for term in query_terms:
            freq = counts.get(term, 0)
            if not freq:
                continue
            df = doc_freq.get(term, 0)
            # +0.5 smoothing: with a small corpus an unseen term would otherwise
            # divide by zero, and every document would score -inf.
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            norm = freq * (BM25_K1 + 1) / (
                freq + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_length)
            )
            score += idf * norm
        scores.append(score)
    return scores


def _document_text(paper: Paper) -> str:
    """Title is repeated twice: it is the densest signal in a short document."""
    return f"{paper.title} {paper.title} {paper.abstract or ''}"


def retrieve(
    question: str,
    papers: Iterable[Paper],
    top_k: int = 5,
    *,
    allow: set[str] | None = None,
) -> RagResult:
    """Retrieve the top-k papers for a question by BM25.

    `allow` restricts the searchable set by paper id, which is how the held-out
    split is enforced: when measuring what the graph knows, the baseline must not
    be able to retrieve the papers the graph was never shown.
    """
    pool = [p for p in papers if allow is None or p.id in allow]
    if not pool:
        return RagResult(
            question=question,
            note="no papers available to retrieve from",
        )
    docs = [tokenise(_document_text(p)) for p in pool]
    scores = bm25_scores(question, docs)
    order = sorted(range(len(pool)), key=lambda i: (-scores[i], pool[i].id))
    hits = [
        RetrievedPaper(
            paper_id=pool[i].id,
            title=pool[i].title,
            year=pool[i].year,
            score=scores[i],
            abstract=pool[i].abstract or "",
        )
        for i in order[:top_k]
        if scores[i] > 0.0
    ]
    note = "" if hits else "no paper shares a term with the question"
    return RagResult(question=question, hits=hits, note=note)


def evidence_text(result: RagResult, labels: dict[str, str] | None = None) -> str:
    """The baseline's evidence, as one string for the judge to read.

    Each paper is tagged with a short label so the judge can check citations
    against it. `labels` maps paper id to label; by default the label is the paper
    id itself, which keeps the evidence self-describing and lets
    `judge.extract_citations` match `[P1]`-style labels from either arm.
    """
    lines = []
    for hit in result.hits:
        label = (labels or {}).get(hit.paper_id, hit.paper_id)
        lines.append(f"[{label}] {hit.title}\n{hit.abstract}")
    return "\n\n".join(lines)


def paper_labels(paper_ids: Sequence[str]) -> dict[str, str]:
    """Stable `P1..Pn` labels for a fixed ordering of paper ids.

    Both arms need a citation vocabulary the judge can resolve. The graph arm
    already emits `[P1]`/`[C2]` from traversal; the baseline has to be given the
    same kind of label, or every one of its citations looks invalid and the
    comparison silently measures label format instead of retrieval.
    """
    return {pid: f"P{i + 1}" for i, pid in enumerate(paper_ids)}
