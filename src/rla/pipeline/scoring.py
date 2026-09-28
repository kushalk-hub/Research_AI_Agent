"""LLM relevance scoring, 1-5 (spec section 2, layer 1).

Batched ten papers per call: 100 individual calls would be both slow and
pointlessly expensive for a judgement that is only used to trim the corpus.
Scores are written back onto each `Paper` in place.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from rla.events import Event, Phase, event
from rla.llm.base import LLMClient, LLMError
from rla.models import Paper

BATCH_SIZE = 10
MIN_KEEP_SCORE = 3
DEFAULT_SCORE = 3

SCORING_PROMPT = """\
Score how relevant each paper is to the research topic below. Use the title, year, and abstract.

Topic: {title}

Papers:
{papers}

Scoring rubric:
5 - directly studies the topic's core problem
4 - clearly related method, task, or application
3 - adjacent work that a survey of the topic should mention
2 - tangential
1 - irrelevant

Return JSON: {{"scores": [{{"id": "...", "score": 1-5, "reason": "max 10 words"}}]}}
Return one entry per paper, with the id exactly as given."""


def _reason(error: Exception | None, limit: int = 140) -> str:
    """Provider errors are multi-kilobyte JSON blobs; keep the log readable."""
    if error is None:
        return "unknown error"
    text = " ".join(str(error).split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


class ScoreEntry(BaseModel):
    id: str
    score: int = Field(ge=1, le=5)
    reason: str = ""


class ScoreSet(BaseModel):
    scores: list[ScoreEntry] = Field(default_factory=list)


def _batch_prompt(papers: list[Paper], title: str) -> str:
    lines = []
    for paper in papers:
        snippet = (paper.abstract or "")[:400].replace("\n", " ")
        lines.append(
            f"- id: {paper.id}\n  title: {paper.title}\n  year: {paper.year}\n  abstract: {snippet}"
        )
    return SCORING_PROMPT.format(title=title, papers="\n".join(lines))


async def _score_batch(
    papers: list[Paper],
    title: str,
    llm: LLMClient,
    semaphore: asyncio.Semaphore,
    model: str = "",
) -> tuple[list[ScoreEntry], Exception | None]:
    async with semaphore:
        try:
            result = await llm.generate_structured(
                _batch_prompt(papers, title),
                ScoreSet,
                stage="relevance_scoring",
                model=model or None,
            )
        except (LLMError, RuntimeError) as exc:
            return [], exc
        return result.scores, None


def relevance_histogram(papers: list[Paper]) -> dict[str, Any]:
    histogram: dict[str, int] = {}
    for paper in papers:
        key = str(paper.relevance_score if paper.relevance_score is not None else "unscored")
        histogram[key] = histogram.get(key, 0) + 1
    return dict(sorted(histogram.items()))


async def score_papers(
    papers: list[Paper],
    title: str,
    llm: LLMClient,
    concurrency: int = 4,
    model: str = "",
) -> AsyncIterator[Event]:
    """Assign `relevance_score` to every paper. Unscored papers default to 3.

    Defaulting rather than dropping keeps one failed batch from emptying the
    corpus; that paper simply stops being discriminated on. The final event
    reports how many papers the model actually scored, so "0 scored" is visible
    as a provider failure rather than looking like a neutral result.
    """
    yield event(Phase.SCORE, f"Scoring {len(papers)} papers for relevance")

    batches = [papers[i : i + BATCH_SIZE] for i in range(0, len(papers), BATCH_SIZE)]
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(_score_batch(b, title, llm, semaphore, model) for b in batches)
    )

    assigned: dict[str, int] = {}
    failures = [error for _, error in results if error is not None]
    for entries, _ in results:
        for entry in entries:
            assigned[entry.id] = entry.score
    for paper in papers:
        paper.relevance_score = assigned.get(paper.id, DEFAULT_SCORE)

    histogram = relevance_histogram(papers)
    payload = {
        "scored": len(assigned),
        "failed_batches": len(failures),
        "distribution": histogram,
    }
    if not assigned:
        reason = _reason(failures[0]) if failures else "the model returned no scores"
        yield event(
            Phase.SCORE,
            f"Scored 0/{len(papers)} papers - every paper kept the default score of "
            f"{DEFAULT_SCORE} ({reason})",
            kind="warn",
            **payload,
        )
        return
    message = f"Scored {len(assigned)}/{len(papers)} papers"
    if failures:
        message += f"; {len(failures)} batch(es) failed ({_reason(failures[0])})"
    yield event(Phase.SCORE, message, kind="ok", **payload)
