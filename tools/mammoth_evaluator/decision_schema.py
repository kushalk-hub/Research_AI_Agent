"""Request/response schemas and rubric definitions for the OpenRouter Decisions API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RUBRIC_LEVELS: tuple[str, ...] = (
    "Not relevant",
    "Tangential",
    "Partially relevant",
    "Relevant",
    "Highly relevant",
)

ASSESSABILITY_OPTIONS: tuple[str, ...] = ("assessable", "insufficient_evidence")

ASSESSABILITY_QUESTION_KEY = "assessability"
RELEVANCE_QUESTION_KEY = "relevance"


@dataclass(frozen=True)
class DecisionQuestion:
    key: str
    qtype: Literal["noul", "choice", "score"]
    instructions: str
    criteria: Any  # list[str] for score/noul-bool, dict for choice

    def to_request(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.qtype, "instructions": self.instructions}
        if self.criteria is not None:
            payload["criteria"] = self.criteria
        return payload


def build_questions() -> dict[str, DecisionQuestion]:
    return {
        ASSESSABILITY_QUESTION_KEY: DecisionQuestion(
            key=ASSESSABILITY_QUESTION_KEY,
            qtype="choice",
            instructions=(
                "Does the title and available abstract provide enough information to "
                "judge this paper's relevance to the research question?"
            ),
            criteria={
                "assessable": (
                    "Title and available abstract/context provide enough "
                    "information to judge relevance."
                ),
                "insufficient_evidence": (
                    "Information is missing, too short, or too incomplete "
                    "for a meaningful relevance judgment."
                ),
            },
        ),
        RELEVANCE_QUESTION_KEY: DecisionQuestion(
            key=RELEVANCE_QUESTION_KEY,
            qtype="score",
            instructions="How relevant is this paper to the research question?",
            criteria=list(RUBRIC_LEVELS),
        ),
    }


def make_request_body(
    model: str, state: str, questions: dict[str, DecisionQuestion]
) -> dict[str, Any]:
    return {
        "model": model,
        "state": state,
        "questions": {k: v.to_request() for k, v in questions.items()},
    }


@dataclass
class NormalizedDecision:
    question_key: str
    qtype: str
    raw_answer: dict[str, Any]
    # For choice/assessability:
    choice: str | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    # For score/relevance:
    score: float | None = None
    legend: dict[str, Any] | None = None
    # For noul:
    noul: float | None = None


@dataclass
class CandidateDecision:
    query_id: str
    candidate_id: str
    paper_key: str
    title: str
    year: str
    paper_id: str = ""
    doi: str = ""
    assessability: str | None = None  # assessable / insufficient_evidence
    assessability_probabilities: dict[str, float] | None = None
    assessability_confidence: float | None = None
    relevance_score_raw: float | None = None
    relevance_probabilities: dict[str, float] | None = None
    relevance_confidence: float | None = None
    relevance_legend: dict[str, Any] | None = None
    expected_relevance: float | None = None
    p_relevant_or_highly: float | None = None
    status: str = "ok"  # ok / unassessable / failed
    rank: int | None = None
    error: str | None = None
    request_id: str | None = None
    batch_id: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    cost: float | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


def normalize_response(
    response_json: dict[str, Any],
    question_keys: list[str],
) -> dict[str, NormalizedDecision]:
    """Normalize a Decisions API response into per-question NormalizedDecision.

    Uses the documented schema: top-level 'answers' (dict question->answer),
    optional 'usage', 'id', 'model', 'provider'.
    """
    answers = response_json.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("response missing 'answers' object")
    out: dict[str, NormalizedDecision] = {}
    for qk in question_keys:
        if qk not in answers:
            raise ValueError(f"missing answer for question {qk!r}")
        ans = answers[qk]
        if not isinstance(ans, dict):
            raise ValueError(f"answer for {qk!r} is not an object")
        qtype = ans.get("type")
        nd = NormalizedDecision(question_key=qk, qtype=qtype or "", raw_answer=ans)
        if qtype == "choice":
            nd.choice = ans.get("choice")
            nd.probabilities = ans.get("probabilities")
            nd.confidence = ans.get("confidence")
        elif qtype == "score":
            nd.score = ans.get("score")
            nd.probabilities = ans.get("probabilities")
            nd.confidence = ans.get("confidence")
            nd.legend = ans.get("legend")
        elif qtype == "noul":
            nd.noul = ans.get("noul")
        else:
            raise ValueError(f"unknown answer type {qtype!r} for {qk!r}")
        out[qk] = nd
    return out


def compute_expected_relevance(nd: NormalizedDecision) -> tuple[float | None, float | None]:
    """Return (expected_relevance, p_relevant_or_highly) using verified legend.

    Levels normalized to 1..5. If probabilities present and legend maps 0..4 or 1..5,
    compute weighted sum. Returns None if insufficient data.
    """
    probs = nd.probabilities
    if not probs:
        # fall back to score if present
        if nd.score is not None:
            # score is probability-weighted mean over criteria indices (0-based)
            # convert to 1..5 by +1
            return float(nd.score) + 1.0, None
        return None, None
    # Determine level mapping from legend if available; else assume keys '0'..'4'
    # Build list of (level_1based, probability) pairs
    pairs: list[tuple[int, float]] = []
    for k, v in probs.items():
        try:
            idx = int(k)
        except (ValueError, TypeError):
            continue
        # legend may map index->label; level = idx+1 (1-based)
        level = idx + 1
        # clamp to 1..5
        if level < 1 or level > 5:
            continue
        try:
            p = float(v)
        except (TypeError, ValueError):
            continue
        pairs.append((level, p))
    if not pairs:
        return None, None
    # normalize probabilities to sum 1 if needed
    total = sum(p for _, p in pairs)
    if total <= 0:
        return None, None
    exp_rel = sum(level * (p / total) for level, p in pairs)
    p_rel_high = sum(p / total for level, p in pairs if level >= 4)
    return exp_rel, p_rel_high
