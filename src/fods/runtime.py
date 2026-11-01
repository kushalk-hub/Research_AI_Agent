"""DAG validation, ready-queue scheduling, bounded retries, and trace events."""

from __future__ import annotations

import asyncio
import heapq
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

from fods.events import EventLog
from fods.models import RunResult, TaskPlan, TaskRecord, TaskState
from fods.plan import PlanError, validate_plan
from fods.research import deduplicate_candidates
from fods.tools import ToolContext, ToolRegistry
from rla.models import Paper


class RetryableToolError(RuntimeError):
    """A transient tool failure that may be retried within the run bound."""


class ToolRejectedError(RuntimeError):
    """A policy or evidence rejection that must not be retried blindly."""

    def __init__(self, message: str, recovery_action: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.recovery_action = recovery_action
        self.details = details or {}


class TraceStack:
    """A per-task stack; concurrency never interleaves frames from different tasks."""

    def __init__(self, run_id: str) -> None:
        self.frames = [f"run:{run_id}"]

    def push(self, frame: str) -> list[str]:
        self.frames.append(frame)
        return list(self.frames)

    def pop(self) -> tuple[str, list[str]]:
        frame = self.frames.pop()
        return frame, list(self.frames)


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    summary: dict[str, Any] = {}
    if isinstance(result.get("papers"), list):
        summary["paper_count"] = len(result["papers"])
    if isinstance(result.get("evidence"), list):
        summary["evidence_count"] = len(result["evidence"])
        summary["citations"] = [item.get("citation") for item in result["evidence"]]
    if isinstance(result.get("answer"), str):
        summary["answer_chars"] = len(result["answer"])
    for key in (
        "source",
        "path",
        "saved",
        "citations_validated",
        "context_hash",
        "snapshot_path",
        "duplicates_merged",
        "source_count",
        "query",
        "retrieved_at",
        "cache_policy",
        "round_index",
        "valid",
        "cache_reused",
        "batch_key",
        "model",
        "schema_version",
        "papers_enriched",
        "concept_count",
        "inferred_relation_count",
        "context_id",
        "discovered_count",
        "resolved_edges",
        "status",
        "seed_paper_id",
        "candidate_count",
        "reason",
        "candidate_paper_ids",
        "parent_context_id",
        "reference_record_count",
    ):
        if key in result:
            summary[key] = result[key]
    return summary


class FifoQueue:
    def __init__(self) -> None:
        self._items: deque[tuple[int, str]] = deque()

    def put(self, priority: int, task_id: str) -> None:
        del priority
        self._items.append((0, task_id))

    def get(self) -> str:
        return self._items.popleft()[1]

    def __bool__(self) -> bool:
        return bool(self._items)

    def snapshot(self) -> list[dict[str, Any]]:
        return [{"task_id": task_id} for _priority, task_id in self._items]


class PriorityQueue:
    """Static user priority; ties retain FIFO insertion order."""

    def __init__(self) -> None:
        self._items: list[tuple[int, int, str]] = []
        self._sequence = 0

    def put(self, priority: int, task_id: str) -> None:
        heapq.heappush(self._items, (-priority, self._sequence, task_id))
        self._sequence += 1

    def get(self) -> str:
        return heapq.heappop(self._items)[2]

    def __bool__(self) -> bool:
        return bool(self._items)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {"task_id": task_id, "priority": -priority, "sequence": sequence}
            for priority, sequence, task_id in sorted(self._items)
        ]


def make_queue(policy: str) -> FifoQueue | PriorityQueue:
    if policy == "fifo":
        return FifoQueue()
    if policy == "priority":
        return PriorityQueue()
    raise ValueError("schedule must be 'fifo' or 'priority'")


async def run_plan(
    plan: TaskPlan,
    registry: ToolRegistry,
    context: ToolContext,
    *,
    schedule: str = "fifo",
    concurrency: int = 3,
    max_attempts: int = 2,
    event_path: Path | None = None,
    event_sink: Callable[[Any], None] | None = None,
    event_log: EventLog | None = None,
    cancel_event: Event | None = None,
    research_budget_seconds: int | None = None,
    research_profile: dict[str, Any] | None = None,
    workflow_budget_seconds: int | None = None,
) -> RunResult:
    """Validate before tool calls, then schedule only tasks whose inputs completed."""
    if concurrency < 1 or max_attempts < 1:
        raise ValueError("concurrency and max_attempts must be positive")
    if event_log is not None and (event_path is not None or event_sink is not None):
        raise ValueError("pass event_log or event_path/event_sink, not both")
    log = event_log or EventLog(event_path, event_sink)
    run_started = time.perf_counter()
    run_id = context.run_id or uuid.uuid4().hex[:12]
    base_context = replace(context, run_id=run_id)
    profile = dict(context.metadata.get("research_policy", research_profile or {}))
    minimum_sources = int(profile.get("minimum_sources", 2))
    acquisition_budget = (
        research_budget_seconds
        if research_budget_seconds is not None
        else profile.get("budget_seconds")
    )
    acquisition_deadline = (
        time.monotonic() + max(0.0, float(acquisition_budget))
        if acquisition_budget is not None
        else None
    )
    workflow_deadline = (
        time.monotonic() + max(0.0, float(workflow_budget_seconds))
        if workflow_budget_seconds is not None
        else None
    )
    request_deadlines = [
        deadline for deadline in (acquisition_deadline, workflow_deadline) if deadline is not None
    ]
    base_context.metadata["outbound_request_deadline"] = (
        min(request_deadlines) if request_deadlines else None
    )
    acquisition_stop_reason = ""
    workflow_stop_reason = ""
    log.emit(
        "plan_received",
        "structured plan received",
        mode=context.mode,
        source_cache_mode=context.metadata.get("source_cache_mode", "configured"),
        planner=context.metadata.get("planner", "deterministic"),
        topic=plan.topic,
        question=plan.question,
        output_path=plan.output_path,
        tasks=base_context.metadata.get("proposed_tasks")
        or [task.model_dump(mode="json") for task in plan.tasks],
        tool_calls=0,
    )
    repairs = base_context.metadata.get("planner_repairs", [])
    if repairs:
        log.emit(
            "plan_repaired",
            f"runtime canonicalized {len(repairs)} research-plan details",
            repairs=repairs,
            tasks=[task.model_dump(mode="json") for task in plan.tasks],
            tool_calls=0,
        )

    try:
        levels = validate_plan(plan, registry.schemas(), workspace=context.workspace)
    except PlanError as exc:
        log.emit("plan_rejected", str(exc), mode=context.mode, tool_calls=0)
        raise

    log.emit(
        "plan_validated",
        f"plan accepted: {len(plan.tasks)} tasks, {len(levels)} topological levels",
        mode=context.mode,
        schedule=schedule,
        levels=levels,
        dependency_counts={task.id: len(task.depends_on) for task in plan.tasks},
        tool_calls=0,
        tasks=[task.model_dump(mode="json") for task in plan.tasks],
    )
    queue = make_queue(schedule)
    records = {task.id: TaskRecord(task=task) for task in plan.tasks}
    by_id = {task.id: task for task in plan.tasks}
    dependents: dict[str, list[str]] = {task.id: [] for task in plan.tasks}
    for task in plan.tasks:
        for dependency in task.depends_on:
            dependents[dependency].append(task.id)

    outputs: dict[str, Any] = {}
    running: dict[asyncio.Task[Any], str] = {}
    dispatch_counter = 0

    def completed_source_names() -> set[str]:
        return {
            record.task.tool.removeprefix("search_")
            for record in records.values()
            if record.task.tool.startswith("search_")
            and record.state is TaskState.COMPLETED
            and outputs.get(record.task.id, {}).get("status") != "skipped_stop_criteria"
        }

    def candidate_counts() -> tuple[int, int]:
        candidates: list[tuple[str, str, Paper]] = []
        for value in outputs.values():
            if (
                not isinstance(value, dict)
                or not value.get("source")
                or value.get("status") == "skipped_stop_criteria"
            ):
                continue
            for item in value.get("papers", []):
                candidates.append(
                    (
                        str(value["source"]),
                        str(value.get("query", "")),
                        Paper.model_validate(item),
                    )
                )
        pool = deduplicate_candidates(candidates)
        return len(candidates), pool.unique_paper_count

    def enqueue(task_id: str) -> None:
        nonlocal dispatch_counter
        record = records[task_id]
        record.state = TaskState.READY
        queue.put(record.task.priority, task_id)
        log.emit(
            "task_ready",
            f"{task_id} is ready",
            task_id=task_id,
            priority=record.task.priority,
            queue_policy=schedule,
            queue_position=dispatch_counter,
            prerequisites=list(record.task.depends_on),
            remaining_prerequisites=sum(
                records[dependency].state is not TaskState.COMPLETED
                for dependency in record.task.depends_on
            ),
            ready_reason="source_task" if not record.task.depends_on else "prerequisites_satisfied",
            ready_queue=queue.snapshot(),
        )
        log.emit(
            "queue_updated",
            f"{task_id} enqueued in {schedule} ready queue",
            operation="enqueue",
            task_id=task_id,
            schedule=schedule,
            priority=record.task.priority,
            ready_queue=queue.snapshot(),
        )
        dispatch_counter += 1

    for task in plan.tasks:
        if not task.depends_on:
            enqueue(task.id)

    terminal_states = {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    }

    def block_descendants(failed_id: str, reason: str) -> None:
        for child_id in dependents[failed_id]:
            child = records[child_id]
            if child.state in terminal_states:
                continue
            dependencies_now = [records[dep] for dep in child.task.depends_on]
            pending = [dep for dep in dependencies_now if dep.state is not TaskState.COMPLETED]
            source_quorum_ready = (
                child.task.tool in {"merge_and_save_context", "acquisition_checkpoint"}
                and all(dependency.state in terminal_states for dependency in dependencies_now)
                and len(
                    {
                        dependency.task.tool.removeprefix("search_")
                        for dependency in dependencies_now
                        if dependency.state is TaskState.COMPLETED
                        and dependency.task.tool.startswith("search_")
                        and outputs.get(dependency.task.id, {}).get("status")
                        != "skipped_stop_criteria"
                    }
                )
                >= minimum_sources
            )
            log.emit(
                "dependency_updated",
                f"{failed_id} finished; {len(pending)} prerequisite(s) remain for {child_id}",
                task_id=child_id,
                completed_dependency=failed_id,
                prerequisite_states={dep.task.id: dep.state.value for dep in dependencies_now},
                completed_prerequisites=sum(
                    dependency.state is TaskState.COMPLETED for dependency in dependencies_now
                ),
                remaining_prerequisites=len(pending),
                ready_eligible=not pending or source_quorum_ready,
                readiness_rule=(
                    "minimum_source_quorum"
                    if source_quorum_ready
                    else "all_prerequisites_completed"
                ),
            )
            if child.task.tool == "acquisition_checkpoint" and any(
                dependency.state not in terminal_states for dependency in dependencies_now
            ):
                continue
            if child.task.tool in {"merge_and_save_context", "acquisition_checkpoint"}:
                dependencies = dependencies_now
                if any(dependency.state not in terminal_states for dependency in dependencies):
                    continue
                completed_sources = [
                    dependency
                    for dependency in dependencies
                    if dependency.state is TaskState.COMPLETED
                    and outputs.get(dependency.task.id, {}).get("status") != "skipped_stop_criteria"
                ]
                successful_names = {
                    dependency.task.tool.removeprefix("search_")
                    for dependency in completed_sources
                    if dependency.task.tool.startswith("search_")
                }
                if len(successful_names) >= minimum_sources:
                    failed_sources = [
                        dependency.task.id
                        for dependency in dependencies
                        if dependency.state is not TaskState.COMPLETED
                    ]
                    if failed_sources:
                        log.emit(
                            "partial_source_set",
                            f"continuing with {len(completed_sources)} successful sources",
                            task_id=child_id,
                            successful_sources=[
                                dependency.task.id for dependency in completed_sources
                            ],
                            unavailable_sources=failed_sources,
                            minimum_sources=minimum_sources,
                        )
                    if child.state is TaskState.PLANNED:
                        enqueue(child_id)
                    continue
            dependency_records = [records[dep] for dep in child.task.depends_on]
            if all(dependency.state is TaskState.COMPLETED for dependency in dependency_records):
                if child.state is TaskState.PLANNED:
                    enqueue(child_id)
                continue
            failed_dependencies = [
                dependency
                for dependency in dependency_records
                if dependency.state in {TaskState.FAILED, TaskState.BLOCKED, TaskState.CANCELLED}
            ]
            if not failed_dependencies:
                continue
            child.state = TaskState.BLOCKED
            failed_dependency = failed_dependencies[0]
            child.error = f"blocked by {failed_dependency.task.id}: {reason}"
            log.emit(
                "task_blocked",
                f"{child_id} blocked because {failed_dependency.task.id} did not complete",
                task_id=child_id,
                failed_dependency=failed_dependency.task.id,
            )
            block_descendants(child_id, child.error)

    async def invoke(task_id: str) -> tuple[str, Any, BaseException | None, float]:
        task = by_id[task_id]
        record = records[task_id]
        spec = registry.get(task.tool)
        args = spec.args_model.model_validate(task.args)
        deps = {
            dependency: outputs[dependency]
            for dependency in task.depends_on
            if dependency in outputs
        }
        local_context = replace(
            base_context,
            dependency_results=deps,
            event_log=log,
            metadata={**base_context.metadata, "current_task_id": task_id},
        )
        stack = TraceStack(run_id)
        record.attempts += 1
        task_started = time.perf_counter()
        record.state = TaskState.RUNNING
        frames = stack.push(f"task:{task_id}")
        log.emit(
            "task_started",
            f"{task_id} started (attempt {record.attempts})",
            task_id=task_id,
            tool=task.tool,
            attempt=record.attempts,
            stack=frames,
            mode=context.mode,
        )
        frames = stack.push(f"tool:{task.tool}")
        log.emit("stack_push", f"entered {task.tool}", task_id=task_id, stack=frames)
        log.emit(
            "tool_call_validated",
            f"arguments validated for {task.tool}",
            task_id=task_id,
            tool=task.tool,
            parent_activity=f"task:{task_id}",
            arguments=args.model_dump(mode="json"),
            attempt=record.attempts,
            stack=frames,
        )
        log.emit(
            "tool_call_started",
            f"tool {task.tool} started",
            task_id=task_id,
            tool=task.tool,
            parent_activity=f"task:{task_id}",
            attempt=record.attempts,
            stack=frames,
        )
        try:
            result = await spec.handler(local_context, args)
            result_summary = _result_summary(result)
            if task.tool.startswith("search_") and isinstance(result, dict):
                result_summary["papers"] = result.get("papers", [])
            log.emit(
                "tool_call_completed",
                f"tool {task.tool} returned",
                task_id=task_id,
                tool=task.tool,
                parent_activity=f"task:{task_id}",
                attempt=record.attempts,
                duration_ms=round((time.perf_counter() - task_started) * 1000, 1),
                output_summary=result_summary,
                stack=frames,
            )
            frame, frames = stack.pop()
            log.emit("stack_pop", f"returned from {frame}", task_id=task_id, stack=frames)
            frame, frames = stack.pop()
            log.emit("stack_pop", f"returned from {frame}", task_id=task_id, stack=frames)
            duration_ms = round((time.perf_counter() - task_started) * 1000, 1)
            return task_id, result, None, duration_ms
        except Exception as exc:
            log.emit(
                "tool_call_failed",
                f"tool {task.tool} failed: {str(exc)[:320]}",
                task_id=task_id,
                tool=task.tool,
                parent_activity=f"task:{task_id}",
                attempt=record.attempts,
                error_type=type(exc).__name__,
                recovery_action=getattr(exc, "recovery_action", None),
                details=getattr(exc, "details", {}),
                stack=frames,
            )
            while len(stack.frames) > 1:
                frame, frames = stack.pop()
                log.emit("stack_pop", f"unwound {frame}", task_id=task_id, stack=frames)
            duration_ms = round((time.perf_counter() - task_started) * 1000, 1)
            return task_id, None, exc, duration_ms
        except asyncio.CancelledError as exc:
            while len(stack.frames) > 1:
                frame, frames = stack.pop()
                log.emit("stack_pop", f"unwound {frame}", task_id=task_id, stack=frames)
            duration_ms = round((time.perf_counter() - task_started) * 1000, 1)
            return task_id, None, exc, duration_ms

    def cancel_optional_sources() -> None:
        nonlocal acquisition_stop_reason
        sources = [record for record in records.values() if record.task.tool.startswith("search_")]
        successful_names = completed_source_names()
        if context.mode != "live" or not sources or len(successful_names) < minimum_sources:
            return
        raw_count, unique_count = candidate_counts()
        if profile.get("early_quorum", True):
            stop_reason = "source_quorum_reached"
        elif unique_count >= int(profile.get("target_unique_papers", 25)):
            stop_reason = "unique_paper_target_reached"
        elif raw_count >= int(profile.get("candidate_limit", 100)):
            stop_reason = "candidate_limit_reached"
        else:
            return
        if acquisition_stop_reason:
            return
        acquisition_stop_reason = stop_reason
        log.emit(
            "research_stopping",
            f"stopping acquisition: {stop_reason}",
            stop_reason=stop_reason,
            raw_candidate_count=raw_count,
            unique_paper_count=unique_count,
            successful_sources=sorted(successful_names),
        )
        for future, task_id in list(running.items()):
            if records[task_id].task.tool.startswith("search_") and not future.done():
                log.emit(
                    "task_cancel_requested",
                    f"canceling optional acquisition task {task_id}: {stop_reason}",
                    task_id=task_id,
                    recovery_action=stop_reason,
                    successful_sources=sorted(successful_names),
                )
                future.cancel()
        for record in sources:
            if record.state is TaskState.READY:
                record.state = TaskState.CANCELLED
                record.error = f"cancelled: {stop_reason}"
                log.emit(
                    "task_cancelled",
                    f"{record.task.id} skipped: {stop_reason}",
                    task_id=record.task.id,
                    recovery_action=stop_reason,
                    successful_sources=sorted(successful_names),
                )

    def expire_acquisition_budget() -> None:
        nonlocal acquisition_stop_reason
        if acquisition_deadline is None or time.monotonic() < acquisition_deadline:
            return
        if acquisition_stop_reason == "research_budget_exhausted":
            return
        if not acquisition_stop_reason:
            acquisition_stop_reason = "research_budget_exhausted"
            raw_count, unique_count = candidate_counts()
            log.emit(
                "research_stopping",
                "stopping acquisition: configured time budget exhausted",
                stop_reason=acquisition_stop_reason,
                budget_seconds=acquisition_budget,
                raw_candidate_count=raw_count,
                unique_paper_count=unique_count,
                successful_sources=sorted(completed_source_names()),
            )
        for future, task_id in list(running.items()):
            if records[task_id].task.tool.startswith("search_") and not future.done():
                future.cancel()
        for record in records.values():
            if record.task.tool.startswith("search_") and record.state in {
                TaskState.READY,
                TaskState.PLANNED,
            }:
                record.state = TaskState.CANCELLED
                record.error = "cancelled: research budget exhausted"
                log.emit(
                    "task_cancelled",
                    f"{record.task.id} skipped: research budget exhausted",
                    task_id=record.task.id,
                    recovery_action="research_budget_exhausted",
                )
                block_descendants(record.task.id, record.error)

    def expire_workflow_budget() -> None:
        nonlocal workflow_stop_reason
        if workflow_deadline is None or time.monotonic() < workflow_deadline:
            return
        if workflow_stop_reason:
            return
        workflow_stop_reason = "workflow_budget_exhausted"
        log.emit(
            "workflow_stopping",
            "stopping workflow: configured total time budget exhausted",
            stop_reason=workflow_stop_reason,
            budget_seconds=workflow_budget_seconds,
        )
        for future, _task_id in list(running.items()):
            if not future.done():
                future.cancel()
        for record in records.values():
            if record.state in {TaskState.READY, TaskState.PLANNED}:
                record.state = TaskState.CANCELLED
                record.error = "cancelled: workflow time budget exhausted"
                log.emit(
                    "task_cancelled",
                    f"{record.task.id} skipped: workflow time budget exhausted",
                    task_id=record.task.id,
                    recovery_action=workflow_stop_reason,
                )

    while queue or running:
        expire_acquisition_budget()
        expire_workflow_budget()
        if cancel_event is not None and cancel_event.is_set():
            log.emit(
                "run_cancel_requested",
                "cancellation requested; stopping queued and running work",
                run_id=run_id,
            )
            while queue:
                queued_id = queue.get()
                if records[queued_id].state is TaskState.READY:
                    records[queued_id].state = TaskState.CANCELLED
                    records[queued_id].error = "cancelled by user"
                    log.emit(
                        "task_cancelled",
                        f"{queued_id} cancelled before dispatch",
                        task_id=queued_id,
                        recovery_action="user_cancelled_run",
                    )
            for record in records.values():
                if record.state is TaskState.PLANNED:
                    record.state = TaskState.CANCELLED
                    record.error = "cancelled before becoming ready"
                    log.emit(
                        "task_cancelled",
                        f"{record.task.id} cancelled before readiness",
                        task_id=record.task.id,
                        recovery_action="user_cancelled_run",
                    )
            for future, _task_id in list(running.items()):
                if not future.done():
                    future.cancel()
            if not running:
                break
        while queue and len(running) < concurrency:
            task_id = queue.get()
            if records[task_id].state is not TaskState.READY:
                continue
            log.emit(
                "task_dequeued",
                f"{task_id} dispatched",
                task_id=task_id,
                schedule=schedule,
                priority=records[task_id].task.priority,
                ready_queue=queue.snapshot(),
            )
            log.emit(
                "queue_updated",
                f"{task_id} dequeued from {schedule} ready queue",
                operation="dequeue",
                task_id=task_id,
                schedule=schedule,
                ready_queue=queue.snapshot(),
            )
            future = asyncio.create_task(invoke(task_id))
            running[future] = task_id

        if not running:
            break
        wait_timeout = 0.2 if cancel_event is not None else None
        if acquisition_deadline is not None:
            remaining = max(0.0, acquisition_deadline - time.monotonic())
            if wait_timeout is None or remaining < wait_timeout:
                wait_timeout = remaining
        if workflow_deadline is not None:
            remaining = max(0.0, workflow_deadline - time.monotonic())
            if wait_timeout is None or remaining < wait_timeout:
                wait_timeout = remaining
        done, _pending = await asyncio.wait(
            running,
            timeout=wait_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            continue
        for future in sorted(done, key=lambda item: running[item]):
            task_id = running.pop(future)
            _returned_id, value, error, duration_ms = await future
            record = records[task_id]
            spec = registry.get(record.task.tool)
            if error is None:
                outputs[task_id] = value
                record.result = value
                record.state = TaskState.COMPLETED
                log.emit(
                    "task_completed",
                    f"{task_id} completed",
                    task_id=task_id,
                    result_summary=_result_summary(value),
                    duration_ms=duration_ms,
                )
                if record.task.tool in {"merge_and_save_context", "load_saved_context"}:
                    action = "loaded" if record.task.tool == "load_saved_context" else "saved"
                    log.emit(
                        "context_ready",
                        f"answerable context {action} with {value.get('paper_count', 0)} papers",
                        task_id=task_id,
                        paper_count=value.get("paper_count", 0),
                        abstract_count=value.get("abstract_count", 0),
                        context_hash=value.get("context_hash", ""),
                        context_built_at=value.get("built_at", ""),
                        snapshot_path=value.get("snapshot_path", ""),
                        source_names=value.get("source_names", []),
                        duplicates_merged=value.get("duplicates_merged", 0),
                        citation_links_resolved=value.get("citation_links_resolved", 0),
                        citation_links_dropped=value.get("citation_links_dropped", 0),
                        reference_ids_observed_count=value.get("reference_ids_observed_count", 0),
                        raw_candidate_count=value.get("raw_candidate_count", 0),
                        candidates_processed_count=value.get("candidates_processed_count", 0),
                        candidates_truncated_count=value.get("candidates_truncated_count", 0),
                        unique_paper_count=value.get("unique_paper_count", 0),
                        retained_paper_count=value.get("retained_paper_count", 0),
                        papers=value.get("papers", []),
                        elapsed_ms=round(
                            (time.perf_counter() - run_started) * 1000
                            + float(base_context.metadata.get("pre_execution_ms", 0)),
                            1,
                        ),
                    )
                cancel_optional_sources()
                block_descendants(task_id, "")
                continue

            if isinstance(error, asyncio.CancelledError):
                record.state = TaskState.CANCELLED
                cancel_reason = (
                    workflow_stop_reason or acquisition_stop_reason or "user_cancelled_run"
                )
                record.error = f"cancelled: {cancel_reason}"
                log.emit(
                    "task_cancelled",
                    f"{task_id} cancelled: {cancel_reason}",
                    task_id=task_id,
                    recovery_action=cancel_reason,
                )
                block_descendants(task_id, record.error)
                continue

            record.error = f"{type(error).__name__}: {error}"
            log.emit(
                "task_failed",
                f"{task_id} failed: {record.error}",
                task_id=task_id,
                attempt=record.attempts,
                recovery_action=getattr(error, "recovery_action", None),
                details=getattr(error, "details", {}),
            )
            if (
                isinstance(error, RetryableToolError)
                and spec.retryable
                and record.attempts < max_attempts
            ):
                record.state = TaskState.READY
                log.emit(
                    "task_retry",
                    f"retrying {task_id} ({record.attempts + 1}/{max_attempts})",
                    task_id=task_id,
                    recovery_action="retry_transient_tool",
                )
                enqueue(task_id)
            else:
                record.state = TaskState.FAILED
                log.emit(
                    "recovery_decision",
                    f"stopping {task_id}; dependent tasks will be blocked",
                    task_id=task_id,
                    recovery_action=getattr(error, "recovery_action", "block_dependents"),
                )
                block_descendants(task_id, record.error)

    source_records = [
        record for record in records.values() if record.task.tool.startswith("search_")
    ]
    required_records = [record for record in records.values() if record not in source_records]
    source_successes = len(completed_source_names())
    source_unavailable = [
        record.task.id
        for record in source_records
        if record.state is not TaskState.COMPLETED
        or outputs.get(record.task.id, {}).get("status") == "skipped_stop_criteria"
    ]
    source_unavailable = [
        task_id
        for task_id in source_unavailable
        if outputs.get(task_id, {}).get("status") != "skipped_stop_criteria"
    ]
    succeeded = all(record.state is TaskState.COMPLETED for record in required_records) and (
        not source_records or source_successes >= minimum_sources
    )
    reason = (
        "workflow_budget_exhausted"
        if workflow_stop_reason
        else "cancelled"
        if cancel_event is not None and cancel_event.is_set()
        else "completed_with_budget_limit"
        if succeeded and acquisition_stop_reason == "research_budget_exhausted"
        else "completed_at_research_target"
        if succeeded
        and acquisition_stop_reason
        in {
            "unique_paper_target_reached",
            "candidate_limit_reached",
        }
        else "completed_with_partial_sources"
        if succeeded and source_unavailable
        else "completed"
        if succeeded
        else "task_failed_or_blocked"
    )
    if not succeeded and any(item.kind == "source_rate_limit_stopped" for item in log.events):
        reason = "rate_limit_budget_stopped"
    elif not succeeded and any(item.kind == "source_http_budget_stopped" for item in log.events):
        reason = "http_attempt_budget_exhausted"
    http_attempt_events = [item for item in log.events if item.kind == "source_http_attempt"]
    attempts_by_provider: dict[str, int] = {}
    max_in_flight_by_provider: dict[str, int] = {}
    for item in http_attempt_events:
        provider = str(item.payload.get("provider", "unknown"))
        attempts_by_provider[provider] = attempts_by_provider.get(provider, 0) + 1
        max_in_flight_by_provider[provider] = max(
            max_in_flight_by_provider.get(provider, 0),
            int(item.payload.get("in_flight", 0)),
        )
    attempt_budget = context.metadata.get("http_attempt_budget")
    log.emit(
        "run_finished",
        "run completed with partial sources"
        if succeeded and source_unavailable
        else "run completed"
        if succeeded
        else "run stopped with failed or blocked tasks",
        succeeded=succeeded,
        termination_reason=reason,
        cancellation_requested=bool(cancel_event and cancel_event.is_set()),
        mode=context.mode,
        successful_source_count=source_successes,
        source_task_success_count=sum(
            record.state is TaskState.COMPLETED for record in source_records
        ),
        unique_paper_target=int(profile.get("target_unique_papers", 0)),
        research_stop_reason=acquisition_stop_reason or reason,
        unavailable_sources=source_unavailable,
        http_attempts=len(http_attempt_events),
        http_attempts_by_provider=attempts_by_provider,
        provider_max_in_flight_observed=max_in_flight_by_provider,
        http_attempt_budget=(attempt_budget.maximum if attempt_budget is not None else None),
        http_attempt_budget_used=(attempt_budget.used if attempt_budget is not None else None),
        elapsed_ms=round(
            (time.perf_counter() - run_started) * 1000
            + float(base_context.metadata.get("pre_execution_ms", 0)),
            1,
        ),
    )
    return RunResult(
        run_id=run_id,
        mode=context.mode,
        plan=plan,
        states=records,
        succeeded=succeeded,
        termination_reason=reason,
        events=[event.to_dict() for event in log.events],
    )
