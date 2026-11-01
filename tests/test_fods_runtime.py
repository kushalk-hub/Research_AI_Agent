from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

import pytest

from fods.fixtures import FIXTURE_PAPERS
from fods.models import TaskPlan
from fods.plan import PlanError, validate_plan
from fods.planner import canonicalize_llm_research_plan, deterministic_plan
from fods.runtime import PriorityQueue, run_plan
from fods.tools import ToolContext, create_registry, output_path
from rla.models import Paper


async def _empty_search(_query: str, _limit: int):
    return []


def _registry():
    return create_registry({name: _empty_search for name in FIXTURE_PAPERS})


def _context(
    tmp_path: Path, *, output: str = "brief.md", llm=None, fail_sources=None
) -> ToolContext:
    async def delay(_source: str) -> None:
        await asyncio.sleep(0.02)

    return ToolContext(
        run_id="test-run",
        mode="simulate",
        topic="graph attention networks",
        question="How does graph attention use neighborhoods?",
        output_path=output,
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        llm=llm,
        metadata={
            "fixtures": FIXTURE_PAPERS,
            "simulated_delay": delay,
            "fail_sources": fail_sources or set(),
        },
    )


def _plan(output: str = "brief.md", reuse: bool = False) -> TaskPlan:
    return deterministic_plan(
        "Research graph attention networks",
        "graph attention networks",
        "How does graph attention use neighborhoods?",
        output,
        list(FIXTURE_PAPERS),
        reuse_context=reuse,
    )


def test_cycle_is_rejected_before_any_tool_call(tmp_path):
    calls = 0

    async def counted(_query: str, _limit: int):
        nonlocal calls
        calls += 1
        return []

    registry = create_registry({name: counted for name in FIXTURE_PAPERS})
    plan = _plan()
    plan.tasks[0].depends_on = [plan.tasks[1].id]
    plan.tasks[1].depends_on = [plan.tasks[0].id]

    with pytest.raises(PlanError, match="dependency cycle"):
        asyncio.run(run_plan(plan, registry, _context(tmp_path)))

    assert calls == 0


def test_normal_research_runtime_never_calls_graph_mutations(tmp_path, monkeypatch):
    import fods.knowledge_graph as graph

    def forbidden(*_args, **_kwargs):
        raise AssertionError("normal research invoked an optional graph operation")

    monkeypatch.setattr(graph, "update_snapshot", forbidden)
    monkeypatch.setattr(graph, "publish", forbidden)

    result = asyncio.run(run_plan(_plan(), _registry(), _context(tmp_path), concurrency=3))

    assert result.succeeded
    assert (tmp_path / "brief.md").exists()


def test_simulated_source_calls_are_concurrently_dispatched_and_saved_context_reused(tmp_path):
    first = asyncio.run(run_plan(_plan(), _registry(), _context(tmp_path), concurrency=3))

    assert first.succeeded
    source_starts = [
        event["seq"]
        for event in first.events
        if event["kind"] == "task_started" and event["payload"]["task_id"].startswith("search_")
    ]
    first_source_complete = next(
        event["seq"]
        for event in first.events
        if event["kind"] == "task_completed" and event["payload"]["task_id"].startswith("search_")
    )
    assert len(source_starts) == 3
    assert max(source_starts) < first_source_complete
    assert (tmp_path / "brief.md").exists()
    snapshot = Path(first.states["merge"].result["snapshot_path"])
    snapshot_before = snapshot.read_bytes()

    reuse_plan = _plan("second-brief.md", reuse=True)
    second = asyncio.run(
        run_plan(
            reuse_plan, _registry(), _context(tmp_path, output="second-brief.md"), concurrency=3
        )
    )
    assert second.succeeded
    assert not any(task.startswith("search_") for task in second.states)
    assert "merge" not in second.states
    assert second.states["load_context"].state.value == "completed"
    assert snapshot.read_bytes() == snapshot_before
    assert (tmp_path / "second-brief.md").exists()


def test_persistent_single_source_failure_is_bounded_and_uses_partial_context(tmp_path):
    result = asyncio.run(
        run_plan(
            _plan(),
            _registry(),
            _context(tmp_path, fail_sources={"arxiv"}),
            concurrency=3,
            max_attempts=2,
        )
    )

    assert result.succeeded, (
        result.termination_reason,
        {task_id: record.state.value for task_id, record in result.states.items()},
        [
            (event["kind"], event["payload"].get("task_id"), event["message"])
            for event in result.events
            if event["kind"] in {"task_failed", "task_blocked"}
        ],
    )
    assert result.states["search_arxiv"].attempts == 2
    assert result.states["search_arxiv"].state.value == "failed"
    assert result.states["merge"].state.value == "completed"
    assert result.states["write"].state.value == "completed"
    assert result.termination_reason == "completed_with_partial_sources"
    assert (tmp_path / "brief.md").exists()
    partial = next(event for event in result.events if event["kind"] == "partial_source_set")
    assert len(partial["payload"]["successful_sources"]) == 2


def test_deep_profile_keeps_searching_after_two_sources_until_target_or_budget(tmp_path):
    async def search(name: str):
        if name == "arxiv":
            await asyncio.sleep(0.08)
        else:
            await asyncio.sleep(0.01)
        return []

    registry = create_registry(
        {
            "semantic_scholar": lambda _query, _limit: search("semantic_scholar"),
            "openalex": lambda _query, _limit: search("openalex"),
            "arxiv": lambda _query, _limit: search("arxiv"),
        }
    )
    context = _context(tmp_path)
    context.mode = "live"
    context.metadata["research_policy"] = {
        "profile": "deep",
        "target_unique_papers": 25,
        "max_retained_papers": 50,
        "max_evidence_papers": 8,
        "budget_seconds": 600,
        "source_limit": 3,
        "per_query_limit": 10,
        "query_count": 4,
        "minimum_sources": 3,
        "early_quorum": False,
    }

    result = asyncio.run(run_plan(_plan(), registry, context, concurrency=3))

    completed_sources = {
        event["payload"].get("tool")
        for event in result.events
        if event["kind"] == "tool_call_completed"
        and str(event["payload"].get("tool", "")).startswith("search_")
    }
    assert len(completed_sources) == 3
    assert not any(
        event["kind"] == "task_cancelled"
        and event["payload"].get("recovery_action") == "source_quorum_reached"
        for event in result.events
    )


def test_research_budget_stops_source_work_and_returns_labeled_partial_context(tmp_path):
    async def search(name: str):
        await asyncio.sleep(0.01 if name != "arxiv" else 0.2)
        return [Paper.model_validate(FIXTURE_PAPERS[name][0])]

    registry = create_registry(
        {
            "semantic_scholar": lambda _query, _limit: search("semantic_scholar"),
            "openalex": lambda _query, _limit: search("openalex"),
            "arxiv": lambda _query, _limit: search("arxiv"),
        }
    )
    context = _context(tmp_path)
    context.mode = "live"
    context.metadata["research_policy"] = {
        "profile": "deep",
        "target_unique_papers": 25,
        "candidate_limit": 100,
        "minimum_sources": 2,
        "early_quorum": False,
    }

    result = asyncio.run(
        run_plan(_plan(), registry, context, concurrency=3, research_budget_seconds=0.04)
    )
    assert result.succeeded, (
        result.termination_reason,
        {task_id: record.state.value for task_id, record in result.states.items()},
        [(event["kind"], event["payload"].get("task_id")) for event in result.events],
    )
    assert result.termination_reason == "completed_with_budget_limit"
    assert any(
        event["kind"] == "research_stopping"
        and event["payload"]["stop_reason"] == "research_budget_exhausted"
        for event in result.events
    )


def test_deep_budget_keeps_checkpoint_and_partial_context_answerable(tmp_path):
    names = list(FIXTURE_PAPERS)

    async def varied_search(source: str, _query: str, limit: int):
        await asyncio.sleep(0.5 if source == names[-1] else 0.01)
        return [Paper.model_validate(record) for record in FIXTURE_PAPERS[source][:limit]]

    registry = create_registry(
        {
            name: (lambda query, limit, name=name: varied_search(name, query, limit))
            for name in names
        }
    )
    plan = deterministic_plan(
        "Request",
        "Graph attention",
        "Compare graph attention methods",
        "brief.md",
        names,
        queries=["Graph attention", "Graph attention limitations"],
    )
    context = _context(tmp_path)
    context.mode = "live"
    context.metadata["research_policy"] = {
        "profile": "deep",
        "target_unique_papers": 25,
        "max_retained_papers": 50,
        "candidate_limit": 100,
        "minimum_sources": 2,
        "early_quorum": False,
    }

    result = asyncio.run(
        run_plan(plan, registry, context, concurrency=3, research_budget_seconds=0.15)
    )

    assert result.succeeded, (
        result.termination_reason,
        {task_id: (record.state.value, record.error) for task_id, record in result.states.items()},
        [
            (event["kind"], event["payload"], event["message"])
            for event in result.events
            if event["kind"] in {"task_failed", "task_blocked"}
        ],
    )
    assert result.states["acquisition_checkpoint"].state.value == "completed"
    assert result.states["merge"].state.value == "completed"
    assert result.states["write"].state.value == "completed"


def test_deep_profile_runs_second_query_round_when_first_round_is_under_target(tmp_path):
    calls: list[tuple[str, str]] = []

    async def search(source: str, query: str):
        calls.append((source, query))
        await asyncio.sleep(0.005)
        return [Paper.model_validate(FIXTURE_PAPERS[source][0])]

    names = list(FIXTURE_PAPERS)
    registry = create_registry(
        {name: (lambda query, _limit, name=name: search(name, query)) for name in names}
    )
    plan = deterministic_plan(
        "Request",
        "Graph attention",
        "Compare graph attention methods",
        "deep.md",
        names,
        queries=["Graph attention", "Graph attention comparative methods"],
    )
    context = _context(tmp_path, output="target.md")
    context.mode = "live"
    context.metadata["research_policy"] = {
        "profile": "deep",
        "target_unique_papers": 25,
        "max_retained_papers": 50,
        "candidate_limit": 100,
        "minimum_sources": 3,
        "early_quorum": False,
    }

    result = asyncio.run(run_plan(plan, registry, context, concurrency=3))

    assert len(calls) == len(names) * 2
    assert {query for _source, query in calls} == {
        "Graph attention",
        "Graph attention comparative methods",
    }
    assert any(event["kind"] == "query_round_completed" for event in result.events)
    assert result.states["search_arxiv_q2"].state.value == "completed"


def test_query_expansion_skips_network_calls_when_unique_target_is_already_met(tmp_path):
    calls: list[tuple[str, str]] = []

    async def search(source: str, query: str):
        calls.append((source, query))
        if query != "Graph attention":
            pytest.fail("round-one source call should be skipped after target is met")
        return [
            Paper(
                id=f"{source}-{index}",
                title=f"Graph Attention Study {source} {index}",
                year=2020 + index,
                doi=f"10.5555/{source}-{index}",
                abstract="Graph attention method for neighborhood evidence.",
                sources=[source],
            )
            for index in range(2)
        ]

    names = list(FIXTURE_PAPERS)
    registry = create_registry(
        {name: (lambda query, _limit, name=name: search(name, query)) for name in names}
    )
    plan = deterministic_plan(
        "Request",
        "Graph attention",
        "Compare graph attention methods",
        "target.md",
        names,
        queries=["Graph attention", "Graph attention comparative methods"],
    )
    context = _context(tmp_path, output="target.md")
    context.mode = "live"
    context.metadata["research_policy"] = {
        "profile": "deep",
        "target_unique_papers": 4,
        "max_retained_papers": 50,
        "candidate_limit": 100,
        "minimum_sources": 3,
        "early_quorum": False,
    }

    result = asyncio.run(run_plan(plan, registry, context, concurrency=3))

    assert len(calls) == len(names)
    assert all(record.state.value == "completed" for record in result.states.values()), (
        result.termination_reason,
        {task_id: record.state.value for task_id, record in result.states.items()},
        [
            (event["kind"], event["payload"].get("task_id"), event["message"])
            for event in result.events
            if event["kind"] in {"task_failed", "task_blocked"}
        ],
    )
    assert all(
        record.result.get("status") == "skipped_stop_criteria"
        for record in result.states.values()
        if record.task.id.endswith("_q2")
    )
    assert any(
        event["kind"] == "research_stopping"
        and event["payload"]["stop_reason"] == "unique_paper_target_reached"
        for event in result.events
    )


def test_fewer_than_two_successful_sources_blocks_context_and_output(tmp_path):
    result = asyncio.run(
        run_plan(
            _plan(),
            _registry(),
            _context(tmp_path, fail_sources={"arxiv", "openalex"}),
            concurrency=3,
            max_attempts=2,
        )
    )

    assert not result.succeeded
    assert result.states["merge"].state.value == "blocked"
    assert result.states["write"].state.value == "blocked"
    assert not (tmp_path / "brief.md").exists()


def test_invalid_citation_blocks_write_and_records_recovery(tmp_path):
    class BadAnswerModel:
        async def generate_text(self, *_args, **_kwargs):
            return "The claim has no supporting source [P999]."

    result = asyncio.run(
        run_plan(
            _plan(),
            _registry(),
            _context(tmp_path, llm=BadAnswerModel()),
            concurrency=3,
        )
    )

    assert not result.succeeded
    assert result.states["citation_check"].state.value == "failed"
    assert result.states["write"].state.value == "blocked"
    assert not (tmp_path / "brief.md").exists()
    failed = next(event for event in result.events if event["kind"] == "task_failed")
    assert failed["payload"]["recovery_action"] == "block_output_write"
    assert failed["payload"]["details"]["unknown"] == ["P999"]
    validation = next(event for event in result.events if event["kind"] == "citation_validation")
    assert validation["payload"]["valid"] is False
    assert validation["payload"]["recovery_action"] == "block_output_write"
    assert not any(event["kind"] == "brief_saved" for event in result.events)
    assert not any(
        event["kind"] == "tool_call_completed"
        and event["payload"].get("tool") == "write_cited_brief"
        for event in result.events
    )


def test_evidence_selection_obeys_token_budget_and_maps_citations_to_papers(tmp_path):
    context = _context(tmp_path)
    context.metadata["research_policy"] = {
        "profile": "quick",
        "evidence_token_budget": 1000,
        "max_evidence_papers": 6,
    }
    context.metadata["fixtures"] = {
        source: [
            {**record, "abstract": (record.get("abstract", "") + " evidence") * 80}
            for record in records
        ]
        for source, records in FIXTURE_PAPERS.items()
    }

    result = asyncio.run(run_plan(_plan(), _registry(), context, concurrency=3))

    selection = next(event for event in result.events if event["kind"] == "evidence_selected")
    assert selection["payload"]["estimated_evidence_units"] <= 1000
    assert selection["payload"]["evidence_budget_limit"] == 1000
    validation = next(event for event in result.events if event["kind"] == "citation_validation")
    mapping = validation["payload"]["claim_evidence_map"]
    assert validation["payload"]["valid"] is True
    assert mapping
    assert all(item["paper_ids"] for item in mapping)
    assert all(item["support_status"] == "unverified" for item in mapping)


def test_user_cancellation_is_recorded_and_never_saves_a_brief(tmp_path):
    cancelled = Event()
    cancelled.set()
    result = asyncio.run(run_plan(_plan(), _registry(), _context(tmp_path), cancel_event=cancelled))

    assert not result.succeeded
    assert result.termination_reason == "cancelled"
    assert not (tmp_path / "brief.md").exists()
    assert any(event["kind"] == "run_cancel_requested" for event in result.events)
    assert all(record.state.value == "cancelled" for record in result.states.values())


@pytest.mark.parametrize(
    "requested",
    [
        "../outside.md",
        "..\\outside.md",
        "folder/../../outside.md",
        "folder\\..\\..\\outside.md",
        "folder/..\\..\\outside.md",
        "/outside.md",
        "C:\\outside.md",
        "\\\\server\\share\\outside.md",
    ],
)
def test_output_path_rejects_cross_platform_workspace_escapes(tmp_path, requested):
    with pytest.raises(ValueError, match="inside the approved workspace"):
        output_path(tmp_path, requested)

    with pytest.raises(PlanError, match="inside the approved workspace"):
        validate_plan(_plan(requested), _registry().schemas(), workspace=tmp_path)


@pytest.mark.parametrize(
    "requested",
    [
        "brief.md",
        "briefs/output.md",
        "briefs\\output.md",
        "reports/2026/final.md",
        "report..md",
    ],
)
def test_output_path_accepts_portable_nested_paths_and_double_dots(tmp_path, requested):
    destination = output_path(tmp_path, requested)

    assert destination.is_relative_to(tmp_path.resolve())
    assert destination != tmp_path.resolve()


def test_output_path_rejects_existing_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    try:
        (workspace / "linked").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    requested = "linked/escape.md"
    with pytest.raises(ValueError, match="inside the approved workspace"):
        output_path(workspace, requested)

    with pytest.raises(PlanError, match="inside the approved workspace"):
        validate_plan(_plan(requested), _registry().schemas(), workspace=workspace)


def test_priority_queue_uses_priority_then_fifo_order():
    queue = PriorityQueue()
    queue.put(10, "first-low")
    queue.put(30, "high")
    queue.put(10, "second-low")

    assert [queue.get(), queue.get(), queue.get()] == ["high", "first-low", "second-low"]


def test_plan_output_path_and_tool_args_are_checked():
    plan = _plan()
    plan.tasks[-1].args["output_path"] = "elsewhere.md"
    with pytest.raises(PlanError, match="explicitly named plan output path"):
        validate_plan(plan, _registry().schemas())


def test_llm_plan_canonicalization_records_repairs_and_restores_required_edges():
    proposed = _plan()
    proposed.tasks[1].tool = "openalex"
    for task in proposed.tasks:
        task.depends_on = []

    normalized, repairs = canonicalize_llm_research_plan(proposed, list(FIXTURE_PAPERS))

    assert repairs
    assert normalized.tasks[1].tool == "search_openalex"
    levels = validate_plan(normalized, _registry().schemas())
    assert levels[0] == ["search_semantic_scholar", "search_openalex", "search_arxiv"]
