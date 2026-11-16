"""Every recorded event must be displayable from the record alone.

Design §5.1: the in-chat status lines and the trace table read the same
`summary`/`phase`/`class`/`severity`/`duration_ms` fields, which the backend
writes at emit time. The frontend keeps a fallback for the 82 logs recorded
before those fields existed, so the golden fixtures are exercised here to prove
the same derivation produces them for old and new events.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fods.event_meta import MAX_SUMMARY, describe
from fods.events import EventLog, read_events

FIXTURES = Path(__file__).parent / "fixtures" / "fods_logs"
GOLDEN_LOGS = ["17ee03228c0b.jsonl", "efee736eb669.jsonl", "Q01-deep.jsonl"]

VALID_PHASES = {
    "plan",
    "queue",
    "runtime",
    "acquire",
    "merge",
    "evidence",
    "answer",
    "validate",
    "write",
    "search",
    "fetch",
    "score",
    "fulltext",
    "extract",
    "resolve",
    "graph",
    "traverse",
    "done",
    "error",
}
VALID_CLASSES = {
    "plan",
    "queue",
    "task",
    "tool",
    "stack",
    "source",
    "model",
    "evidence",
    "answer",
    "validation",
    "output",
    "runtime",
}
VALID_SEVERITIES = {"info", "ok", "warn", "error"}


@pytest.mark.parametrize("name", GOLDEN_LOGS)
def test_every_recorded_event_gets_a_displayable_summary(name):
    events = read_events(FIXTURES / name)
    assert events, f"{name} is empty"

    for event in events:
        details = describe(event["kind"], event["message"], event.get("payload", {}))
        where = f"{name} seq {event['seq']} ({event['kind']})"
        assert details["summary"], f"{where} has no summary"
        assert len(details["summary"]) <= MAX_SUMMARY, where
        assert "\n" not in details["summary"], where
        assert details["phase"] in VALID_PHASES, f"{where}: {details['phase']}"
        assert details["event_class"] in VALID_CLASSES, f"{where}: {details['event_class']}"
        assert details["severity"] in VALID_SEVERITIES, f"{where}: {details['severity']}"


def test_plan_validated_summary_states_the_recorded_counts():
    payload = {"tasks": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "levels": [["a"], ["b"], ["c"]]}
    details = describe("plan_validated", "plan accepted: 3 tasks, 3 topological levels", payload)
    assert details["summary"] == "plan validated — 3 tasks, 3 levels"
    assert details["phase"] == "plan"
    assert details["event_class"] == "plan"
    assert details["severity"] == "ok"


def test_phase_for_scheduler_events_comes_from_the_task_tool():
    assert describe("task_started", "x", {"tool": "search_arxiv"})["phase"] == "acquire"
    evidence = describe("tool_call_completed", "x", {"tool": "retrieve_evidence"})
    assert evidence["phase"] == "evidence"
    assert describe("task_completed", "x", {"tool": "draft_cited_answer"})["phase"] == "answer"
    assert describe("task_completed", "x", {"tool": "merge_and_save_context"})["phase"] == "merge"
    # No tool recorded: the event is runtime bookkeeping, not a research phase.
    assert describe("queue_updated", "x", {})["phase"] == "queue"
    assert describe("stack_push", "x", {"task_id": "t"})["phase"] == "runtime"


def test_rla_progress_phase_comes_from_the_payload():
    details = describe("research_progress", "fetched 3 abstracts", {"phase": "fetch"})
    assert details["phase"] == "fetch"
    assert details["event_class"] == "source"
    assert details["summary"] == "fetched 3 abstracts"
    assert describe("research_progress", "done", {"phase": "done"})["event_class"] == "runtime"


def test_duration_is_copied_only_when_it_was_recorded():
    assert describe("task_completed", "x", {"duration_ms": 12.5})["duration_ms"] == 12.5
    assert describe("plan_validated", "x", {"tasks": [], "levels": []})["duration_ms"] is None
    # Bools are not durations even though they are ints in Python.
    assert describe("task_completed", "x", {"duration_ms": True})["duration_ms"] is None


def test_severity_reports_what_happened_not_just_the_kind():
    assert describe("citation_validation", "x", {"valid": True})["severity"] == "ok"
    assert describe("citation_validation", "x", {"valid": False})["severity"] == "warn"
    assert describe("run_finished", "x", {"succeeded": True})["severity"] == "ok"
    assert (
        describe("run_finished", "x", {"termination_reason": "completed_with_partial_sources"})[
            "severity"
        ]
        == "warn"
    )
    assert describe("run_finished", "x", {"succeeded": False})["severity"] == "error"
    assert describe("plan_rejected", "x", {})["severity"] == "error"


def test_event_log_writes_the_five_fields_and_keeps_the_wire_key_class(tmp_path):
    path = tmp_path / "trace.jsonl"
    log = EventLog(path)
    event = log.emit("task_completed", "search_arxiv completed", task_id="t1", duration_ms=7.0)

    stored = json.loads(path.read_text(encoding="utf-8").strip())
    for key in ("summary", "phase", "class", "severity", "duration_ms"):
        assert key in stored, f"{key} missing from the recorded event"
    assert "event_class" not in stored
    assert stored["class"] == "task"
    assert stored["summary"] == "search_arxiv completed"
    assert stored["duration_ms"] == 7.0
    # The five positional fields are unchanged for old readers.
    for key in ("seq", "kind", "message", "payload", "timestamp"):
        assert key in stored
    assert event.to_dict() == stored


def test_long_messages_are_truncated_not_dumped():
    log = EventLog()
    event = log.emit("tool_call_failed", "boom " + "x" * 400)
    assert event.summary is not None
    assert len(event.summary) <= MAX_SUMMARY
    assert event.summary.endswith("…")


def test_a_replayed_old_event_gets_the_same_summary_as_a_new_one():
    """Old logs and new events must describe themselves identically."""
    old = read_events(FIXTURES / "17ee03228c0b.jsonl")[3]
    expected = describe(old["kind"], old["message"], old["payload"])
    new = EventLog().emit(old["kind"], old["message"], **old["payload"])
    assert new.summary == expected["summary"]
    assert new.phase == expected["phase"]
    assert new.event_class == expected["event_class"]
    assert new.severity == expected["severity"]
    assert new.duration_ms == expected["duration_ms"]
