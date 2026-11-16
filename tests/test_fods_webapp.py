from __future__ import annotations

import importlib
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from fods import webapp
from fods.events import EventLog
from fods.webapp import (
    BudgetOverrideRequired,
    NewRun,
    RunHandle,
    RunManager,
    _brief_saved_payload,
    _handle_info,
    _rla_stages,
    make_server,
)
from rla.config import Settings
from rla.events import PIPELINE_PHASES


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
    with pytest.raises(ValidationError, match="32-character snapshot hash"):
        NewRun(topic="Graph attention", question="A valid question", context_id="bad-id")


def test_full_literature_pipeline_exposes_bounded_run_settings(tmp_path):
    manager = RunManager(_settings(tmp_path))
    request = NewRun(
        topic="Scientific discovery",
        question="How does AI change experimentation?",
        engine="rla",
        mode="live",
        paper_limit=20,
        provider_wait_seconds=300,
        llm_request_budget=100,
    )
    assert request.engine == "rla"
    assert request.paper_limit == 20
    assert request.provider_wait_seconds == 300
    assert request.llm_request_budget == 100
    assert manager.config()["provider_wait_seconds"] == 300
    assert manager.config()["paper_limit"] == 20
    assert manager.config()["paper_limit_max"] == 20

    with pytest.raises(ValueError, match="requires live mode"):
        manager.start(request.model_copy(update={"mode": "simulate"}))

    with pytest.raises(ValidationError):
        NewRun(
            topic="Scientific discovery",
            question="How does AI change experimentation?",
            engine="rla",
            mode="live",
            paper_limit=21,
        )
    with pytest.raises(ValidationError):
        NewRun(
            topic="Scientific discovery",
            question="How does AI change experimentation?",
            engine="rla",
            mode="live",
            llm_request_budget=1001,
        )


def test_config_exposes_ui_limits_and_live_capabilities(tmp_path):
    manager = RunManager(_settings(tmp_path))
    config = manager.config()

    assert config["limits"]["paper_limit_max"] == config["paper_limit_max"]
    assert config["limits"]["topic_max"] == 300
    assert config["limits"]["llm_request_budget_max"] == 1000
    assert config["capabilities"]["ollama_planner"] == (
        config["providers"]["planner"] == "ollama"
    )
    assert config["capabilities"]["gemini"] is True
    # The test settings configure a Gemini planner, so live research is not
    # available even though a key exists.
    assert config["capabilities"]["rla_live"] is False


def test_budget_uses_the_configured_cap_and_needs_an_explicit_override(tmp_path):
    manager = RunManager(_settings(tmp_path))
    configured = manager.settings.llm_daily_budget

    base = NewRun(topic="Budget bounds", question="How many calls may this run make?")
    assert manager._effective_budget(base) == configured
    assert manager._effective_budget(
        base.model_copy(update={"llm_request_budget": configured})
    ) == configured

    with pytest.raises(BudgetOverrideRequired) as raised:
        manager._effective_budget(
            base.model_copy(update={"llm_request_budget": configured + 1})
        )
    assert raised.value.code == "budget_override_required"
    assert raised.value.fields[0]["loc"] == ("body", "llm_request_budget")
    assert str(configured) in raised.value.fields[0]["msg"]

    override = base.model_copy(
        update={"llm_request_budget": configured + 1, "allow_budget_override": True}
    )
    assert manager._effective_budget(override) == configured + 1


def test_api_rejects_budget_above_cap_with_a_code_and_a_field_error(tmp_path):
    settings = _settings(tmp_path)
    configured = settings.llm_daily_budget
    server, _manager = make_server("127.0.0.1", 0, RunManager(settings))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    body = {
        "topic": "Budget override",
        "question": "Will this request be rejected before it starts?",
        "mode": "simulate",
        "planner": "fixture",
        "llm_request_budget": configured + 1,
        "delay_ms": 0,
    }
    request = Request(
        base + "/api/runs",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with pytest.raises(HTTPError) as raised:
            urlopen(request, timeout=5)
        assert raised.value.code == 400
        payload = json.loads(raised.value.read())
        assert payload["code"] == "budget_override_required"
        assert payload["fields"][0]["loc"] == ["body", "llm_request_budget"]
        assert "daily cap" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_history_reports_recorded_start_and_end_timestamps(tmp_path):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "seq": 1,
            "kind": "run_started",
            "message": "started",
            "payload": {"topic": "Timed run", "mode": "simulate"},
            "timestamp": 1_700_000_000.0,
        },
        {
            "seq": 2,
            "kind": "run_finished",
            "message": "finished",
            "payload": {"succeeded": True, "termination_reason": "completed"},
            "timestamp": 1_700_000_012.5,
        },
    ]
    path = manager.runs_dir / "0123456789ab.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    row = manager.history()[0]
    assert row["run_id"] == "0123456789ab"
    assert row["started_at"] == 1_700_000_000.0
    assert row["ended_at"] == 1_700_000_012.5


def test_live_web_run_rejects_fixture_planner_instead_of_presenting_it_as_live(tmp_path):
    manager = RunManager(_settings(tmp_path))

    with pytest.raises(ValueError, match="fixture planner cannot be used for live research"):
        manager.start(
            NewRun(
                topic="Graph attention",
                question="What does the method do?",
                mode="live",
                planner="fixture",
            )
        )

    with pytest.raises(ValueError, match="requires reuse_context"):
        manager.start(
            NewRun(
                topic="Graph attention",
                question="What does the method do?",
                context_id="a" * 32,
            )
        )

    with pytest.raises(FileNotFoundError, match="no saved context"):
        manager.start(
            NewRun(
                topic="Graph attention",
                question="What does the method do?",
                mode="simulate",
                planner="fixture",
                reuse_context=True,
                context_id="a" * 32,
            )
        )

    with pytest.raises(ValueError, match="only in live research mode"):
        manager.start(
            NewRun(
                topic="Graph attention",
                question="What does the method do?",
                mode="simulate",
                planner="fixture",
                fresh_sources=True,
            )
        )


def test_web_run_passes_fresh_source_policy_to_production_executor(tmp_path, monkeypatch):
    manager = RunManager(_settings(tmp_path))
    captured = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)

        async def result():
            return True

        return result()

    cli = importlib.import_module("fods.cli")
    monkeypatch.setattr(cli, "_execute", fake_execute)
    monkeypatch.setattr("asyncio.run", lambda awaitable: (awaitable.close(), True)[1])
    assert cli._execute is fake_execute
    request = NewRun(
        topic="Fresh source policy test",
        question="Were fresh sources requested?",
        mode="live",
        planner="ollama",
        context_id="a" * 32,
        fresh_sources=True,
    )
    event_handle = RunHandle("aabbccddeeff", "simulate", request.topic)
    manager._execute(event_handle, request, EventLog(sink=event_handle.publish))

    assert event_handle.finished
    assert captured["fresh_sources"] is True
    assert captured["context_id"] == "a" * 32


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


def test_api_serves_react_bundle_assets_and_never_returns_credentials(tmp_path, monkeypatch):
    web_root = tmp_path / "web"
    assets = web_root / "dist" / "assets"
    assets.mkdir(parents=True)
    (web_root / "dist" / "index.html").write_text(
        '<!doctype html><title>FODS · Research Studio</title>'
        '<script src="/shell-core.js" defer></script>'
        '<script type="module" src="/assets/index-test.js"></script>'
        '<link rel="stylesheet" href="/assets/index-test.css">',
        encoding="utf-8",
    )
    (assets / "index-test.js").write_text(
        "createRoot(document.getElementById('root'))", encoding="utf-8"
    )
    (assets / "index-test.css").write_text(".app-frame{min-height:100vh}", encoding="utf-8")
    (web_root / "shell-core.js").write_text("window.FODSFrontendCore = {};", encoding="utf-8")
    monkeypatch.setattr("fods.webapp.WEB_ROOT", web_root)
    server, _manager = make_server("127.0.0.1", 0, RunManager(_settings(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            page = response.read().decode()
        with urlopen(base + "/api/config", timeout=3) as response:
            config = response.read().decode()
        with urlopen(base + "/assets/index-test.js", timeout=3) as response:
            script = response.read().decode()
            script_type = response.headers.get("Content-Type")
        with urlopen(base + "/assets/index-test.css", timeout=3) as response:
            styles = response.read().decode()
        with urlopen(base + "/shell-core.js", timeout=3) as response:
            core = response.read().decode()
        assert "FODS · Research Studio" in page
        assert "/assets/index-test.js" in page
        assert "/assets/index-test.css" in page
        assert "createRoot" in script
        assert script_type.startswith("text/javascript")
        assert ".app-frame" in styles
        assert "FODSFrontendCore" in core
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


def test_handle_info_reports_authoritative_status_timing_and_pipeline():
    handle = RunHandle("0123456789ab", "simulate", "Timed run", "briefs/x.md")
    handle.events = [
        {
            "seq": 1,
            "kind": "run_started",
            "message": "started",
            "payload": {"engine": "fods", "pipeline": "fods-scheduler"},
            "timestamp": 100.0,
        },
        {
            "seq": 2,
            "kind": "run_finished",
            "message": "finished",
            "payload": {
                "succeeded": True,
                "termination_reason": "completed_with_partial_sources",
                "elapsed_ms": 12.5,
                "unavailable_sources": ["crossref"],
            },
            "timestamp": 112.5,
        },
    ]
    handle.status = "partial"

    info = _handle_info(handle)

    assert info["status"] == "partial"
    assert info["status_reason"] == "completed_with_partial_sources"
    assert info["pipeline"] == "fods-scheduler"
    assert info["started_at"] == 100.0
    assert info["ended_at"] == 112.5
    assert info["elapsed_ms"] == 12.5
    assert info["unavailable_sources"] == ["crossref"]
    assert info["event_count"] == 2

    # The RLA pipeline records the same fact as `failed_sources`.
    handle.events[1]["payload"].pop("unavailable_sources")
    handle.events[1]["payload"]["failed_sources"] = ["semantic_scholar"]
    assert _handle_info(handle)["unavailable_sources"] == ["semantic_scholar"]


def test_handle_info_derives_elapsed_from_timestamps_when_absent():
    handle = RunHandle("0123456789ab", "simulate", "Old log")
    handle.events = [
        {"seq": 1, "kind": "run_started", "message": "s", "payload": {}, "timestamp": 10.0},
        {"seq": 2, "kind": "run_finished", "message": "f", "payload": {}, "timestamp": 10.25},
    ]
    handle.status = "completed"

    info = _handle_info(handle)

    assert info["status_reason"] == ""
    assert info["elapsed_ms"] == 250.0
    # No pipeline recorded in this old log: the engine decides the label.
    assert info["pipeline"] == "fods-scheduler"
    assert info["unavailable_sources"] == []


def test_replay_keeps_replayed_status_and_reports_why_it_ended(tmp_path, monkeypatch):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {"seq": 1, "kind": "run_started", "message": "started", "payload": {}, "timestamp": 1.0},
        {
            "seq": 2,
            "kind": "run_finished",
            "message": "finished",
            "payload": {"succeeded": False, "termination_reason": "plan_rejected"},
            "timestamp": 1.5,
        },
    ]
    (manager.runs_dir / "0123456789ab.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    monkeypatch.setattr("fods.cli._execute", lambda *_a, **_k: None, raising=False)

    replay = manager.replay("0123456789ab", speed_ms=0)
    deadline = time.monotonic() + 2
    while not replay.finished and time.monotonic() < deadline:
        time.sleep(0.01)

    info = _handle_info(replay)
    assert info["status"] == "replayed"
    assert info["status_reason"] == "plan_rejected"


def test_brief_is_served_as_markdown_json_and_download(tmp_path):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    manager.briefs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "0123456789ab"
    brief_path = manager.briefs_dir / f"{run_id}.md"
    brief_path.write_text("# Brief\n\nCited answer.\n", encoding="utf-8")
    events = [
        {"seq": 1, "kind": "run_started", "message": "started", "payload": {}, "timestamp": 1.0},
        {
            "seq": 2,
            "kind": "context_ready",
            "message": "context",
            "payload": {"source_names": ["arxiv", "dblp"]},
            "timestamp": 2.0,
        },
        {
            "seq": 3,
            "kind": "answer_ready",
            "message": "answer",
            "payload": {"citations": ["[1]"], "answer": "text"},
            "timestamp": 3.0,
        },
        {
            "seq": 4,
            "kind": "brief_saved",
            "message": "saved",
            "payload": {"path": str(brief_path)},
            "timestamp": 4.0,
        },
    ]
    (manager.runs_dir / f"{run_id}.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + f"/api/runs/{run_id}/brief") as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/markdown")
            assert response.headers.get("Content-Disposition") is None
            assert response.read().decode("utf-8") == "# Brief\n\nCited answer.\n"

        with urlopen(base + f"/api/runs/{run_id}/brief?download=1") as response:
            assert (
                response.headers["Content-Disposition"]
                == f'attachment; filename="{run_id}.md"'
            )
            assert response.read().decode("utf-8").startswith("# Brief")

        with urlopen(base + f"/api/runs/{run_id}/brief?format=json") as response:
            document = json.loads(response.read())
        assert document["run_id"] == run_id
        assert document["markdown"].startswith("# Brief")
        assert document["citations"] == ["[1]"]
        assert document["sources"] == ["arxiv", "dblp"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_brief_404s_with_a_code_when_no_brief_was_saved(tmp_path):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "0123456789ab"
    (manager.runs_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "kind": "run_started", "message": "s", "payload": {}}) + "\n",
        encoding="utf-8",
    )
    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(HTTPError) as raised:
            urlopen(base + f"/api/runs/{run_id}/brief", timeout=5)
        assert raised.value.code == 404
        assert json.loads(raised.value.read())["code"] == "brief_not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stream_envelope_carries_status_and_reason(tmp_path):
    server, _mgr = make_server("127.0.0.1", 0, RunManager(_settings(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    request = Request(
        base + "/api/runs",
        data=json.dumps(
            {
                "topic": "SSE status",
                "question": "Does the stream state how the run ended?",
                "mode": "simulate",
                "planner": "fixture",
                "delay_ms": 0,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            started = json.loads(response.read())

        envelopes = []
        with urlopen(base + started["events_url"], timeout=10) as response:
            for line in response:
                if not line.startswith(b"data: "):
                    continue
                envelope = json.loads(line[6:])
                envelopes.append(envelope)
                if envelope["event"]["kind"] == "run_finished":
                    break

        assert envelopes, "no streamed envelopes"
        for envelope in envelopes:
            assert "status" in envelope
            assert "status_reason" in envelope
        first = envelopes[0]["event"]
        assert first["kind"] == "run_started"
        assert first["payload"]["engine"] == "fods"
        assert first["payload"]["pipeline"] == "fods-scheduler"
        assert first["summary"] and len(first["summary"]) <= 90
        assert first["class"] == "runtime"
        assert "event_class" not in first
        final = envelopes[-1]
        assert final["status"] == "completed"
        assert final["status_reason"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rla_stage_rail_is_the_ordered_pipeline():
    stages = _rla_stages()

    assert [stage["id"] for stage in stages] == [str(phase) for phase in PIPELINE_PHASES]
    assert [stage["order"] for stage in stages] == list(range(len(PIPELINE_PHASES)))
    assert all(stage["label"] and stage["label"][0].isupper() for stage in stages)
    assert {"search", "fetch", "fulltext", "extract", "answer", "done"} <= {
        stage["id"] for stage in stages
    }


def test_invalid_run_request_returns_a_code_and_field_errors(tmp_path):
    server, _mgr = make_server("127.0.0.1", 0, RunManager(_settings(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    request = Request(
        base + "/api/runs",
        data=json.dumps(
            {"topic": "Bounds", "question": "Is this rejected?", "concurrency": 99}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with pytest.raises(HTTPError) as raised:
            urlopen(request, timeout=5)
        assert raised.value.code == 400
        payload = json.loads(raised.value.read())
        assert payload["code"] == "validation"
        assert any(error["loc"][-1] == "concurrency" for error in payload["fields"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# --- slice 3b: disk fallback, tolerance, hygiene, origin guard ---------------


def _write_log(manager: RunManager, run_id: str, events: list[dict]) -> None:
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    (manager.runs_dir / f"{run_id}.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def _log_events(topic: str = "Restart", store: str = "") -> list[dict]:
    started = {
        "seq": 1,
        "kind": "run_started",
        "message": "started",
        "payload": {"engine": "fods", "mode": "simulate", "topic": topic},
        "timestamp": 10.0,
    }
    if store:
        started["payload"]["extraction_store"] = store
    return [
        started,
        {
            "seq": 2,
            "kind": "run_finished",
            "message": "done",
            "payload": {
                "succeeded": True,
                "termination_reason": "completed",
                "elapsed_ms": 12.5,
            },
            "timestamp": 11.0,
        },
    ]


def test_history_is_cached_and_invalidated_by_an_append(tmp_path, monkeypatch):
    manager = RunManager(_settings(tmp_path))
    run_id = "0123456789ab"
    path = manager.runs_dir / f"{run_id}.jsonl"
    _write_log(manager, run_id, _log_events())

    real_read = webapp.read_events
    calls = {"count": 0}

    def counting(*args, **kwargs):
        calls["count"] += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(webapp, "read_events", counting)

    first = manager.history()
    after_first = calls["count"]
    second = manager.history()

    assert first == second
    assert calls["count"] == after_first  # cached: no second parse
    assert first[0]["event_count"] == 2

    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"seq": 3, "kind": "log_note", "message": "appended", "payload": {}}
            )
            + "\n"
        )

    third = manager.history()

    assert calls["count"] > after_first  # (mtime, size) changed
    assert third[0]["event_count"] == 3


def test_history_keeps_a_run_with_a_corrupt_line_and_reports_it(tmp_path):
    manager = RunManager(_settings(tmp_path))
    _write_log(manager, "0123456789ab", _log_events()[:1])
    (manager.runs_dir / "0123456789ab.jsonl").open("a", encoding="utf-8").write(
        "{ not json at all\n"
    )

    rows = manager.history()

    assert [row["run_id"] for row in rows] == ["0123456789ab"]
    assert rows[0]["status"] == "interrupted"  # no readable run_finished
    assert rows[0]["warnings"] == 1
    assert rows[0]["event_count"] == 1


def test_history_rewrites_absolute_paths_before_they_leave_the_server(tmp_path):
    manager = RunManager(_settings(tmp_path))
    brief = manager.briefs_dir / "0123456789ab.md"
    events = _log_events()
    events.append(
        {
            "seq": 3,
            "kind": "brief_saved",
            "message": "saved",
            "payload": {"path": str(brief), "saved": True},
            "timestamp": 12.0,
        }
    )
    _write_log(manager, "0123456789ab", events)

    row = manager.history()[0]

    assert row["output_path"] == "data/fods/briefs/0123456789ab.md"
    assert str(tmp_path) not in json.dumps(row)


def test_info_and_stream_come_from_disk_after_a_restart(tmp_path):
    settings = _settings(tmp_path)
    first = RunManager(settings)
    run_id = "0123456789ab"
    _write_log(first, run_id, _log_events(store=str(tmp_path / "data" / "x.jsonl")))

    restarted = RunManager(settings)
    info = restarted.info(run_id)

    assert info is not None
    assert info["historical"] is True
    assert info["status"] == "completed"
    assert info["status_reason"] == "completed"
    assert info["warnings"] == 0

    server, _mgr = make_server("127.0.0.1", 0, restarted)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + f"/api/runs/{run_id}", timeout=5) as response:
            served = json.loads(response.read())
        assert served["historical"] is True

        request = Request(
            base + f"/api/runs/{run_id}/events", headers={"Connection": "close"}
        )
        lines: list[str] = []
        retry_seen = False
        with urlopen(request, timeout=5) as response:
            for raw in response:
                text = raw.decode("utf-8")
                if text.startswith("retry:"):
                    retry_seen = True
                if text.startswith("data: "):
                    lines.append(text)
                    if len(lines) == 2:
                        break
        assert retry_seen
        assert len(lines) == 2
        body = "".join(lines)
        assert '"historical":true' in body
        assert str(tmp_path) not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_disk_stream_honours_last_event_id(tmp_path):
    manager = RunManager(_settings(tmp_path))
    run_id = "0123456789ab"
    _write_log(manager, run_id, _log_events())

    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(
            base + f"/api/runs/{run_id}/events",
            headers={"Last-Event-ID": "1", "Connection": "close"},
        )
        with urlopen(request, timeout=5) as response:
            lines = []
            for raw in response:
                if raw.startswith(b"data: "):
                    lines.append(raw)
                    break
        assert len(lines) == 1
        assert json.loads(lines[0][6:])["event"]["seq"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_a_corrupt_log_without_a_brief_is_a_500_with_a_code(tmp_path):
    manager = RunManager(_settings(tmp_path))
    manager.runs_dir.mkdir(parents=True, exist_ok=True)
    (manager.runs_dir / "0123456789ab.jsonl").write_text("{broken\n", encoding="utf-8")

    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(HTTPError) as raised:
            urlopen(base + "/api/runs/0123456789ab/brief", timeout=5)
        assert raised.value.code == 500
        assert json.loads(raised.value.read())["code"] == "brief_unreadable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_an_oversize_brief_is_refused_with_413(tmp_path):
    manager = RunManager(_settings(tmp_path))
    brief = manager.briefs_dir / "0123456789ab.md"
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text("x" * (webapp.MAX_BRIEF_BYTES + 1), encoding="utf-8")
    events = _log_events()
    events.append(
        {
            "seq": 3,
            "kind": "brief_saved",
            "message": "saved",
            "payload": {"path": str(brief)},
            "timestamp": 12.0,
        }
    )
    _write_log(manager, "0123456789ab", events)

    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(HTTPError) as raised:
            urlopen(base + "/api/runs/0123456789ab/brief", timeout=10)
        assert raised.value.code == 413
        assert json.loads(raised.value.read())["code"] == "brief_too_large"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_the_brief_validation_flag_follows_the_recorded_stripped_citations():
    clean = _brief_saved_payload("data/fods/briefs/x.md", [])
    dropped = _brief_saved_payload("data/fods/briefs/x.md", ["[9]"])

    assert clean["citations_validated"] is True
    assert clean["stripped_citations"] == []
    assert dropped["citations_validated"] is False
    assert dropped["stripped_citations"] == ["[9]"]


def test_finished_handles_are_evicted_but_stay_readable_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "MAX_FINISHED_HANDLES", 1)
    manager = RunManager(_settings(tmp_path))
    run_ids = ["0" * 12, "1" * 12]
    for run_id in run_ids:
        _write_log(manager, run_id, _log_events())
        handle = RunHandle(run_id, "simulate", "Restart")
        handle.status = "completed"
        handle.finished = True
        manager.runs[run_id] = handle

    manager._evict_finished()

    assert len(manager.runs) == 1
    evicted = next(run_id for run_id in run_ids if run_id not in manager.runs)
    info = manager.info(evicted)
    assert info is not None and info["historical"] is True
    assert len(manager.history()) == 2


def _post_run(base: str, headers: dict[str, str]):
    request = Request(
        base + "/api/runs",
        data=json.dumps(
            {
                "topic": "Origin guard",
                "question": "Is a foreign page allowed to start a run?",
                "mode": "simulate",
                "planner": "fixture",
                "delay_ms": 0,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    return urlopen(request, timeout=10)


def test_a_foreign_origin_or_host_cannot_start_a_run(tmp_path):
    manager = RunManager(_settings(tmp_path))
    server, _mgr = make_server("127.0.0.1", 0, manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(HTTPError) as raised:
            _post_run(base, {"Origin": "http://evil.example"})
        assert raised.value.code == 403
        assert json.loads(raised.value.read())["code"] == "forbidden_origin"

        with pytest.raises(HTTPError) as raised:
            _post_run(base, {"Host": "evil.example"})
        assert raised.value.code == 403
        assert json.loads(raised.value.read())["code"] == "forbidden_host"

        assert manager.runs == {}

        with _post_run(base, {"Origin": base}) as response:
            assert response.status == 202
            started = json.loads(response.read())
        deadline = time.monotonic() + 10
        handle = manager.get(started["run_id"])
        while handle is not None and not handle.finished and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_a_configured_dev_origin_is_allowed(tmp_path, monkeypatch):
    from fods.webapp import _origin_allowed

    monkeypatch.setenv("RLA_FODS_DEV_ORIGIN", "http://127.0.0.1:5173")
    assert _origin_allowed("http://127.0.0.1:5173", 8901) is True
    assert _origin_allowed("http://127.0.0.1:9999", 8901) is False
    assert _origin_allowed("", 8901) is True

