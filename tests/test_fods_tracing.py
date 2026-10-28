from __future__ import annotations

import asyncio

from fods.events import EventLog
from fods.tracing import traced_model_call


class _Provider:
    def model_for(self, _stage: str, requested: str | None) -> str:
        return requested or "ollama/qwen3:4b"


def test_provider_failure_is_traced_and_unwinds_model_stack(tmp_path):
    log = EventLog(tmp_path / "provider-failure.jsonl")

    async def fail_call():
        raise RuntimeError("provider is unavailable")

    try:
        asyncio.run(
            traced_model_call(
                log,
                _Provider(),
                stage="fods_plan",
                requested_model="ollama/qwen3:4b",
                run_id="test-run",
                parent_task=None,
                operation=fail_call,
                summarize=lambda result: {"length": len(result)},
            )
        )
    except RuntimeError as error:
        assert str(error) == "provider is unavailable"
    else:
        raise AssertionError("provider exception should be propagated")

    events = [event for event in log.events]
    kinds = [event.kind for event in events]
    failed = next(event for event in events if event.kind == "model_call_failed")

    assert "model_call_started" in kinds
    assert "model_call_completed" not in kinds
    assert kinds[-1] == "stack_pop"
    assert failed.payload["provider"] == "ollama"
    assert failed.payload["model"] == "ollama/qwen3:4b"
    assert failed.payload["error_type"] == "RuntimeError"
    assert "provider is unavailable" in failed.message
    assert events[-1].payload["failed"] is True
