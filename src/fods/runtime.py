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
from fods.tools import ToolContext, ToolRegistry


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
        "valid",
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
                child.task.tool == "merge_and_save_context"
                and all(dependency.state in terminal_states for dependency in dependencies_now)
                and sum(dependency.state is TaskState.COMPLETED for dependency in dependencies_now)
                >= 2
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
            if child.task.tool == "merge_and_save_context":
                dependencies = dependencies_now
                if any(dependency.state not in terminal_states for dependency in dependencies):
                    continue
                completed_sources = [
                    dependency
                    for dependency in dependencies
                    if dependency.state is TaskState.COMPLETED
                ]
                if len(completed_sources) >= 2:
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
                            minimum_sources=2,
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
        sources = [record for record in records.values() if record.task.tool.startswith("search_")]
        successes = [record for record in sources if record.state is TaskState.COMPLETED]
        if context.mode != "live" or len(sources) < 3 or len(successes) < 2:
            return
        successful_names = [record.task.id for record in successes]
        for future, task_id in list(running.items()):
            if records[task_id].task.tool.startswith("search_") and not future.done():
                log.emit(
                    "task_cancel_requested",
                    f"canceling optional source {task_id} after two sources returned",
                    task_id=task_id,
                    recovery_action="source_quorum_reached",
                    successful_sources=successful_names,
                )
                future.cancel()
        for record in sources:
            if record.state is TaskState.READY:
                record.state = TaskState.CANCELLED
                record.error = "cancelled after two sources returned"
                log.emit(
                    "task_cancelled",
                    f"{record.task.id} skipped after source quorum",
                    task_id=record.task.id,
                    recovery_action="source_quorum_reached",
                    successful_sources=successful_names,
                )

    while queue or running:
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
        done, _pending = await asyncio.wait(
            running,
            timeout=0.2 if cancel_event is not None else None,
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
                        snapshot_path=value.get("snapshot_path", ""),
                        source_names=value.get("source_names", []),
                        duplicates_merged=value.get("duplicates_merged", 0),
                        citation_links_resolved=value.get("citation_links_resolved", 0),
                        citation_links_dropped=value.get("citation_links_dropped", 0),
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
                record.error = "cancelled after the source quorum was reached"
                log.emit(
                    "task_cancelled",
                    f"{task_id} cancelled after two sources returned",
                    task_id=task_id,
                    recovery_action="source_quorum_reached",
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
    source_successes = sum(record.state is TaskState.COMPLETED for record in source_records)
    source_unavailable = [
        record.task.id for record in source_records if record.state is not TaskState.COMPLETED
    ]
    succeeded = all(record.state is TaskState.COMPLETED for record in required_records) and (
        not source_records or source_successes >= 2
    )
    reason = (
        "cancelled"
        if cancel_event is not None and cancel_event.is_set()
        else "completed_with_partial_sources"
        if succeeded and source_unavailable
        else "completed"
        if succeeded
        else "task_failed_or_blocked"
    )
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
        unavailable_sources=source_unavailable,
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
