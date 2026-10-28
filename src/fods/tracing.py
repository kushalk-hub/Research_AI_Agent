"""Trace actual model calls into the FODS event stream."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fods.events import EventLog
from fods.safety import redact_text


def _identity(llm: Any, stage: str, requested_model: str | None) -> tuple[str, str]:
    model = requested_model
    if hasattr(llm, "model_for"):
        model = llm.model_for(stage, requested_model)
    settings = getattr(llm, "settings", None)
    if model and settings is not None and hasattr(settings, "canonical_model"):
        model = settings.canonical_model(model)
    model = model or "unknown"
    provider = model.split("/", 1)[0] if "/" in model else "unknown"
    backend = getattr(llm, "backend", None)
    if backend is not None and hasattr(backend, "provider_for"):
        provider = backend.provider_for(model)
    return provider, model


async def traced_model_call(
    event_log: EventLog | None,
    llm: Any,
    *,
    stage: str,
    requested_model: str | None,
    run_id: str,
    parent_task: str | None,
    operation: Callable[[], Awaitable[Any]],
    summarize: Callable[[Any], dict[str, Any]],
) -> Any:
    """Run one provider call and record requested and successful model identity."""
    provider, model = _identity(llm, stage, requested_model)
    activity_id = uuid.uuid4().hex[:12]
    parent_stack = [f"run:{run_id}"]
    if parent_task:
        parent_stack.append(f"task:{parent_task}")
    model_name = model.split("/", 1)[-1]
    stack = [*parent_stack, f"model:{provider}/{model_name}"]
    fallback_count = len(getattr(llm, "fallbacks", []))
    if event_log is not None:
        event_log.emit(
            "model_call_started",
            f"{stage} model call started",
            activity_id=activity_id,
            parent_task=parent_task,
            stage=stage,
            provider=provider,
            model=model,
            stack=stack,
        )
        event_log.emit(
            "stack_push",
            f"entered model:{provider}/{model_name}",
            activity_id=activity_id,
            stack=stack,
        )
    try:
        result = await operation()
    except Exception as exc:
        if event_log is not None:
            event_log.emit(
                "model_call_failed",
                f"{stage} model call failed: {redact_text(str(exc))[:320]}",
                activity_id=activity_id,
                parent_task=parent_task,
                stage=stage,
                provider=provider,
                model=model,
                error_type=type(exc).__name__,
                stack=parent_stack,
            )
            event_log.emit(
                "stack_pop",
                f"unwound model:{provider}/{model_name}",
                activity_id=activity_id,
                failed=True,
                stack=parent_stack,
            )
        raise

    fallbacks = getattr(llm, "fallbacks", [])[fallback_count:]
    actual_model = model
    for fallback in fallbacks:
        if len(fallback) >= 3 and fallback[0] == stage:
            actual_model = fallback[2]
    actual_provider, actual_model = _identity(llm, stage, actual_model)
    summary = summarize(result)
    if event_log is not None:
        event_log.emit(
            "model_call_completed",
            f"{stage} model call completed",
            activity_id=activity_id,
            parent_task=parent_task,
            stage=stage,
            provider=actual_provider,
            model=actual_model,
            requested_provider=provider,
            requested_model=model,
            fallback_count=len(fallbacks),
            output_summary=summary,
            stack=stack,
        )
        event_log.emit(
            "stack_pop",
            f"returned from model:{actual_provider}/{actual_model.split('/', 1)[-1]}",
            activity_id=activity_id,
            failed=False,
            stack=parent_stack,
        )
    return result
