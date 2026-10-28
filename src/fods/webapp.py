"""Local browser frontend API for the FODS runtime.

The browser is a read-only observer of canonical runtime events. Runs and replay
are owned by this module and the existing ``_execute`` / ``run_plan`` pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fods.events import EventLog, read_events
from fods.fixtures import FIXTURE_PAPERS
from fods.safety import redact_text, safe_value
from fods.visualize import write_run_html
from rla.config import Settings, get_settings

WEB_ROOT = Path(__file__).with_name("web")
RUN_ID = re.compile(r"^[0-9a-f]{12}$")
OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.md$")


class NewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=3, max_length=300)
    question: str = Field(min_length=3, max_length=1000)
    mode: Literal["live", "simulate"] = "simulate"
    planner: Literal["auto", "ollama", "fixture"] = "auto"
    schedule: Literal["fifo", "priority"] = "fifo"
    concurrency: int = Field(default=3, ge=1, le=8)
    source_limit: int = Field(default=3, ge=2, le=5)
    output_name: str = ""
    reuse_context: bool = False
    fresh_sources: bool = False
    inject_cycle: bool = False
    invalid_citation: bool = False
    fail_sources: list[str] = Field(default_factory=list, max_length=5)
    delay_ms: int = Field(default=150, ge=0, le=5000)

    @field_validator("topic", "question")
    @classmethod
    def strip_and_reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("fail_sources")
    @classmethod
    def unique_fail_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("fail_sources must not contain duplicates")
        return value


@dataclass
class RunHandle:
    run_id: str
    run_kind: Literal["live", "simulate", "replay"]
    topic: str
    output_path: str = ""
    event_path: Path | None = None
    source_run_id: str = ""
    status: str = "starting"
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    condition: threading.Condition = field(default_factory=threading.Condition)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    finished: bool = False

    def publish(self, event: Any) -> None:
        value = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        with self.condition:
            self.events.append(value)
            self.condition.notify_all()

    def finish(self, status: str, error: str = "") -> None:
        with self.condition:
            self.status = status
            self.error = redact_text(error)[:320]
            self.finished = True
            self.condition.notify_all()


class RunManager:
    """Own background runs, event subscriptions, local history, and replay."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.workspace = self.settings.data_dir.resolve().parent
        self.root = self.settings.data_dir.resolve()
        self.runs_dir = self.root / "fods" / "runs"
        self.briefs_dir = self.root / "fods" / "briefs"
        self.topics_dir = self.root / "fods" / "topics"
        self.runs: dict[str, RunHandle] = {}
        self.idempotency: dict[str, str] = {}
        self.lock = threading.RLock()

    def config(self) -> dict[str, Any]:
        settings = self.settings
        models = {
            "planner": settings.canonical_model(settings.model_for_structured),
            "structured": settings.canonical_model(settings.model_for_structured),
            "answer": settings.canonical_model(settings.model_for_answer),
            "embedding": settings.canonical_model(settings.embedding_model),
        }
        return {
            "models": models,
            "providers": {role: model.split("/", 1)[0] for role, model in models.items()},
            "gemini_key_configured": bool(settings.gemini_api_key),
            "gemini_opted_in": os.getenv("RLA_FODS_ALLOW_GEMINI") == "1",
            "source_names": list(FIXTURE_PAPERS),
            "source_quorum": 2,
            "modes": ["live", "simulate", "replay"],
        }

    @staticmethod
    def _output_name(request: NewRun, run_id: str) -> str:
        name = request.output_name.strip()
        if not name:
            name = f"{run_id}.md"
        if not OUTPUT_NAME.fullmatch(name) or name in {".", ".."}:
            raise ValueError("output_name must be a simple Markdown filename")
        return name

    def start(self, request: NewRun, idempotency_key: str = "") -> tuple[RunHandle, bool]:
        unknown = set(request.fail_sources) - set(FIXTURE_PAPERS)
        if unknown:
            raise ValueError(f"unknown demo source(s): {', '.join(sorted(unknown))}")
        if request.fail_sources and request.mode != "simulate":
            raise ValueError("controlled source failures are available only in simulation mode")
        if request.mode == "simulate" and request.planner == "ollama":
            raise ValueError("deterministic simulation uses the fixture planner")
        if request.inject_cycle and request.reuse_context:
            raise ValueError("cycle demonstration requires a new simulated research plan")
        if request.invalid_citation and request.mode != "simulate":
            raise ValueError("invalid-citation demonstration is available only in simulation mode")
        key = idempotency_key.strip()[:120]
        with self.lock:
            if key and key in self.idempotency:
                existing = self.runs.get(self.idempotency[key])
                if existing:
                    return existing, True
            run_id = uuid.uuid4().hex[:12]
            output_name = self._output_name(request, run_id)
            output = f"data/fods/briefs/{output_name}"
            output_path = (self.workspace / output).resolve()
            if not output_path.is_relative_to(self.workspace):
                raise ValueError("output must stay inside this workspace")
            if output_path.exists():
                raise FileExistsError("output already exists; choose a different filename")
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            self.briefs_dir.mkdir(parents=True, exist_ok=True)
            event_path = self.runs_dir / f"{run_id}.jsonl"
            handle = RunHandle(run_id, request.mode, request.topic, output, event_path)
            self.runs[run_id] = handle
            if key:
                self.idempotency[key] = run_id

        event_log = EventLog(event_path, handle.publish)
        thread = threading.Thread(
            target=self._execute,
            args=(handle, request, event_log),
            name=f"fods-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return handle, False

    def _execute(self, handle: RunHandle, request: NewRun, event_log: EventLog) -> None:
        from fods.cli import _execute

        fail_sources = set(request.fail_sources)
        unknown = fail_sources - set(FIXTURE_PAPERS)
        if unknown:
            handle.finish("failed", f"unknown demo source(s): {', '.join(sorted(unknown))}")
            return
        try:
            ok = asyncio.run(
                _execute(
                    topic=request.topic,
                    question=request.question,
                    output=handle.output_path,
                    request=f"Research {request.topic} and answer: {request.question}",
                    mode=request.mode,
                    planner_mode=request.planner,
                    schedule=request.schedule,
                    concurrency=request.concurrency,
                    reuse_context=request.reuse_context,
                    fail_sources=fail_sources,
                    inject_cycle=request.inject_cycle,
                    invalid_citation=request.invalid_citation,
                    simulated_delay=request.delay_ms / 1000,
                    event_file=handle.event_path,
                    source_limit=request.source_limit,
                    run_id=handle.run_id,
                    event_log=event_log,
                    print_cli=False,
                    cancel_event=handle.cancel_event,
                    settings=self.settings,
                    workspace=self.workspace,
                )
            )
            events = handle.events
            if handle.event_path and handle.event_path.exists():
                write_run_html(
                    read_events(handle.event_path), handle.event_path.with_suffix(".html")
                )
            finish = next(
                (event for event in reversed(events) if event["kind"] == "run_finished"), None
            )
            if finish is not None:
                payload = finish.get("payload", {})
                if payload.get("termination_reason") == "completed_with_partial_sources":
                    status = "partial"
                elif payload.get("succeeded"):
                    status = "completed"
                else:
                    status = (
                        "cancelled"
                        if payload.get("termination_reason") == "cancelled"
                        else "failed"
                    )
            else:
                rejected = any(event["kind"] == "plan_rejected" for event in events)
                event_log.emit(
                    "run_finished",
                    "plan rejected before tools executed"
                    if rejected
                    else "run failed before completion",
                    run_id=handle.run_id,
                    succeeded=False,
                    termination_reason="plan_rejected" if rejected else "failed",
                    mode=request.mode,
                )
                status = "failed"
            handle.finish(status, "" if ok else "run did not complete successfully")
        except Exception as exc:
            event_log.emit(
                "run_failed",
                f"run failed: {type(exc).__name__}: {str(exc)[:240]}",
                run_id=handle.run_id,
                mode=request.mode,
            )
            event_log.emit(
                "run_finished",
                "run failed before completion",
                run_id=handle.run_id,
                succeeded=False,
                termination_reason="failed",
                mode=request.mode,
            )
            handle.finish("failed", f"{type(exc).__name__}: {exc}")

    def get(self, run_id: str) -> RunHandle | None:
        with self.lock:
            return self.runs.get(run_id)

    def history(self) -> list[dict[str, Any]]:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for path in sorted(
            self.runs_dir.glob("[0-9a-f]" * 12 + ".jsonl"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                events = read_events(path)
            except (OSError, ValueError):
                continue
            started = next((event for event in events if event["kind"] == "run_started"), {})
            plan = next((event for event in events if event["kind"] == "plan_received"), {})
            finish = next(
                (event for event in reversed(events) if event["kind"] == "run_finished"), {}
            )
            saved = next((event for event in events if event["kind"] == "brief_saved"), {})
            actual_models = [
                {
                    "stage": event.get("payload", {}).get("stage"),
                    "provider": event.get("payload", {}).get("provider"),
                    "model": event.get("payload", {}).get("model"),
                }
                for event in events
                if event["kind"] == "model_call_completed"
            ]
            result.append(
                {
                    "run_id": path.stem,
                    "mode": started.get("payload", {}).get(
                        "mode", plan.get("payload", {}).get("mode", "unknown")
                    ),
                    "topic": started.get("payload", {}).get(
                        "topic", plan.get("payload", {}).get("topic", "")
                    ),
                    "status": _status_from_finish(finish),
                    "output_path": saved.get("payload", {}).get("path", ""),
                    "models_used": actual_models,
                    "elapsed_ms": finish.get("payload", {}).get("elapsed_ms"),
                    "event_count": len(events),
                    "visualization_url": f"/api/runs/{path.stem}/visualization",
                }
            )
        return result[:100]

    def replay(self, source_run_id: str, speed_ms: int = 30) -> RunHandle:
        if not RUN_ID.fullmatch(source_run_id):
            raise ValueError("invalid run id")
        path = self.runs_dir / f"{source_run_id}.jsonl"
        if not path.is_file() or not path.resolve().is_relative_to(self.runs_dir.resolve()):
            raise FileNotFoundError("recorded run was not found")
        events = read_events(path)
        replay_id = uuid.uuid4().hex[:12]
        handle = RunHandle(replay_id, "replay", "", source_run_id=source_run_id)
        with self.lock:
            self.runs[replay_id] = handle

        def play() -> None:
            for event in events:
                handle.publish(event)
                if speed_ms:
                    time.sleep(min(speed_ms, 250) / 1000)
            handle.finish("replayed")

        threading.Thread(target=play, name=f"fods-replay-{replay_id}", daemon=True).start()
        return handle

    def contexts(self) -> list[dict[str, Any]]:
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        contexts = []
        for path in sorted(
            self.topics_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        ):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            contexts.append(
                {
                    "topic": value.get("topic", ""),
                    "paper_count": value.get("paper_count", 0),
                    "abstract_count": value.get("abstract_count", 0),
                    "built_at": value.get("built_at", ""),
                    "context_hash": value.get("context_hash", ""),
                }
            )
        return contexts[:100]

    def brief(self, run_id: str) -> str | None:
        handle = self.get(run_id)
        events = handle.events if handle else []
        if not events and RUN_ID.fullmatch(run_id):
            path = self.runs_dir / f"{run_id}.jsonl"
            if path.is_file():
                events = read_events(path)
        saved = next((event for event in events if event["kind"] == "brief_saved"), None)
        if not saved:
            return None
        target = Path(saved.get("payload", {}).get("path", "")).resolve()
        if not target.is_relative_to(self.briefs_dir.resolve()) or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")


def _status_from_finish(event: dict[str, Any]) -> str:
    payload = event.get("payload", {})
    if not payload:
        return "unknown"
    if payload.get("termination_reason") == "completed_with_partial_sources":
        return "partial"
    if payload.get("succeeded"):
        return "completed"
    if payload.get("termination_reason") == "cancelled":
        return "cancelled"
    return "failed"


def make_server(host: str = "127.0.0.1", port: int = 8765, manager: RunManager | None = None):
    manager = manager or RunManager()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *args: Any) -> None:
            return

        def _headers(self, content_type: str, length: int | None = None) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'",
            )
            if length is not None:
                self.send_header("Content-Length", str(length))

        def _json(self, status: int, value: Any) -> None:
            body = json.dumps(safe_value(value), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if not 1 <= length <= 65536:
                raise ValueError("request body must be between 1 and 65536 bytes")
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                return self._static("index.html", "text/html; charset=utf-8")
            if path == "/app.js":
                return self._static("app.js", "text/javascript; charset=utf-8")
            if path == "/styles.css":
                return self._static("styles.css", "text/css; charset=utf-8")
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/api/config":
                return self._json(200, manager.config())
            if path == "/api/history":
                return self._json(200, {"runs": manager.history()})
            if path == "/api/contexts":
                return self._json(200, {"contexts": manager.contexts()})
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})", path)
            if match:
                handle = manager.get(match.group(1))
                if handle is None:
                    return self._json(404, {"error": "run not found"})
                return self._json(200, _handle_info(handle))
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})/events", path)
            if match:
                return self._events(manager, match.group(1), parse_qs(parsed.query))
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})/brief", path)
            if match:
                brief = manager.brief(match.group(1))
                if brief is None:
                    return self._json(404, {"error": "no saved brief for this run"})
                body = brief.encode("utf-8")
                self.send_response(200)
                self._headers("text/markdown; charset=utf-8", len(body))
                self.end_headers()
                return self.wfile.write(body)
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})/visualization", path)
            if match:
                event_path = manager.runs_dir / f"{match.group(1)}.html"
                if event_path.is_file() and event_path.resolve().is_relative_to(
                    manager.runs_dir.resolve()
                ):
                    body = event_path.read_bytes()
                    self.send_response(200)
                    self._headers("text/html; charset=utf-8", len(body))
                    self.end_headers()
                    return self.wfile.write(body)
                return self._json(404, {"error": "run visualization not found"})
            return self._json(404, {"error": "not found"})

        def _static(self, name: str, content_type: str) -> None:
            path = WEB_ROOT / name
            if not path.is_file():
                return self._json(404, {"error": "frontend asset missing"})
            body = path.read_bytes()
            self.send_response(200)
            self._headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

        def _events(
            self, run_manager: RunManager, run_id: str, query: dict[str, list[str]]
        ) -> None:
            handle = run_manager.get(run_id)
            if handle is None:
                return self._json(404, {"error": "run not found"})
            try:
                after = int(self.headers.get("Last-Event-ID", query.get("after", ["0"])[0]))
            except ValueError:
                after = 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            index = 0
            try:
                while True:
                    with handle.condition:
                        while index >= len(handle.events) and not handle.finished:
                            handle.condition.wait(timeout=1.0)
                            if index >= len(handle.events):
                                self.wfile.write(b": keep-alive\n\n")
                                self.wfile.flush()
                        pending = handle.events[index:]
                        finished = handle.finished
                    for event in pending:
                        index += 1
                        event_id = int(event.get("seq", index))
                        if event_id <= after:
                            continue
                        envelope = {
                            "run_kind": handle.run_kind,
                            "source_run_id": handle.source_run_id or None,
                            "event": event,
                        }
                        data = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
                        self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode())
                        self.wfile.flush()
                        after = event_id
                    if finished and index >= len(handle.events):
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                return

        def do_POST(self) -> None:  # noqa: N802
            try:
                value = self._body()
                if self.path == "/api/runs":
                    request = NewRun.model_validate(value)
                    if request.reuse_context and request.planner == "ollama":
                        return self._json(
                            400, {"error": "saved-context runs use the deterministic planner"}
                        )
                    handle, duplicate = manager.start(
                        request, self.headers.get("Idempotency-Key", "")
                    )
                    return self._json(200 if duplicate else 202, _handle_info(handle))
                if self.path == "/api/replay":
                    run_id = str(value.get("run_id", ""))
                    speed = int(value.get("speed_ms", 30))
                    handle = manager.replay(run_id, max(0, min(speed, 250)))
                    return self._json(202, _handle_info(handle))
                return self._json(404, {"error": "not found"})
            except ValidationError as exc:
                return self._json(
                    400, {"error": "invalid run request", "fields": exc.errors(include_url=False)}
                )
            except FileExistsError as exc:
                return self._json(409, {"error": str(exc)})
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            except FileNotFoundError as exc:
                return self._json(404, {"error": str(exc)})

        def do_DELETE(self) -> None:  # noqa: N802
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})", urlparse(self.path).path)
            if not match:
                return self._json(404, {"error": "not found"})
            handle = manager.get(match.group(1))
            if handle is None:
                return self._json(404, {"error": "run not found"})
            if handle.finished:
                return self._json(409, {"error": "run is already finished"})
            handle.cancel_event.set()
            return self._json(202, {"run_id": handle.run_id, "status": "cancellation_requested"})

    return ThreadingHTTPServer((host, port), Handler), manager


def _handle_info(handle: RunHandle) -> dict[str, Any]:
    return {
        "run_id": handle.run_id,
        "run_kind": handle.run_kind,
        "source_run_id": handle.source_run_id or None,
        "topic": handle.topic,
        "status": handle.status,
        "event_count": len(handle.events),
        "error": handle.error,
        "output_path": handle.output_path,
        "events_url": f"/api/runs/{handle.run_id}/events",
    }
