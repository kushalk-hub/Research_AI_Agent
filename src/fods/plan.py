"""Plan validation: tool contracts and DAG checks run before any side effect."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fods.models import TaskPlan


class PlanError(ValueError):
    """A plan cannot safely be executed."""


def _cycle_path(tasks: list[Any], ids: set[str]) -> list[str] | None:
    by_id = {task.id: task for task in tasks}
    color = {task_id: 0 for task_id in ids}
    path: list[str] = []

    def visit(task_id: str) -> list[str] | None:
        color[task_id] = 1
        path.append(task_id)
        for dependency in by_id[task_id].depends_on:
            if color[dependency] == 0:
                found = visit(dependency)
                if found:
                    return found
            elif color[dependency] == 1:
                start = path.index(dependency)
                return [*path[start:], dependency]
        path.pop()
        color[task_id] = 2
        return None

    for task_id in ids:
        if color[task_id] == 0:
            found = visit(task_id)
            if found:
                return found
    return None


def validate_plan(
    plan: TaskPlan,
    tool_schemas: Mapping[str, type[BaseModel]],
    workspace: Path | None = None,
) -> list[list[str]]:
    """Validate IDs, dependencies, tool args, then return Kahn topological levels."""
    ids = [task.id for task in plan.tasks]
    if len(ids) != len(set(ids)):
        raise PlanError("duplicate task id")
    id_set = set(ids)
    by_id = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        if task.tool not in tool_schemas:
            raise PlanError(f"task {task.id}: unregistered tool {task.tool!r}")
        unknown = set(task.depends_on) - id_set
        if unknown:
            raise PlanError(f"task {task.id}: unknown dependencies {sorted(unknown)}")
        if task.id in task.depends_on:
            raise PlanError(f"task {task.id}: cannot depend on itself")
        try:
            tool_schemas[task.tool].model_validate(task.args)
        except Exception as exc:
            raise PlanError(f"task {task.id}: invalid arguments: {exc}") from exc

    cycle = _cycle_path(plan.tasks, id_set)
    if cycle:
        raise PlanError("dependency cycle: " + " -> ".join(cycle))

    indegree = {task.id: len(task.depends_on) for task in plan.tasks}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in id_set}
    for task in plan.tasks:
        for dependency in task.depends_on:
            dependents[dependency].append(task.id)
    ready = deque(task_id for task_id in ids if indegree[task_id] == 0)
    levels: list[list[str]] = []
    visited = 0
    while ready:
        level = list(ready)
        ready.clear()
        levels.append(level)
        visited += len(level)
        for task_id in level:
            for child in dependents[task_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
    if visited != len(by_id):
        raise PlanError("dependency graph is not acyclic")
    _validate_research_flow(plan, by_id)
    if workspace is not None:
        root = workspace.resolve()
        destination = (root / plan.output_path).resolve()
        if destination == root or not destination.is_relative_to(root):
            raise PlanError("output path must resolve to a file inside the approved workspace")
        if destination.exists():
            raise PlanError(f"output path already exists; choose a new path: {plan.output_path}")
    return levels


def _validate_research_flow(plan: TaskPlan, by_id: dict[str, Any]) -> None:
    """Require the evidence → citation-check → write safety chain."""
    source_tasks = [task for task in plan.tasks if task.tool.startswith("search_")]
    context_loads = [task for task in plan.tasks if task.tool == "load_saved_context"]
    if context_loads:
        if source_tasks or len(context_loads) != 1:
            raise PlanError(
                "context reuse plans must have one load task and no source search tasks"
            )
    else:
        if len(source_tasks) < 2:
            raise PlanError("research plan must include at least two independent source tasks")
        if any(task.depends_on for task in source_tasks):
            raise PlanError(
                "academic source tasks must be independent so the runtime can fan them out"
            )

    required = {
        "retrieve_evidence": "retrieve",
        "draft_cited_answer": "answer",
        "validate_citations": "citation validation",
        "write_cited_brief": "brief write",
    }
    one_task: dict[str, Any] = {}
    for tool, label in required.items():
        matches = [task for task in plan.tasks if task.tool == tool]
        if len(matches) != 1:
            raise PlanError(f"research plan requires exactly one {label} task")
        one_task[tool] = matches[0]

    merges = [task for task in plan.tasks if task.tool == "merge_and_save_context"]
    if source_tasks:
        if len(merges) != 1:
            raise PlanError("research plans require exactly one context merge task")
        context_task = merges[0]
        if not set(task.id for task in source_tasks).issubset(set(context_task.depends_on)):
            raise PlanError("context merge must depend on every source task")
    else:
        if merges:
            raise PlanError("context reuse must not rebuild the saved context")
        context_task = context_loads[0]
    chain = [
        ("draft_cited_answer", "retrieve_evidence"),
        ("validate_citations", "draft_cited_answer"),
        ("write_cited_brief", "validate_citations"),
    ]
    for child_tool, parent_tool in chain:
        child = one_task[child_tool]
        parent = one_task[parent_tool]
        if parent.id not in child.depends_on:
            raise PlanError(f"{child_tool} must depend on {parent_tool}")

    retrieve = one_task["retrieve_evidence"]
    if context_task.id not in retrieve.depends_on:
        raise PlanError("evidence retrieval must depend on the merged or loaded context")

    if one_task["draft_cited_answer"].id not in one_task["write_cited_brief"].depends_on:
        raise PlanError(
            "brief write must depend on the cited answer as well as citation validation"
        )

    if one_task["write_cited_brief"].args.get("output_path") != plan.output_path:
        raise PlanError("write task path must match the explicitly named plan output path")
