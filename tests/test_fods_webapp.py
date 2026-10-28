from __future__ import annotations

import json
import threading
import time
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from fods.events import EventLog
from fods.webapp import NewRun, RunManager, make_server
from rla.config import Settings


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        gemini_api_key="private-test-secret",
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )


def test_run_request_rejects_blank_input_and_unbounded_settings():
    with pytest.raises(ValidationError):
        NewRun(topic="  ", question="A valid question")
    with pytest.raises(ValidationError):
        NewRun(topic="Graph attention", question="A valid question", concurrency=99)


def test_output_filename_cannot_escape_briefs_directory(tmp_path):
    manager = RunManager(_settings(tmp_path))
    request = NewRun(
        topic="Graph attention", question="What is the method?", output_name="..\\outside.md"
    )
    with pytest.raises(ValueError, match="simple Markdown filename"):
        manager._output_name(request, "0123456789ab")


def test_replay_reads_events_without_starting_execution(tmp_path, monkeypatch):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "seq": 1,
        "kind": "plan_rejected",
        "message": "dependency cycle: a -> b -> a",
        "payload": {"tool_calls": 0},
        "timestamp": 1.0,
    }
    (manager.runs_dir / "0123456789ab.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    def no_execution(*_args, **_kwargs):
        raise AssertionError("replay must not execute the runtime")

    monkeypatch.setattr("fods.cli._execute", no_execution, raising=False)
    replay = manager.replay("0123456789ab", speed_ms=0)
    deadline = time.monotonic() + 2
    while not replay.finished and time.monotonic() < deadline:
        time.sleep(0.01)

    assert replay.status == "replayed"
    assert replay.events == [event]
    assert replay.source_run_id == "0123456789ab"


def test_event_log_redacts_credentials_from_persisted_payloads(tmp_path):
    log = EventLog(tmp_path / "trace.jsonl")
    log.emit(
        "tool_call_validated",
        "call with api_key=private-test-secret",
        arguments={"query": "AIza123456789012345678901234567890"},
        api_key="private-test-secret",
    )
    saved = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "private-test-secret" not in saved
    assert "AIza123456789012345678901234567890" not in saved
    assert "[REDACTED]" in saved


def test_api_serves_frontend_and_never_returns_credentials(tmp_path):
    server, _manager = make_server("127.0.0.1", 0, RunManager(_settings(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            page = response.read().decode()
        with urlopen(base + "/api/config", timeout=3) as response:
            config = response.read().decode()
        assert "FODS Research Agent" in page
        assert "private-test-secret" not in config
        assert '"gemini_key_configured": true' in config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_submission_streams_real_simulated_runtime_and_saves_only_validated_brief(tmp_path):
    server, _manager = make_server("127.0.0.1", 0, RunManager(_settings(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    request_body = {
        "topic": "FODS web integration smoke topic",
        "question": "What does the fixture evidence say about graph attention?",
        "mode": "simulate",
        "planner": "fixture",
        "delay_ms": 0,
    }
    try:
        request = Request(
            base + "/api/runs",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Idempotency-Key": "test-run-once"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            started = json.loads(response.read())
        assert response.status == 202

        recorded = []
        with urlopen(base + started["events_url"], timeout=10) as response:
            for line in response:
                if not line.startswith(b"data: "):
                    continue
                envelope = json.loads(line[6:])
                recorded.append(envelope["event"])
                if envelope["event"]["kind"] == "run_finished":
                    break

        kinds = [event["kind"] for event in recorded]
        assert "plan_validated" in kinds
        assert "queue_updated" in kinds
        assert "tool_call_validated" in kinds
        assert "tool_call_completed" in kinds
        assert "evidence_selected" in kinds
        assert "citation_validation" in kinds
        assert "brief_saved" in kinds
        assert not any(event["kind"] == "model_call_completed" for event in recorded)
        brief_path = tmp_path / "data" / "fods" / "briefs" / started["output_path"].split("/")[-1]
        assert brief_path.is_file()
        deadline = time.monotonic() + 3
        status = "starting"
        while status == "starting" and time.monotonic() < deadline:
            with urlopen(base + f"/api/runs/{started['run_id']}") as response:
                status = json.loads(response.read())["status"]
            if status == "starting":
                time.sleep(0.01)
        assert status == "completed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_invalid_citation_records_failed_gate_and_does_not_create_brief(tmp_path):
    manager = RunManager(_settings(tmp_path))
    handle, duplicate = manager.start(
        NewRun(
            topic="FODS invalid citation integration topic",
            question="Will a fabricated citation pass validation?",
            mode="simulate",
            planner="fixture",
            invalid_citation=True,
            delay_ms=0,
        ),
        idempotency_key="invalid-citation-once",
    )
    assert not duplicate
    deadline = time.monotonic() + 8
    while not handle.finished and time.monotonic() < deadline:
        time.sleep(0.01)

    assert handle.finished
    assert handle.status == "failed"
    validation = next(event for event in handle.events if event["kind"] == "citation_validation")
    assert validation["payload"]["valid"] is False
    assert validation["payload"]["recovery_action"] == "block_output_write"
    assert not any(event["kind"] == "brief_saved" for event in handle.events)
    assert not (manager.briefs_dir / f"{handle.run_id}.md").exists()
