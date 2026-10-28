"""LLM-proposed and deterministic research plans."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from fods.events import EventLog
from fods.models import Task, TaskPlan
from fods.tracing import traced_model_call


class Planner(Protocol):
    async def propose(
        self,
        request: str,
        topic: str,
        question: str,
        output_path: str,
        source_names: Sequence[str],
    ) -> TaskPlan: ...


class LLMPlanner:
    def __init__(
        self,
        llm: Any,
        model: str | None = None,
        event_log: EventLog | None = None,
        run_id: str = "",
    ) -> None:
        self.llm = llm
        self.model = model
        self.event_log = event_log
        self.run_id = run_id

    async def propose(
        self,
        request: str,
        topic: str,
        question: str,
        output_path: str,
        source_names: Sequence[str],
    ) -> TaskPlan:
        from fods.models import TaskPlan

        searches = "\n".join(
            f"- search_{name}: args={{'query': string, 'limit': integer 1..20}}"
            for name in source_names
        )
        prompt = f"""Create a concise structured task plan for the user's research request.
The runtime, not you, controls task order, concurrency, permissions, retries, and writes.
Use these tools only:
{searches}
- merge_and_save_context: args={{}}
- retrieve_evidence: args={{'question': string, 'max_results': integer 1..10}}
- draft_cited_answer: args={{'question': string}}
- validate_citations: args={{}}
- write_cited_brief: args={{'output_path': string}}

Include one independent search task per listed source. Then include a merge depending on every
search, retrieval depending on merge, answer depending on retrieval, citation validation depending
on answer, and a write depending on both answer and validation. Set the write path exactly to the
supplied path. Do not add tools or dependencies outside this flow.

Request: {request}
Topic: {topic}
Question: {question}
Output path: {output_path}
Available sources: {", ".join(source_names)}
"""
        proposed = await traced_model_call(
            self.event_log,
            self.llm,
            stage="fods_plan",
            requested_model=self.model,
            run_id=self.run_id,
            parent_task=None,
            operation=lambda: self.llm.generate_structured(
                prompt,
                TaskPlan,
                stage="fods_plan",
                temperature=0.0,
                model=self.model,
            ),
            summarize=lambda value: {"task_count": len(value.tasks)},
        )
        return TaskPlan.model_validate(proposed.model_dump())


def canonicalize_llm_research_plan(
    proposed: TaskPlan, source_names: Sequence[str]
) -> tuple[TaskPlan, list[str]]:
    """Repair only the known research-workflow shape, leaving cycles for rejection.

    Small local models can omit dependency edges or return a source name instead of
    its registered tool name. Repairs are explicit events; they never add tools or
    alter a cyclic or otherwise malformed dependency graph.
    """
    task_ids = [task.id for task in proposed.tasks]
    id_set = set(task_ids)
    if len(id_set) != len(task_ids):
        return proposed, []
    if any(set(task.depends_on) - id_set for task in proposed.tasks):
        return proposed, []
    indegree = {task.id: len(task.depends_on) for task in proposed.tasks}
    dependents: dict[str, list[str]] = {task.id: [] for task in proposed.tasks}
    for task in proposed.tasks:
        for parent in task.depends_on:
            dependents[parent].append(task.id)
    ready = [task_id for task_id in task_ids if indegree[task_id] == 0]
    visited = 0
    while ready:
        task_id = ready.pop()
        visited += 1
        for child_id in dependents[task_id]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
    if visited != len(task_ids):
        return proposed, []

    repairs: list[str] = []
    tasks: list[Task] = []
    for task in proposed.tasks:
        tool = f"search_{task.tool}" if task.tool in source_names else task.tool
        if tool != task.tool:
            repairs.append(f"mapped source alias {task.tool!r} to registered tool {tool!r}")
        tasks.append(task.model_copy(update={"tool": tool}))

    by_tool: dict[str, list[Task]] = {}
    for task in tasks:
        by_tool.setdefault(task.tool, []).append(task)
    source_tasks = [
        task for task in tasks if task.tool in {f"search_{name}" for name in source_names}
    ]
    required_tools = (
        "merge_and_save_context",
        "retrieve_evidence",
        "draft_cited_answer",
        "validate_citations",
        "write_cited_brief",
    )
    if len(source_tasks) < 2 or any(len(by_tool.get(tool, [])) != 1 for tool in required_tools):
        return proposed.model_copy(update={"tasks": tasks}), repairs
    if len(tasks) != len(source_tasks) + len(required_tools):
        return proposed.model_copy(update={"tasks": tasks}), repairs

    merge = by_tool["merge_and_save_context"][0]
    retrieve = by_tool["retrieve_evidence"][0]
    answer = by_tool["draft_cited_answer"][0]
    citation_check = by_tool["validate_citations"][0]
    write = by_tool["write_cited_brief"][0]
    dependencies = {
        **{task.id: [] for task in source_tasks},
        merge.id: [task.id for task in source_tasks],
        retrieve.id: [merge.id],
        answer.id: [retrieve.id],
        citation_check.id: [answer.id],
        write.id: [answer.id, citation_check.id],
    }
    normalized: list[Task] = []
    for task in tasks:
        expected = dependencies[task.id]
        if task.depends_on != expected:
            repairs.append(f"set dependencies for {task.id!r} to {expected}")
        normalized.append(task.model_copy(update={"depends_on": expected}))
    return proposed.model_copy(update={"tasks": normalized}), repairs


def deterministic_plan(
    request: str,
    topic: str,
    question: str,
    output_path: str,
    source_names: Sequence[str],
    reuse_context: bool = False,
) -> TaskPlan:
    if reuse_context:
        tasks = [Task(id="load_context", tool="load_saved_context", priority=10)]
        context_id = "load_context"
    else:
        fixed_priority = {"arxiv": 30, "openalex": 20, "semantic_scholar": 10}
        tasks = [
            Task(
                id=f"search_{name}",
                tool=f"search_{name}",
                args={"query": topic, "limit": 8},
                priority=fixed_priority.get(name, 10),
            )
            for name in source_names
        ]
        source_ids = [task.id for task in tasks]
        context_id = "merge"
    if not reuse_context:
        tasks.append(
            Task(
                id="merge",
                tool="merge_and_save_context",
                depends_on=source_ids,
                priority=5,
            )
        )
    tasks.extend(
        [
            Task(
                id="retrieve",
                tool="retrieve_evidence",
                args={"question": question, "max_results": 6},
                depends_on=[context_id],
            ),
            Task(
                id="answer",
                tool="draft_cited_answer",
                args={"question": question},
                depends_on=["retrieve"],
            ),
            Task(id="citation_check", tool="validate_citations", depends_on=["answer"]),
            Task(
                id="write",
                tool="write_cited_brief",
                args={"output_path": output_path},
                depends_on=["answer", "citation_check"],
            ),
        ]
    )
    return TaskPlan(
        request=request,
        topic=topic,
        question=question,
        output_path=output_path,
        tasks=tasks,
    )
