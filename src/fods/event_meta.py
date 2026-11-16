"""One place that gives a runtime event its display fields.

The UI shows a one-line summary, a phase, a class, a severity and a duration for
every event. Those are **facts about the record**, so the backend writes them
when the event is emitted (`RuntimeEvent.summary`, `.phase`, `.class`,
`.severity`, `.duration_ms`) and the frontend only falls back to its own
`describeEvent()` for logs recorded before these fields existed.

Keeping the derivation here means the in-chat status lines and the trace table
cannot disagree: both read the same five fields (design §5.1, §8.5).
"""

from __future__ import annotations

from typing import Any

#: Decision 6: summaries are short, human text, never a JSON dump or a path.
MAX_SUMMARY = 90

PLAN_KINDS = {
    "research_query_plan",
    "plan_received",
    "plan_repaired",
    "plan_validated",
    "plan_rejected",
}
QUEUE_KINDS = {"task_ready", "queue_updated", "task_dequeued", "dependency_updated"}
TASK_KINDS = {
    "task_started",
    "task_completed",
    "task_failed",
    "task_retry",
    "task_cancelled",
}
STACK_KINDS = {"stack_push", "stack_pop"}
TOOL_KINDS = {"tool_call_validated", "tool_call_started", "tool_call_completed", "tool_call_failed"}
MODEL_KINDS = {"model_call_started", "model_call_completed", "model_call_failed"}
SOURCE_KINDS = {
    "context_ready",
    "research_papers",
    "research_stopping",
    "source_http_attempt",
    "source_retry",
    "source_rate_limit_stopped",
    "source_http_budget_stopped",
    "source_cache_hit",
}
EVIDENCE_KINDS = {"evidence_selected"}
ANSWER_KINDS = {"answer_ready", "research_answer"}
VALIDATION_KINDS = {"citation_validation"}
OUTPUT_KINDS = {"brief_saved"}

#: Tool prefix/suffix -> trace phase for the FODS scheduler (design §5).
TOOL_PHASE = {
    "search_": "acquire",
    "acquisition_checkpoint": "acquire",
    "merge_and_save_context": "merge",
    "load_saved_context": "merge",
    "retrieve_evidence": "evidence",
    "draft_cited_answer": "answer",
    "validate_citations": "validate",
    "write_cited_brief": "write",
}

#: RLA pipeline phase -> trace class (design §5).
PHASE_CLASS = {
    "search": "source",
    "fetch": "source",
    "score": "source",
    "fulltext": "source",
    "extract": "evidence",
    "resolve": "evidence",
    "graph": "evidence",
    "traverse": "evidence",
    "answer": "answer",
    "done": "runtime",
    "error": "runtime",
}

#: RLA pipeline phase -> human label, shared with the Lab phase rail.
PHASE_LABEL = {
    "search": "Search",
    "fetch": "Fetch",
    "score": "Score",
    "fulltext": "Full text",
    "extract": "Extract",
    "resolve": "Resolve",
    "graph": "Graph",
    "traverse": "Traverse",
    "answer": "Answer",
    "done": "Done",
    "error": "Error",
}

ERROR_KINDS = {
    "plan_rejected",
    "run_failed",
    "tool_call_failed",
    "task_failed",
    "model_call_failed",
    "source_rate_limit_stopped",
    "source_http_budget_stopped",
}
WARN_KINDS = {
    "task_retry",
    "task_cancelled",
    "research_stopping",
    "run_cancel_requested",
    "task_cancel_requested",
    "recovery_decision",
}


def _text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_SUMMARY:
        return text
    return text[: MAX_SUMMARY - 1].rstrip() + "…"


def _tool_phase(tool: str, payload: dict[str, Any]) -> str:
    for needle, phase in TOOL_PHASE.items():
        if tool == needle or (needle.endswith("_") and tool.startswith(needle)):
            return phase
    return str(payload.get("phase") or "runtime")


def phase_for(kind: str, payload: dict[str, Any]) -> str:
    """Trace phase for one event, from the record rather than the kind alone."""
    if payload.get("phase"):
        return str(payload["phase"])
    tool = str(payload.get("tool") or "")
    if tool:
        return _tool_phase(tool, payload)
    if kind in PLAN_KINDS:
        return "plan"
    if kind in QUEUE_KINDS:
        return "queue"
    if kind in TASK_KINDS or kind in STACK_KINDS or kind in TOOL_KINDS:
        return "runtime"
    return "runtime"


def class_for(kind: str, payload: dict[str, Any]) -> str:
    if kind in PLAN_KINDS:
        return "plan"
    if kind in QUEUE_KINDS:
        return "queue"
    if kind in TASK_KINDS:
        return "task"
    if kind in STACK_KINDS:
        return "stack"
    if kind in TOOL_KINDS:
        return "tool"
    if kind in MODEL_KINDS:
        return "model"
    if kind in SOURCE_KINDS:
        return "source"
    if kind in EVIDENCE_KINDS:
        return "evidence"
    if kind in ANSWER_KINDS:
        return "answer"
    if kind in VALIDATION_KINDS:
        return "validation"
    if kind in OUTPUT_KINDS:
        return "output"
    phase = str(payload.get("phase") or "")
    if phase:
        return PHASE_CLASS.get(phase, "runtime")
    return "runtime"


def severity_for(kind: str, payload: dict[str, Any]) -> str:
    """info | ok | warn | error, from what actually happened."""
    if kind in ERROR_KINDS:
        return "error"
    if kind == "citation_validation":
        return "ok" if payload.get("valid") else "warn"
    if kind == "run_finished":
        if payload.get("succeeded") is False:
            return "error"
        if payload.get("termination_reason") == "completed_with_partial_sources":
            return "warn"
        return "ok"
    if kind in WARN_KINDS:
        return "warn"
    if payload.get("valid") is False:
        return "warn"
    if kind.endswith(("_completed", "_saved", "_ready", "_validated")):
        return "ok"
    return "info"


def _summary_for(kind: str, message: str, payload: dict[str, Any]) -> str:
    """A concrete one-liner, using payload counts where they exist."""
    if kind == "plan_validated":
        tasks = payload.get("tasks")
        levels = payload.get("levels")
        if isinstance(tasks, list) and isinstance(levels, list):
            return f"plan validated — {len(tasks)} tasks, {len(levels)} levels"
    if kind == "plan_received":
        tasks = payload.get("tasks")
        if isinstance(tasks, list):
            return f"plan received — {len(tasks)} tasks"
    if kind == "plan_repaired":
        repairs = payload.get("repairs")
        if isinstance(repairs, list):
            return f"plan repaired — {len(repairs)} detail(s)"
    if kind == "context_ready":
        papers = payload.get("paper_count")
        if isinstance(papers, int):
            return f"answerable context — {papers} papers"
    if kind == "evidence_selected":
        count = payload.get("evidence_selected_paper_count")
        if isinstance(count, int):
            return f"{count} evidence card(s) selected"
    if kind == "research_papers":
        papers = payload.get("papers")
        if isinstance(papers, list):
            return f"{len(papers)} selected papers"
    if kind == "citation_validation":
        unknown = payload.get("unknown")
        if payload.get("valid"):
            return "citations validated"
        if isinstance(unknown, list):
            return f"citations rejected — {len(unknown)} unknown"
        return "citations rejected"
    if payload.get("phase") and message:
        # RLA progress lines are already one-liners written for humans.
        return message
    return message


def duration_for(payload: dict[str, Any]) -> float | None:
    value = payload.get("duration_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def describe(kind: str, message: str, payload: dict[str, Any]) -> dict[str, Any]:
    """All five optional `RuntimeEvent` fields for one event."""
    return {
        "summary": _text(_summary_for(kind, message, payload)),
        "phase": phase_for(kind, payload),
        "event_class": class_for(kind, payload),
        "severity": severity_for(kind, payload),
        "duration_ms": duration_for(payload),
    }
