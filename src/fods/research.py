"""Research profiles and validated question/query planning for the FODS CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fods.events import EventLog
from fods.tracing import traced_model_call
from rla.models import Paper
from rla.sources.base import normalise_doi, normalise_title
from rla.sources.dedup import merge_papers


class ResearchIntent(StrEnum):
    OVERVIEW = "overview"
    COMPARISON = "comparison"
    LINEAGE = "lineage"
    METHODS = "methods"
    LIMITATIONS = "limitations_gaps"
    OTHER = "other"


class ResearchProfile(BaseModel):
    """Bounded policy shared by acquisition, evidence selection, and CLI summaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["quick", "deep"]
    target_unique_papers: int = Field(ge=1, le=30)
    max_retained_papers: int = Field(ge=1, le=50)
    candidate_limit: int = Field(ge=1, le=100)
    max_evidence_papers: int = Field(ge=1, le=15)
    evidence_token_budget: int = Field(ge=1000, le=30000)
    budget_seconds: int = Field(ge=30, le=600)
    source_limit: int = Field(ge=2, le=5)
    per_query_limit: int = Field(ge=1, le=20)
    query_count: int = Field(ge=1, le=6)
    minimum_sources: int = Field(ge=1, le=5)
    early_quorum: bool

    @model_validator(mode="after")
    def limits_are_consistent(self) -> ResearchProfile:
        if self.target_unique_papers > self.max_retained_papers:
            raise ValueError("target_unique_papers cannot exceed max_retained_papers")
        if self.minimum_sources > self.source_limit:
            raise ValueError("minimum_sources cannot exceed source_limit")
        if self.query_count > 1 and self.source_limit * self.query_count > 24:
            raise ValueError(
                "source_limit × query_count exceeds the 24-source-task cap with checkpoint"
            )
        return self


def profile_for(name: str, **overrides: Any) -> ResearchProfile:
    """Return a validated profile; caller overrides can tighten its limits."""
    if name == "quick":
        values: dict[str, Any] = {
            "profile": "quick",
            "target_unique_papers": 8,
            "max_retained_papers": 20,
            "candidate_limit": 50,
            "max_evidence_papers": 6,
            "evidence_token_budget": 6000,
            "budget_seconds": 120,
            "source_limit": 3,
            "per_query_limit": 10,
            "query_count": 1,
            "minimum_sources": 2,
            "early_quorum": True,
        }
    elif name == "deep":
        values = {
            "profile": "deep",
            "target_unique_papers": 25,
            "max_retained_papers": 50,
            "candidate_limit": 100,
            "max_evidence_papers": 8,
            "evidence_token_budget": 12000,
            "budget_seconds": 600,
            "source_limit": 5,
            "per_query_limit": 15,
            "query_count": 4,
            "minimum_sources": 3,
            "early_quorum": False,
        }
    else:
        raise ValueError("profile must be 'quick' or 'deep'")
    values.update(overrides)
    if "minimum_sources" not in overrides and int(values["source_limit"]) < int(
        values["minimum_sources"]
    ):
        values["minimum_sources"] = values["source_limit"]
    return ResearchProfile.model_validate(values)


class QueryPlanOutput(BaseModel):
    """Strict structured model response; the runtime still owns the source tasks."""

    model_config = ConfigDict(extra="forbid")

    intent: ResearchIntent
    queries: list[str] = Field(min_length=1, max_length=6)

    @field_validator("queries")
    @classmethod
    def queries_are_nonblank(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(query.split()) for query in value]
        if any(not query for query in cleaned):
            raise ValueError("queries must not be blank")
        if len(set(query.casefold() for query in cleaned)) != len(cleaned):
            raise ValueError("queries must be unique")
        return cleaned


class ResearchQueryPlan(BaseModel):
    intent: ResearchIntent
    queries: list[str]
    source: Literal["model", "rules"]
    model_used: str = ""
    fallback_reason: str = ""


@dataclass
class CandidatePool:
    papers: list[Paper]
    provenance: dict[str, list[dict[str, str]]]
    decisions: list[dict[str, str]]
    raw_candidate_count: int
    duplicates_merged: int

    @property
    def unique_paper_count(self) -> int:
        return len(self.papers)


@dataclass(frozen=True)
class RankedPaper:
    paper: Paper
    score: float
    signals: dict[str, float | int | bool]


def _strong_identifiers(paper: Paper) -> list[str]:
    keys: list[str] = []
    if doi := normalise_doi(paper.doi):
        keys.append(f"doi:{doi}")
    if paper.arxiv_id.strip():
        keys.append(f"arxiv:{paper.arxiv_id.strip().lower()}")
    keys.extend(
        f"{namespace.casefold()}:{value.casefold()}"
        for namespace, value in sorted(paper.external_ids.items())
        if value.strip()
    )
    return list(dict.fromkeys(keys))


def deduplicate_candidates(candidates: list[tuple[str, str, Paper]]) -> CandidatePool:
    """Deduplicate on strong IDs, then exact normalized title plus year.

    Conflicting DOI matches remain separate. Every source/query observation is
    retained even when its paper merges into an existing canonical record.
    """
    papers: dict[str, Paper] = {}
    provenance: dict[str, list[dict[str, str]]] = {}
    identifiers: dict[str, str] = {}
    title_year: dict[tuple[str, int], str] = {}
    decisions: list[dict[str, str]] = []
    merged_count = 0

    for source, query, incoming_value in candidates:
        incoming = incoming_value.model_copy(deep=True)
        incoming.sources = list(dict.fromkeys([*incoming.sources, source]))
        keys = _strong_identifiers(incoming)
        existing_id = next((identifiers[key] for key in keys if key in identifiers), None)
        title_key = normalise_title(incoming.title)
        title_match = title_year.get((title_key, incoming.year)) if incoming.year else None
        incoming_doi = normalise_doi(incoming.doi)
        conflict = False
        if existing_id is None and title_match is not None:
            existing_doi = normalise_doi(papers[title_match].doi)
            if incoming_doi and existing_doi and incoming_doi != existing_doi:
                conflict = True
                decisions.append(
                    {
                        "incoming_id": incoming.id,
                        "canonical_id": title_match,
                        "decision": "kept_separate_conflicting_doi",
                    }
                )
            else:
                existing_id = title_match

        if existing_id is None:
            canonical_id = incoming.id
            if canonical_id in papers:
                canonical_id = f"{canonical_id}:{len(papers) + 1}"
                incoming.id = canonical_id
            papers[canonical_id] = incoming
            provenance[canonical_id] = []
            decision = "new_candidate"
        else:
            canonical_id = existing_id
            merged = merge_papers(papers[canonical_id], incoming)
            merged.id = canonical_id
            papers[canonical_id] = merged
            merged_count += 1
            decision = "merged_strong_identifier" if keys else "merged_title_and_year"

        for key in _strong_identifiers(papers[canonical_id]):
            identifiers[key] = canonical_id
        if title_key and papers[canonical_id].year:
            title_year[(title_key, papers[canonical_id].year)] = canonical_id
        provenance[canonical_id].append(
            {
                "source": source,
                "query": query,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "source_id": incoming_value.external_ids.get(source, incoming_value.id),
                "doi": incoming_value.doi,
                "url": incoming_value.url,
            }
        )
        if not conflict:
            decisions.append(
                {
                    "incoming_id": incoming_value.id,
                    "canonical_id": canonical_id,
                    "decision": decision,
                }
            )

    return CandidatePool(
        papers=list(papers.values()),
        provenance=provenance,
        decisions=decisions,
        raw_candidate_count=len(candidates),
        duplicates_merged=merged_count,
    )


def _terms(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "what", "how", "does"}
    return {
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text
        ).split()
        if len(token) > 2 and token not in stop
    }


def rank_candidates(
    papers: list[Paper],
    *,
    topic: str,
    question: str,
    queries: list[str],
    provenance: dict[str, list[dict[str, str]]],
    limit: int,
) -> list[RankedPaper]:
    """Greedy relevance/coverage rank; citation counts are deliberately excluded."""
    topic_terms = _terms(topic)
    question_terms = _terms(question)
    query_sets = [(query, _terms(query)) for query in queries]
    remaining = list(papers)
    selected: list[RankedPaper] = []
    covered_sources: set[str] = set()
    covered_queries: set[str] = set()

    while remaining and len(selected) < limit:
        scored: list[tuple[float, Paper, dict[str, float | int | bool]]] = []
        for paper in remaining:
            title_terms = _terms(paper.title)
            abstract_terms = _terms(paper.abstract)
            all_terms = title_terms | abstract_terms | _terms(" ".join(paper.keywords))
            topic_coverage = len(topic_terms & all_terms) / max(len(topic_terms), 1)
            question_coverage = len(question_terms & all_terms) / max(len(question_terms), 1)
            matched_queries = {query for query, terms in query_sets if terms and terms & all_terms}
            sources = set(paper.sources) | {
                record["source"] for record in provenance.get(paper.id, []) if record.get("source")
            }
            new_sources = sources - covered_sources
            new_queries = matched_queries - covered_queries
            has_abstract = bool(paper.abstract.strip())
            score = (
                topic_coverage * 50
                + question_coverage * 30
                + float(has_abstract) * 8
                + min(len(new_sources), 2) * 5
                + min(len(new_queries), 2) * 3
            )
            signals: dict[str, float | int | bool] = {
                "topic_coverage": round(topic_coverage, 3),
                "question_coverage": round(question_coverage, 3),
                "abstract_available": has_abstract,
                "new_source_coverage": len(new_sources),
                "new_query_coverage": len(new_queries),
            }
            scored.append((score, paper, signals))
        score, paper, signals = max(
            scored, key=lambda item: (item[0], item[1].year or 0, item[1].id)
        )
        selected.append(RankedPaper(paper=paper, score=round(score, 3), signals=signals))
        covered_sources.update(paper.sources)
        covered_sources.update(
            record["source"] for record in provenance.get(paper.id, []) if record.get("source")
        )
        covered_queries.update(
            record["query"] for record in provenance.get(paper.id, []) if record.get("query")
        )
        remaining.remove(paper)
    return selected


_INTENT_TERMS: tuple[tuple[ResearchIntent, tuple[str, ...]], ...] = (
    (ResearchIntent.COMPARISON, ("compare", "comparison", "versus", "tradeoff", "trade-off")),
    (ResearchIntent.LINEAGE, ("evolve", "evolution", "lineage", "history", "origin")),
    (ResearchIntent.METHODS, ("method", "methods", "approach", "algorithm", "technique")),
    (
        ResearchIntent.LIMITATIONS,
        ("limitation", "limitations", "gap", "gaps", "weakness", "challenge"),
    ),
    (ResearchIntent.OVERVIEW, ("overview", "survey", "what is", "summarize", "summary")),
)


def classify_intent(question: str) -> ResearchIntent:
    lowered = question.casefold()
    for intent, terms in _INTENT_TERMS:
        if any(term in lowered for term in terms):
            return intent
    return ResearchIntent.OTHER


def _rule_queries(topic: str, question: str, count: int) -> QueryPlanOutput:
    intent = classify_intent(question)
    aspect = {
        ResearchIntent.OVERVIEW: "survey overview",
        ResearchIntent.COMPARISON: "comparative study methods results",
        ResearchIntent.LINEAGE: "history evolution foundational work",
        ResearchIntent.METHODS: "methods approach algorithm evaluation",
        ResearchIntent.LIMITATIONS: "limitations challenges research gaps",
        ResearchIntent.OTHER: "research findings evidence",
    }[intent]
    variants = [
        topic,
        f"{topic} {aspect}",
        f"{topic} {question}",
        f"{topic} recent research",
        f"{topic} foundational papers",
        f"{topic} evidence and evaluation",
    ]
    queries = list(dict.fromkeys(" ".join(item.split()) for item in variants))[:count]
    return QueryPlanOutput(intent=intent, queries=queries)


async def build_query_plan(
    topic: str,
    question: str,
    policy: ResearchProfile,
    *,
    llm: Any = None,
    model: str = "",
    event_log: EventLog | None = None,
    run_id: str = "",
) -> ResearchQueryPlan:
    """Classify intent and build validated queries; deterministic rules are the fallback."""
    result: QueryPlanOutput | None = None
    failure = ""
    if llm is not None:
        prompt = (
            "Classify the research intent and produce distinct academic search queries. "
            f"Return at most {policy.query_count} queries. Every query must include the topic. "
            "Supported intent values: overview, comparison, lineage, methods, "
            "limitations_gaps, other.\n"
            f"Topic: {topic}\nQuestion: {question}"
        )
        try:
            result = await traced_model_call(
                event_log,
                llm,
                stage="fods_query_plan",
                requested_model=model or None,
                run_id=run_id,
                parent_task=None,
                operation=lambda: llm.generate_structured(
                    prompt,
                    QueryPlanOutput,
                    stage="fods_query_plan",
                    temperature=0.0,
                    model=model or None,
                ),
                summarize=lambda value: {"query_count": len(value.queries)},
            )
            result = QueryPlanOutput.model_validate(result.model_dump())
            result.queries = [
                query if topic.casefold() in query.casefold() else f"{topic} {query}"
                for query in result.queries
            ][: policy.query_count]
            result = QueryPlanOutput.model_validate(result.model_dump())
        except Exception as exc:
            failure = f"{type(exc).__name__}: {str(exc)[:160]}"
            result = None
            if event_log is not None:
                event_log.emit(
                    "query_plan_rejected",
                    "structured query plan was rejected; using bounded deterministic queries",
                    reason=failure,
                    profile=policy.profile,
                )
    if result is None:
        result = _rule_queries(topic, question, policy.query_count)

    plan = ResearchQueryPlan(
        intent=result.intent,
        queries=result.queries,
        source="model" if not failure and llm is not None else "rules",
        model_used=model if not failure and llm is not None else "",
        fallback_reason=failure,
    )
    if event_log is not None:
        event_log.emit(
            "research_query_plan",
            f"prepared {len(plan.queries)} validated query/queries for {plan.intent.value}",
            intent=plan.intent.value,
            queries=plan.queries,
            planner=plan.source,
            model=plan.model_used or None,
            fallback_reason=plan.fallback_reason,
            profile=policy.profile,
        )
    return plan
