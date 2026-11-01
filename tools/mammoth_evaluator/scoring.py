"""Apply Mammoth decisions to candidates and compute normalized scores."""

from __future__ import annotations

from .decision_schema import (
    ASSESSABILITY_QUESTION_KEY,
    RELEVANCE_QUESTION_KEY,
    CandidateDecision,
    compute_expected_relevance,
    normalize_response,
)


def apply_decision(
    cd: CandidateDecision, response_json: dict, latency_ms: float, meta: dict
) -> None:
    cd.raw_response = response_json
    cd.request_id = meta.get("request_id")
    cd.latency_ms = latency_ms
    cd.input_tokens = (meta.get("usage") or {}).get("input_tokens")
    cd.cost = (meta.get("usage") or {}).get("cost")
    try:
        nds = normalize_response(
            response_json, [ASSESSABILITY_QUESTION_KEY, RELEVANCE_QUESTION_KEY]
        )
    except Exception as exc:
        cd.status = "failed"
        cd.error = str(exc)
        return
    a_nd = nds[ASSESSABILITY_QUESTION_KEY]
    cd.assessability = a_nd.choice
    cd.assessability_probabilities = a_nd.probabilities
    cd.assessability_confidence = a_nd.confidence
    r_nd = nds[RELEVANCE_QUESTION_KEY]
    cd.relevance_score_raw = r_nd.score
    cd.relevance_probabilities = r_nd.probabilities
    cd.relevance_confidence = r_nd.confidence
    cd.relevance_legend = r_nd.legend
    exp, p45 = compute_expected_relevance(r_nd)
    cd.expected_relevance = exp
    cd.p_relevant_or_highly = p45
    if cd.assessability == "insufficient_evidence":
        cd.status = "unassessable"
    else:
        cd.status = "ok"


def make_candidate_decision(candidate, query_id: str) -> CandidateDecision:
    return CandidateDecision(
        query_id=query_id,
        candidate_id=candidate.candidate_id,
        paper_key=candidate.paper_key,
        title=candidate.title,
        year=candidate.year,
        paper_id=candidate.paper_id,
        doi=candidate.doi,
    )
