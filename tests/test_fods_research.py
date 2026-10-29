from __future__ import annotations

import pytest
from pydantic import ValidationError

from fods.planner import deterministic_plan
from fods.research import (
    ResearchIntent,
    build_query_plan,
    deduplicate_candidates,
    profile_for,
    rank_candidates,
)
from rla.models import Paper


def test_deep_profile_sets_bounded_research_targets_and_accepts_tighter_overrides():
    policy = profile_for("deep", target_unique_papers=22, budget_seconds=300)

    assert policy.target_unique_papers == 22
    assert policy.max_retained_papers == 50
    assert policy.max_evidence_papers == 8
    assert policy.budget_seconds == 300
    assert policy.source_limit == 5
    with pytest.raises(ValidationError):
        profile_for("deep", max_retained_papers=51)


async def test_quick_and_deep_query_plans_are_bounded_and_classify_intent():
    quick_policy = profile_for("quick")
    deep_policy = profile_for("deep")

    quick = await build_query_plan(
        "Graph attention", "Compare methods and limitations", quick_policy
    )
    deep = await build_query_plan("Graph attention", "Compare methods and limitations", deep_policy)

    assert quick.intent is ResearchIntent.COMPARISON
    assert len(quick.queries) == 1
    assert deep.intent is ResearchIntent.COMPARISON
    assert len(deep.queries) == deep_policy.query_count
    assert len(set(deep.queries)) == len(deep.queries)
    assert all("Graph attention" in query for query in deep.queries)


async def test_query_planner_validates_and_records_structured_model_output():
    class FakeModel:
        async def generate_structured(self, _prompt, schema, **_kwargs):
            return schema(intent="lineage", queries=["Topic lineage", "Topic evolution"])

    policy = profile_for("deep", query_count=2)
    plan = await build_query_plan(
        "Topic", "How has it evolved?", policy, llm=FakeModel(), model="ollama/qwen3:4b"
    )

    assert plan.intent is ResearchIntent.LINEAGE
    assert plan.queries == ["Topic lineage", "Topic evolution"]
    assert plan.model_used == "ollama/qwen3:4b"
    assert plan.source == "model"


async def test_invalid_or_failed_model_query_plan_falls_back_to_validated_rules():
    class InvalidModel:
        async def generate_structured(self, _prompt, schema, **_kwargs):
            return schema(intent="comparison", queries=[" "])

    policy = profile_for("deep", query_count=3)
    plan = await build_query_plan("Topic", "What are limitations?", policy, llm=InvalidModel())

    assert plan.source == "rules"
    assert plan.intent is ResearchIntent.LIMITATIONS
    assert len(plan.queries) == 3


def test_candidate_dedup_prefers_strong_ids_and_keeps_ambiguous_title_matches_separate():
    candidates = [
        (
            "openalex",
            "graph attention",
            Paper(id="oa1", title="Graph Attention", year=2020, doi="10.1234/shared", abstract="A"),
        ),
        (
            "crossref",
            "graph attention methods",
            Paper(
                id="cr1",
                title="Graph Attention",
                year=2020,
                doi="https://doi.org/10.1234/shared",
                abstract="Longer abstract",
            ),
        ),
        (
            "arxiv",
            "graph attention",
            Paper(
                id="ar1",
                title="Graph Attention",
                year=2020,
                doi="10.1234/other",
                abstract="Separate paper",
            ),
        ),
        (
            "dblp",
            "graph attention",
            Paper(id="d1", title="Graph Attention", year=2021, abstract="Later work"),
        ),
    ]

    pool = deduplicate_candidates(candidates)

    assert pool.raw_candidate_count == 4
    assert pool.unique_paper_count == 3
    assert pool.duplicates_merged == 1
    merged = next(paper for paper in pool.papers if paper.doi == "10.1234/shared")
    assert set(merged.sources) == {"openalex", "crossref"}
    assert len(pool.provenance[merged.id]) == 2
    assert any(item["decision"] == "kept_separate_conflicting_doi" for item in pool.decisions)


def test_candidate_ranking_is_query_relevant_transparent_and_capped():
    relevant = Paper(
        id="p-relevant",
        title="Graph Attention Networks",
        year=2023,
        abstract="Graph attention compares local neighborhood aggregation methods.",
        sources=["arxiv"],
    )
    popular_but_off_topic = Paper(
        id="p-popular",
        title="A survey of unrelated systems",
        year=2025,
        abstract="A broad survey of unrelated systems.",
        citation_count=100_000,
        sources=["openalex"],
    )

    ranked = rank_candidates(
        [popular_but_off_topic, relevant],
        topic="graph attention",
        question="How do neighborhood methods compare?",
        queries=["graph attention neighborhood methods"],
        provenance={},
        limit=1,
    )

    assert [item.paper.id for item in ranked] == ["p-relevant"]
    assert ranked[0].score > 0
    assert ranked[0].signals["topic_coverage"] > 0


def test_planner_emits_independent_source_query_tasks_with_exact_validated_queries():
    plan = deterministic_plan(
        "Request",
        "Graph attention",
        "Compare methods",
        "brief.md",
        ["openalex", "arxiv"],
        queries=["Graph attention methods", "Graph attention evaluation"],
        per_query_limit=12,
    )
    source_tasks = [task for task in plan.tasks if task.tool.startswith("search_")]

    assert len(source_tasks) == 4
    assert {task.id for task in source_tasks} == {
        "search_openalex_q1",
        "search_openalex_q2",
        "search_arxiv_q1",
        "search_arxiv_q2",
    }
    assert {task.args["query"] for task in source_tasks} == {
        "Graph attention methods",
        "Graph attention evaluation",
    }
    assert all(task.args["limit"] == 12 for task in source_tasks)
    assert all(not task.depends_on for task in source_tasks if task.args["round_index"] == 0)
    assert all(
        task.depends_on == ["acquisition_checkpoint"]
        for task in source_tasks
        if task.args["round_index"] == 1
    )
