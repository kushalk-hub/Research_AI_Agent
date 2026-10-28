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

    assert result.succeeded
    assert result.states["search_arxiv"].attempts == 2
    assert result.states["search_arxiv"].state.value == "failed"
    assert result.states["merge"].state.value == "completed"
    assert result.states["write"].state.value == "completed"
    assert result.termination_reason == "completed_with_partial_sources"
    assert (tmp_path / "brief.md").exists()
    partial = next(event for event in result.events if event["kind"] == "partial_source_set")
    assert len(partial["payload"]["successful_sources"]) == 2


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


def test_user_cancellation_is_recorded_and_never_saves_a_brief(tmp_path):
    cancelled = Event()
    cancelled.set()
    result = asyncio.run(run_plan(_plan(), _registry(), _context(tmp_path), cancel_event=cancelled))

    assert not result.succeeded
    assert result.termination_reason == "cancelled"
    assert not (tmp_path / "brief.md").exists()
    assert any(event["kind"] == "run_cancel_requested" for event in result.events)
    assert all(record.state.value == "cancelled" for record in result.states.values())


def test_output_path_cannot_escape_workspace(tmp_path):
    with pytest.raises(ValueError, match="inside the approved workspace"):
        output_path(tmp_path, "..\\outside.md")

    plan = _plan("..\\outside.md")
    with pytest.raises(PlanError, match="inside the approved workspace"):
        validate_plan(plan, _registry().schemas(), workspace=tmp_path)


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
