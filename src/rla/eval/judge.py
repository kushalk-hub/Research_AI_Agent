"""Scoring answers on the §10 rubric: correctness, completeness, citation accuracy.

The plan asks for an LLM-as-judge. There are no Gemini requests available here --
the free tier is a per-model daily cap and it is spent -- so this module has to
work without a key *and* be honest about what it then produces.

The rule that matters
---------------------
A heuristic score is not a judge score, and the report must never present one as
the other. So:

- `JudgeKind.LLM` means a real model graded the answer.
- `JudgeKind.HEURISTIC` means the checks below ran, and every number derived from
  them carries `judge_kind="heuristic"` into `eval/report.md` and into the
  comparison table, right next to the number.

What the heuristic can and cannot do
------------------------------------
Citation accuracy is almost fully mechanical: does every citation exist in the
evidence, and does the cited text actually contain the claim's key terms. That is
close to ground truth, so the heuristic number there is worth reading.

Correctness and completeness are not mechanical. Without a reader, "is this
answer right" reduces to "does the answer's content appear in its own evidence",
which is a citation-support check, not a truth check. It is reported as
`support_rate` and never as `correctness`, because calling it correctness would
claim a verification nobody performed.

With a key, `LLMJudge` asks the model the real question and returns rubric
scores. Both paths return the same shape, so `run_eval` does not branch.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

#: Terms a judge should not accept as a claim by themselves. Not stopwords: these
#: are the hedges that make an answer unfalsifiable.
HEDGE_WORDS = frozenset({"may", "might", "could", "possibly", "potentially", "some"})

#: Citation labels the pipeline emits look like `[P1]` or `[C2]`.
_CITATION = re.compile(r"\[([PC]\d+)\]")


class JudgeKind(StrEnum):
    LLM = "llm"
    HEURISTIC = "heuristic"


@dataclass
class RubricScore:
    """One rubric dimension for one answer.

    `judge_kind` rides on every score so it cannot be separated from the number
    when it reaches the report.
    """

    name: str
    value: float | None
    judge_kind: JudgeKind
    #: Why this is `None`, when it is.
    note: str = ""
    #: Whether this dimension is mechanically checkable, and so trustworthy
    #: without a model.
    mechanical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": None if self.value is None else round(self.value, 4),
            "judge_kind": str(self.judge_kind),
            "mechanical": self.mechanical,
            "note": self.note,
        }


@dataclass
class AnswerScore:
    """The rubric applied to one system answering one question."""

    system: str
    question: str
    kind: JudgeKind
    scores: dict[str, RubricScore] = field(default_factory=dict)
    #: Raw text the scores describe, for a reader to check the judgement.
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def value(self, dimension: str) -> float | None:
        score = self.scores.get(dimension)
        return None if score is None else score.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "question": self.question,
            "judge_kind": str(self.kind),
            "answer": self.answer,
            "citations": list(self.citations),
            "notes": list(self.notes),
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
        }


class Judge(Protocol):
    """What `run_eval` needs from a judge, whether model-backed or not."""

    kind: JudgeKind

    def score(
        self,
        system: str,
        question: str,
        answer: str,
        evidence: str,
        citations: Sequence[str],
    ) -> AnswerScore: ...


def extract_citations(text: str) -> list[str]:
    """Citation labels in the order they appear, de-duplicated.

    Order is kept because a reader checking a claim reads the first support, and
    because a citation appearing twice is worth knowing about.
    """
    seen: list[str] = []
    for label in _CITATION.findall(text or ""):
        if label not in seen:
            seen.append(label)
    return seen


def _content_terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower())}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _claim_supported(claim: str, evidence: str) -> bool | None:
    """Whether the claim's content words appear in the evidence.

    None when the claim is too short or too generic to check, which is itself
    worth reporting: a judge that only checks substantial claims is a judge with a
    blind spot, and pretending otherwise would overstate confidence.
    """
    terms = _content_terms(claim) - HEDGE_WORDS
    if len(terms) < 2:
        return None
    evidence_terms = _content_terms(evidence)
    return len(terms & evidence_terms) / len(terms) >= 0.5


class HeuristicJudge:
    """Scores what can be scored without a model, and names the rest.

    It is not an LLM judge and `kind` says so. What it produces:
      - `citation_validity`: fraction of cited labels that exist in the evidence.
        Mechanical, so this number is worth reading.
      - `citation_support`: fraction of content sentences supported by evidence.
        Mechanical, and the closest thing available to a correctness check.
      - `completeness`: reported as `None` with a reason. There is no honest
        mechanical version of "did this answer everything asked".
      - `correctness`: deliberately not emitted. Support is not truth.
    """

    kind = JudgeKind.HEURISTIC

    def score(
        self,
        system: str,
        question: str,
        answer: str,
        evidence: str,
        citations: Sequence[str],
    ) -> AnswerScore:
        notes: list[str] = []
        labels = list(citations) or extract_citations(answer)
        available = set(extract_citations(evidence)) | set(re.findall(r"\[[^\]]+\]", evidence))

        if labels:
            valid = sum(1 for c in labels if c in available or c in (evidence or ""))
            validity: float | None = valid / len(labels)
            if validity < 1.0:
                notes.append(
                    f"{len(labels) - valid} of {len(labels)} citations are not present in "
                    "the evidence supplied to the judge"
                )
        else:
            validity = None
            notes.append("the answer cites nothing, so citation accuracy cannot be scored")

        claims = _sentences(answer)
        checks = [c for c in (_claim_supported(c, evidence) for c in claims) if c is not None]
        if checks:
            support: float | None = sum(1 for c in checks if c) / len(checks)
        else:
            support = None
            notes.append("no substantial claim in the answer to check against the evidence")

        return AnswerScore(
            system=system,
            question=question,
            kind=self.kind,
            answer=answer,
            citations=labels,
            notes=notes,
            scores={
                "citation_validity": RubricScore(
                    "citation_validity",
                    validity,
                    self.kind,
                    "cited labels that appear in the evidence",
                    mechanical=True,
                ),
                "citation_support": RubricScore(
                    "citation_support",
                    support,
                    self.kind,
                    "content sentences whose terms appear in the evidence; this is "
                    "citation support, not truth",
                    mechanical=True,
                ),
                "completeness": RubricScore(
                    "completeness",
                    None,
                    self.kind,
                    "not measurable without a reader: whether the answer covers every "
                    "part of the question is a judgement about intent",
                ),
            },
        )


class LLMJudge:
    """Rubric scoring by a real model, used when a key and budget are available.

    Kept deliberately thin and not exercised by the default run: the point is
    that the path exists and is honest about its kind, so `rla eval` upgrades
    rather than being rewritten when a key is present.
    """

    kind = JudgeKind.LLM

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    RUBRIC = (
        "Score the answer against the evidence on three axes, 0.0 to 1.0:\n"
        "correctness - is every claim in the answer supported by the evidence?\n"
        "completeness - does the answer address every part of the question?\n"
        "citation_accuracy - does each citation refer to evidence that backs the "
        "claim next to it?\n"
        "Answer with JSON only: "
        '{"correctness": float, "completeness": float, "citation_accuracy": float}'
    )

    def score(
        self,
        system: str,
        question: str,
        answer: str,
        evidence: str,
        citations: Sequence[str],
    ) -> AnswerScore:
        import json

        prompt = (
            f"{self.RUBRIC}\n\nQuestion:\n{question}\n\nEvidence:\n{evidence}\n\n"
            f"Answer:\n{answer}\n"
        )
        text = self.client.complete(prompt, model=self.model)
        try:
            payload = json.loads(_first_json_object(text))
            values = {
                "correctness": float(payload["correctness"]),
                "completeness": float(payload["completeness"]),
                "citation_accuracy": float(payload["citation_accuracy"]),
            }
            note = ""
        except (ValueError, KeyError, TypeError) as exc:
            values = {k: None for k in ("correctness", "completeness", "citation_accuracy")}
            note = f"the judge returned unparseable output ({exc}); nothing was scored"

        return AnswerScore(
            system=system,
            question=question,
            kind=self.kind,
            answer=answer,
            citations=list(citations),
            notes=[note] if note else [],
            scores={
                name: RubricScore(
                    name,
                    value,
                    self.kind,
                    note,
                    mechanical=False,
                )
                for name, value in values.items()
            },
        )


def _first_json_object(text: str) -> str:
    """Pull the first `{...}` block out of a reply that may be fenced or chatty."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in the reply")
    return text[start : end + 1]


def aggregate(scores: Sequence[AnswerScore], dimension: str) -> float | None:
    """Mean of one dimension across answers, or None if nothing scored it.

    Averaging over only the answers that have a value would quietly change the
    denominator per system, so a system with mostly-unmeasurable answers would be
    compared on a different, easier subset. This averages over all of them and
    reports None when any is missing.
    """
    values = [s.value(dimension) for s in scores]
    if not values or any(v is None for v in values):
        return None
    return sum(values) / len(values)


def coverage(scores: Sequence[AnswerScore], dimension: str) -> float:
    """Fraction of answers for which `dimension` produced a number."""
    if not scores:
        return 0.0
    return sum(1 for s in scores if s.value(dimension) is not None) / len(scores)
