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

from fods.event_meta import PHASE_LABEL
from fods.events import EventLog, read_events
from fods.fixtures import FIXTURE_PAPERS
from fods.safety import redact_text, safe_value, sanitise_paths
from fods.visualize import write_run_html
from rla.config import Settings, get_settings
from rla.events import PIPELINE_PHASES

WEB_ROOT = Path(__file__).with_name("web")
RUN_ID = re.compile(r"^[0-9a-f]{12}$")
OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.md$")
MAX_LIVE_PAPER_LIMIT = 20
#: A generated brief is small; anything larger is not something we wrote (A-08).
MAX_BRIEF_BYTES = 2 * 1024 * 1024
#: Finished runs stay in memory for recent polling; older ones are served from
#: disk (A-02), so the ring can stay small.
MAX_FINISHED_HANDLES = 24
STREAM_RETRY_MS = 3000


class NewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=3, max_length=300)
    question: str = Field(min_length=3, max_length=1000)
    engine: Literal["rla", "fods"] = "fods"
    mode: Literal["live", "simulate"] = "simulate"
    planner: Literal["auto", "ollama", "fixture"] = "auto"
    schedule: Literal["fifo", "priority"] = "fifo"
    concurrency: int = Field(default=3, ge=1, le=8)
    source_limit: int = Field(default=3, ge=2, le=5)
    output_name: str = ""
    reuse_context: bool = False
    context_id: str = ""
    fresh_sources: bool = False
    inject_cycle: bool = False
    invalid_citation: bool = False
    fail_sources: list[str] = Field(default_factory=list, max_length=5)
    delay_ms: int = Field(default=150, ge=0, le=5000)
    paper_limit: int = Field(default=MAX_LIVE_PAPER_LIMIT, ge=2, le=MAX_LIVE_PAPER_LIMIT)
    provider_wait_seconds: float = Field(default=300.0, ge=0, le=3600)
    #: None means "use the configured daily cap" (settings.llm_daily_budget).
    #: The server used to default this to 100 independently of the operator's
    #: configured 15, which silently overrode the cap (A-06).
    llm_request_budget: int | None = Field(default=None, ge=1, le=1000)
    #: An explicit opt-in is required to exceed the configured cap for one run.
    allow_budget_override: bool = False

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

    @field_validator("context_id")
    @classmethod
    def valid_context_id(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("context_id must be a 32-character snapshot hash")
        return value


class BudgetOverrideRequired(ValueError):
    """The request asks for more model calls than the operator configured.

    Carries stable machine-readable fields so the client can render the message
    next to the budget input (A-06) instead of guessing from a prose error.
    """

    code = "budget_override_required"

    def __init__(self, requested: int, configured: int) -> None:
        super().__init__(
            f"{requested} model requests exceeds the configured daily cap of {configured}; "
            "set allow_budget_override to raise it for this run"
        )
        self.requested = requested
        self.configured = configured
        self.fields = [
            {
                "loc": ("body", "llm_request_budget"),
                "msg": f"above the configured daily cap of {configured}",
                "type": "value_error",
            }
        ]


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
    engine: str = "fods"

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
        # A-09: history entries are parsed once per (path, mtime, size).
        self._history_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

    def paths_roots(self) -> tuple[str, ...]:
        """Widest first: the workspace, then the data dir, then the cwd."""
        roots = [str(self.workspace), str(self.root)]
        cwd = str(Path.cwd())
        if cwd not in roots:
            roots.append(cwd)
        return tuple(roots)

    def sanitise(self, value: Any) -> Any:
        """Strip workspace-absolute paths from anything that leaves the server."""
        return sanitise_paths(value, self.paths_roots())

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
            "source_names": settings.enabled_sources(),
            "provider_wait_seconds": settings.provider_max_automatic_wait_seconds,
            "paper_limit": max(2, min(MAX_LIVE_PAPER_LIMIT, settings.target_corpus_max)),
            "paper_limit_max": MAX_LIVE_PAPER_LIMIT,
            "llm_request_budget": settings.llm_daily_budget,
            "source_quorum": 2,
            "modes": ["live", "simulate", "replay"],
            # Bounds for the composer's inline validator. They mirror NewRun and
            # are exposed so the UI does not have to hardcode a second copy.
            "limits": {
                "topic_min": 3,
                "topic_max": 300,
                "question_min": 3,
                "question_max": 1000,
                "paper_limit_min": 2,
                "paper_limit_max": MAX_LIVE_PAPER_LIMIT,
                "provider_wait_seconds_min": 0,
                "provider_wait_seconds_max": 3600,
                "llm_request_budget_min": 1,
                "llm_request_budget_max": 1000,
                "concurrency_min": 1,
                "concurrency_max": 8,
                "source_limit_min": 2,
                "source_limit_max": 5,
                "delay_ms_min": 0,
                "delay_ms_max": 5000,
            },
            # A capability is a fact the server can check, not a promise about a
            # remote service. `ollama_planner` is true when the configured
            # structured-planner provider is Ollama (the webapp's own live gate).
            "capabilities": {
                "ollama_planner": models["planner"].split("/", 1)[0] == "ollama",
                "gemini": bool(settings.gemini_api_key),
                "gemini_opted_in": os.getenv("RLA_FODS_ALLOW_GEMINI") == "1",
                # Live research needs an Ollama planner and a usable answer
                # provider: either a Gemini key or a non-Gemini local model.
                "rla_live": models["planner"].split("/", 1)[0] == "ollama"
                and (
                    bool(settings.gemini_api_key)
                    or models["answer"].split("/", 1)[0] != "gemini"
                ),
            },
        }

    def _effective_budget(self, request: NewRun) -> int:
        """Resolve the run's model-call cap against the operator's setting.

        Omitting the field uses the configured cap verbatim. Raising it above
        that cap requires an explicit, per-run opt-in; otherwise the request is
        rejected with a field error the UI can render next to the input (A-06).
        """
        configured = self.settings.llm_daily_budget
        requested = request.llm_request_budget
        if requested is None:
            return configured
        if requested > configured and not request.allow_budget_override:
            raise BudgetOverrideRequired(requested, configured)
        return requested

    @staticmethod
    def _output_name(request: NewRun, run_id: str) -> str:
        name = request.output_name.strip()
        if not name:
            name = f"{run_id}.md"
        if not OUTPUT_NAME.fullmatch(name) or name in {".", ".."}:
            raise ValueError("output_name must be a simple Markdown filename")
        return name

    def start(self, request: NewRun, idempotency_key: str = "") -> tuple[RunHandle, bool]:
        if request.engine == "rla" and request.mode != "live":
            raise ValueError("the full literature pipeline requires live mode")
        if request.engine == "rla" and (request.reuse_context or request.fresh_sources):
            raise ValueError(
                "context reuse and source-cache controls are available in the FODS runtime"
            )
        unknown = set(request.fail_sources) - set(FIXTURE_PAPERS)
        if unknown:
            raise ValueError(f"unknown demo source(s): {', '.join(sorted(unknown))}")
        if request.fail_sources and request.mode != "simulate":
            raise ValueError("controlled source failures are available only in simulation mode")
        if request.fresh_sources and request.mode != "live":
            raise ValueError("source-cache bypass is available only in live research mode")
        if request.context_id and not request.reuse_context:
            raise ValueError("selecting a saved context requires reuse_context")
        if request.context_id and request.fresh_sources:
            raise ValueError("saved-context reuse cannot bypass source retrieval cache")
        if request.context_id:
            from fods.tools import read_context_snapshot

            read_context_snapshot(self.settings.data_dir, request.topic, request.context_id)
        if (
            request.engine == "fods"
            and request.mode == "simulate"
            and request.planner == "ollama"
        ):
            raise ValueError("deterministic simulation uses the fixture planner")
        if request.engine == "fods" and request.mode == "live" and not request.reuse_context:
            if request.planner == "fixture":
                raise ValueError("fixture planner cannot be used for live research")
            planner_model = self.settings.canonical_model(self.settings.model_for_structured)
            planner_provider = planner_model.split("/", 1)[0]
            if planner_provider != "ollama":
                raise ValueError(
                    "live research requires a configured Ollama structured planner; "
                    f"configured provider is {planner_provider}"
                )
            if request.planner == "auto":
                request = request.model_copy(update={"planner": "ollama"})
        if request.inject_cycle and request.reuse_context:
            raise ValueError("cycle demonstration requires a new simulated research plan")
        if request.invalid_citation and request.mode != "simulate":
            raise ValueError("invalid-citation demonstration is available only in simulation mode")
        request = request.model_copy(update={"llm_request_budget": self._effective_budget(request)})
        key = idempotency_key.strip()[:120]
        with self.lock:
            self._evict_finished()
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
            handle.engine = request.engine
            self.runs[run_id] = handle
            if key:
                self.idempotency[key] = run_id

        event_log = EventLog(event_path, handle.publish, roots=self.paths_roots())
        thread = threading.Thread(
            target=self._execute,
            args=(handle, request, event_log),
            name=f"fods-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return handle, False

    def _execute(self, handle: RunHandle, request: NewRun, event_log: EventLog) -> None:
        if request.engine == "rla":
            self._execute_research_pipeline(handle, request, event_log)
            return
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
                    context_id=request.context_id,
                    fail_sources=fail_sources,
                    inject_cycle=request.inject_cycle,
                    invalid_citation=request.invalid_citation,
                    simulated_delay=request.delay_ms / 1000,
                    event_file=handle.event_path,
                    source_limit=request.source_limit,
                    fresh_sources=request.fresh_sources,
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

    def _execute_research_pipeline(
        self, handle: RunHandle, request: NewRun, event_log: EventLog
    ) -> None:
        """Run the existing rla stages behind the same browser event stream."""
        from rla.llm.factory import build_client
        from rla.pipeline.answer import render_markdown
        from rla.pipeline.orchestrator import Pipeline, PipelineResult
        from rla.store.cache import Cache, CostTracker
        from rla.store.rate_limits import LiveCollectionInProgress, LiveCollectionLock

        settings = self.settings.model_copy(
            update={
                "target_corpus_min": request.paper_limit,
                "target_corpus_max": request.paper_limit,
                "provider_max_automatic_wait_seconds": request.provider_wait_seconds,
                "llm_daily_budget": request.llm_request_budget,
            }
        )
        settings.ensure_dirs()
        cache = Cache(settings.cache_db)
        tracker = CostTracker()
        pipeline_started = time.perf_counter()
        try:
            llm = build_client(settings, cache, tracker)
            result = PipelineResult()
            started_event = event_log.emit(
                "run_started",
                "Full literature pipeline started",
                run_id=handle.run_id,
                engine="rla",
                pipeline="rla-phases",
                pipeline_stages=_rla_stages(),
                mode="live",
                topic=request.topic,
                question=request.question,
                paper_limit=request.paper_limit,
                provider_wait_seconds=request.provider_wait_seconds,
                llm_request_budget=request.llm_request_budget,
            )
            with LiveCollectionLock(settings.data_dir):
                async def run_pipeline() -> None:
                    async for item in Pipeline(settings, llm, cache, tracker).run(
                        request.topic, request.question, result
                    ):
                        value = item.to_dict()
                        event_log.emit(
                            "research_progress",
                            item.message,
                            phase=value["phase"],
                            phase_kind=item.kind,
                            stage_payload=item.payload,
                            event_timestamp=item.timestamp,
                        )
                        if value["phase"] == "score" and result.corpus is not None:
                            papers = [
                                paper.model_dump(mode="json")
                                for paper in result.corpus.papers
                            ]
                            event_log.emit(
                                "research_papers",
                                f"{len(papers)} selected papers are ready",
                                papers=papers,
                            )

                asyncio.run(run_pipeline())

            answer_result = result.answer_result
            answer = getattr(answer_result, "answer", "") if answer_result else ""
            graph_ok = bool(result.graph_report)
            extracted = int(result.extraction.get("extracted", 0)) + int(
                result.extraction.get("reused", 0)
            )
            paper_count = len(result.corpus.papers) if result.corpus else 0
            complete = bool(answer and graph_ok and paper_count and extracted >= paper_count)
            if answer_result and result.corpus:
                from rla.pipeline.traverse import NodeType

                corpus_by_id = {
                    paper.id: paper.model_dump(mode="json")
                    for paper in result.corpus.papers
                }
                evidence = []
                for node in answer_result.subgraph.nodes if answer_result.subgraph else []:
                    if node.type == str(NodeType.PAPER) and node.node_id in corpus_by_id:
                        evidence.append(
                            {"citation": node.label, "paper": corpus_by_id[node.node_id]}
                        )
                event_log.emit(
                    "research_answer",
                    "Cited answer generated",
                    answer=answer,
                    question_type=str(answer_result.question_type),
                    citations=answer_result.citations_used(),
                    stripped_citations=answer_result.stripped_citations,
                    evidence=evidence,
                )
                if complete and handle.output_path:
                    output_path = (self.workspace / handle.output_path).resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(render_markdown(answer_result), encoding="utf-8")
                    event_log.emit(
                        "brief_saved",
                        "Cited research brief saved",
                        **_brief_saved_payload(
                            handle.output_path, answer_result.stripped_citations
                        ),
                    )

            source_failures = result.acquisition.get("failed_sources", {})
            termination_reason = (
                "completed_with_partial_sources" if complete and source_failures else
                "completed" if complete else "pipeline_incomplete"
            )
            status = (
                "partial" if complete and source_failures else "completed" if complete else "failed"
            )
            event_log.emit(
                "run_finished",
                "Research pipeline completed" if complete else "Research pipeline did not complete",
                run_id=handle.run_id,
                engine="rla",
                mode="live",
                succeeded=complete,
                termination_reason=termination_reason,
                elapsed_ms=round((time.perf_counter() - pipeline_started) * 1000, 1),
                failed_sources=sorted(source_failures) if isinstance(source_failures, dict) else [],
                stages=_stage_timings(event_log.events, started_event.timestamp),
                paper_count=paper_count,
                extracted_count=extracted,
                graph_built=graph_ok,
                answer_ready=bool(answer),
            )
            handle.finish(
                status,
                "" if complete else "one or more required pipeline stages did not complete",
            )
        except LiveCollectionInProgress as exc:
            event_log.emit(
                "run_finished",
                str(exc),
                run_id=handle.run_id,
                engine="rla",
                mode="live",
                succeeded=False,
                termination_reason="already_running",
                elapsed_ms=round((time.perf_counter() - pipeline_started) * 1000, 1),
            )
            handle.finish("failed", str(exc))
        except Exception as exc:
            event_log.emit(
                "run_failed",
                f"run failed: {type(exc).__name__}: {str(exc)[:240]}",
                run_id=handle.run_id,
                engine="rla",
                mode="live",
            )
            event_log.emit(
                "run_finished",
                "Research pipeline failed before completion",
                run_id=handle.run_id,
                engine="rla",
                mode="live",
                succeeded=False,
                termination_reason="failed",
                elapsed_ms=round((time.perf_counter() - pipeline_started) * 1000, 1),
            )

            handle.finish("failed", f"{type(exc).__name__}: {exc}")

    def get(self, run_id: str) -> RunHandle | None:
        with self.lock:
            return self.runs.get(run_id)

    def info(self, run_id: str) -> dict[str, Any] | None:
        """Run info for a live handle, or for a log left by an earlier process."""
        handle = self.get(run_id)
        if handle is not None:
            return _handle_info(handle)
        return self._info_from_disk(run_id)

    def _info_from_disk(self, run_id: str) -> dict[str, Any] | None:
        """A-02: after a restart the JSONL is still the authoritative record."""
        if not RUN_ID.fullmatch(run_id):
            return None
        path = self.runs_dir / f"{run_id}.jsonl"
        if not path.is_file() or not path.resolve().is_relative_to(self.runs_dir.resolve()):
            return None
        try:
            events, skipped = read_events(path, strict=False)
        except OSError:
            return None
        if not events:
            return None
        started = _first_event(events, "run_started") or {}
        finish = _last_event(events, "run_finished") or {}
        saved = _first_event(events, "brief_saved") or {}
        payload = started.get("payload", {})
        view = RunHandle(
            run_id,
            str(payload.get("mode") or "unknown"),
            str(payload.get("topic") or ""),
            str(saved.get("payload", {}).get("path") or ""),
        )
        view.engine = str(payload.get("engine") or "fods")
        view.status = _status_from_finish(finish) if finish else "interrupted"
        view.events = events
        info = self.sanitise(_handle_info(view))
        info["historical"] = True
        info["warnings"] = skipped
        return info

    def _evict_finished(self) -> None:
        """Keep the in-memory ring bounded; disk retains every run (A-02)."""
        with self.lock:
            finished = [run_id for run_id, handle in self.runs.items() if handle.finished]
            excess = len(finished) - MAX_FINISHED_HANDLES
            if excess <= 0:
                return
            for run_id in finished[:excess]:
                self.runs.pop(run_id, None)
            stale = {key for key, run_id in self.idempotency.items() if run_id not in self.runs}
            for key in stale:
                self.idempotency.pop(key, None)

    def history(self) -> list[dict[str, Any]]:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        paths = sorted(
            self.runs_dir.glob("[0-9a-f]" * 12 + ".jsonl"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        result: list[dict[str, Any]] = []
        with self.lock:
            seen = {str(path) for path in paths}
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                key = (stat.st_mtime_ns, stat.st_size)
                cached = self._history_cache.get(str(path))
                if cached is not None and cached[0] == key:
                    result.append(cached[1])
                    continue
                entry = self._history_entry(path)
                if entry is None:
                    continue
                self._history_cache[str(path)] = (key, entry)
                result.append(entry)
            for stale in set(self._history_cache) - seen:
                self._history_cache.pop(stale, None)
        return result[:100]

    def _history_entry(self, path: Path) -> dict[str, Any] | None:
        """One history row, tolerant of a corrupt line (A-02, A-09)."""
        try:
            events, skipped = read_events(path, strict=False)
        except OSError:
            return None
        if not events:
            return None
        started = _first_event(events, "run_started") or {}
        plan = _first_event(events, "plan_received") or {}
        finish = _last_event(events, "run_finished") or {}
        saved = _first_event(events, "brief_saved") or {}
        actual_models = [
            {
                "stage": event.get("payload", {}).get("stage"),
                "provider": event.get("payload", {}).get("provider"),
                "model": event.get("payload", {}).get("model"),
            }
            for event in events
            if event["kind"] == "model_call_completed"
        ]
        status = _status_from_finish(finish) if finish else "interrupted"
        return self.sanitise(
            {
                "run_id": path.stem,
                "engine": started.get("payload", {}).get("engine", "fods"),
                "mode": started.get("payload", {}).get(
                    "mode", plan.get("payload", {}).get("mode", "unknown")
                ),
                "topic": started.get("payload", {}).get(
                    "topic", plan.get("payload", {}).get("topic", "")
                ),
                "status": status,
                "output_path": saved.get("payload", {}).get("path", ""),
                "models_used": actual_models,
                "elapsed_ms": finish.get("payload", {}).get("elapsed_ms"),
                "started_at": started.get("timestamp"),
                "ended_at": finish.get("timestamp"),
                "event_count": len(events),
                "warnings": skipped,
                "visualization_url": f"/api/runs/{path.stem}/visualization",
            }
        )

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
            self._evict_finished()
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

    def run_events(self, run_id: str) -> tuple[list[dict[str, Any]], int]:
        """Events for a run, from memory or disk, plus any skipped corrupt lines."""
        handle = self.get(run_id)
        if handle is not None:
            return handle.events, 0
        if not RUN_ID.fullmatch(run_id):
            return [], 0
        path = self.runs_dir / f"{run_id}.jsonl"
        if not path.is_file() or not path.resolve().is_relative_to(self.runs_dir.resolve()):
            return [], 0
        return read_events(path, strict=False)

    def brief(self, run_id: str) -> str | None:
        events, skipped = self.run_events(run_id)
        saved = _first_event(events, "brief_saved")
        if not saved:
            if skipped:
                raise ValueError("the recorded log is corrupt; the brief cannot be resolved")
            return None
        stored = Path(str(saved.get("payload", {}).get("path", "")))
        target = (stored if stored.is_absolute() else self.workspace / stored).resolve()
        if not target.is_relative_to(self.briefs_dir.resolve()) or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def brief_document(self, run_id: str, markdown: str) -> dict[str, Any]:
        """Machine-readable brief: the Markdown plus the recorded citations and sources."""
        events, _skipped = self.run_events(run_id)
        answer = _last_event(events, "research_answer") or _last_event(events, "answer_ready") or {}
        payload = answer.get("payload", {})
        citations = payload.get("citations") or payload.get("evidence_citations") or []
        return {
            "run_id": run_id,
            "markdown": markdown,
            "citations": citations if isinstance(citations, list) else [],
            "sources": _sources_from(events),
        }


def _brief_saved_payload(
    output_path: str, stripped_citations: list[str] | None
) -> dict[str, Any]:
    """A-07: the validation flag follows the recorded check, never a constant."""
    stripped = list(stripped_citations or [])
    return {
        "path": output_path,
        "saved": True,
        "citations_validated": not stripped,
        "stripped_citations": stripped,
    }


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


def _rla_stages() -> list[dict[str, Any]]:
    """The labelled RLA phase rail (design §4.1, UI-07)."""
    return [
        {
            "id": str(phase),
            "label": PHASE_LABEL.get(str(phase), str(phase).title()),
            "order": index,
        }
        for index, phase in enumerate(PIPELINE_PHASES)
    ]


def _stage_timings(events: list[Any], start_ts: float) -> list[dict[str, Any]]:
    """Per-phase start offset and duration, from the recorded progress events.

    Nothing is estimated: a phase with no progress event is absent rather than
    shown as zero.
    """
    starts: dict[str, float] = {}
    ends: dict[str, float] = {}
    for item in events:
        if getattr(item, "kind", "") != "research_progress":
            continue
        phase = str(item.payload.get("phase") or "")
        if not phase:
            continue
        starts.setdefault(phase, item.timestamp)
        ends[phase] = item.timestamp
    return [
        {
            "id": phase,
            "started_ms": round((starts[phase] - start_ts) * 1000, 1),
            "duration_ms": round((ends[phase] - starts[phase]) * 1000, 1),
        }
        for phase in sorted(starts, key=lambda name: starts[name])
    ]


def _first_event(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("kind") == kind), None)


def _last_event(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event.get("kind") == kind), None)


def _sources_from(events: list[dict[str, Any]]) -> list[str]:
    """Source names the run actually used, from the recorded context or papers."""
    names: set[str] = set()
    for event in events:
        payload = event.get("payload", {})
        if event.get("kind") == "context_ready":
            names.update(str(name) for name in payload.get("source_names") or [] if name)
        if event.get("kind") == "research_papers":
            for paper in payload.get("papers") or []:
                if not isinstance(paper, dict):
                    continue
                for name in paper.get("sources") or []:
                    if name:
                        names.add(str(name))
                if paper.get("source"):
                    names.add(str(paper["source"]))
    return sorted(names)


def _host_allowed(host_header: str) -> bool:
    """A-11: with no Host check, a rebound hostname could reach this API."""
    host = host_header.strip()
    if not host:
        return True
    if host.startswith("["):
        name = host.split("]", 1)[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name.lower() in {"127.0.0.1", "localhost", "::1", "[::1]"}


def _origin_allowed(origin: str, port: int) -> bool:
    """Allow this server's own origin and an explicitly configured dev origin."""
    if not origin:
        # Non-browser clients (tests, curl) send no Origin; Host is still checked.
        return True
    extra = os.getenv("RLA_FODS_DEV_ORIGIN", "").strip().rstrip("/")
    if extra and origin.strip().rstrip("/") == extra:
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return False
    return parsed.port in {port, None}


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

        def _json(self, status: int, value: Any, *, raw: bool = False) -> None:
            # A-11: no absolute path leaves the server. A-08: a generated brief
            # skips credential redaction (`safe_value` would mangle Markdown)
            # but still goes through path sanitising.
            payload = manager.sanitise(value if raw else safe_value(value))
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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

        def _origin_guard(self) -> bool:
            """A-11: reject writes from a foreign Host or Origin.

            Cross-origin *reads* are already blocked by the missing CORS
            headers, but a plain form post from another page can still trigger
            a local run. Returns True when the request may proceed; otherwise
            the rejection has already been written.
            """

            def reject(code: str, message: str) -> bool:
                # Drain the body first: closing a keep-alive socket with unread
                # bytes makes Windows reset the connection and the client never
                # sees the 403.
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if 0 < length <= 65536:
                    self.rfile.read(length)
                self._json(403, {"error": message, "code": code})
                return False

            port = int(self.server.server_address[1])
            if not _host_allowed(self.headers.get("Host", "")):
                return reject("forbidden_host", "unexpected Host header")
            if not _origin_allowed(self.headers.get("Origin", ""), port):
                return reject("forbidden_origin", "cross-origin request refused")
            return True

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                built_entry = WEB_ROOT / "dist" / "index.html"
                if built_entry.is_file():
                    return self._static("dist/index.html", "text/html; charset=utf-8")
                return self._static("index.html", "text/html; charset=utf-8")
            asset_match = re.fullmatch(r"/assets/([A-Za-z0-9._-]+\.(?:js|css|svg|woff2?))", path)
            if asset_match:
                filename = asset_match.group(1)
                content_type = {
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".woff": "font/woff",
                    ".woff2": "font/woff2",
                }[Path(filename).suffix]
                return self._static(f"dist/assets/{filename}", content_type)
            if path == "/app.js":
                return self._static("app.js", "text/javascript; charset=utf-8")
            if path == "/styles.css":
                return self._static("styles.css", "text/css; charset=utf-8")
            if path == "/shell.js":
                return self._static("shell.js", "text/javascript; charset=utf-8")
            if path == "/shell-core.js":
                return self._static("shell-core.js", "text/javascript; charset=utf-8")
            if path == "/vendor/d3-path-3.1.0.min.js":
                return self._static("vendor/d3-path-3.1.0.min.js", "text/javascript; charset=utf-8")
            if path == "/vendor/d3-shape-3.2.0.min.js":
                return self._static(
                    "vendor/d3-shape-3.2.0.min.js", "text/javascript; charset=utf-8"
                )
            if path == "/vendor/D3_PATH_LICENSE.txt":
                return self._static("vendor/D3_PATH_LICENSE.txt", "text/plain; charset=utf-8")
            if path == "/vendor/D3_SHAPE_LICENSE.txt":
                return self._static("vendor/D3_SHAPE_LICENSE.txt", "text/plain; charset=utf-8")
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
                info = manager.info(match.group(1))
                if info is None:
                    return self._json(404, {"error": "run not found", "code": "run_not_found"})
                return self._json(200, info)
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})/events", path)
            if match:
                return self._events(manager, match.group(1), parse_qs(parsed.query))
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})/brief", path)
            if match:
                query = parse_qs(parsed.query)
                run_id = match.group(1)
                try:
                    brief = manager.brief(run_id)
                except (OSError, ValueError) as exc:
                    return self._json(
                        500,
                        {
                            "error": f"the saved brief could not be read: {exc}",
                            "code": "brief_unreadable",
                        },
                    )
                if brief is None:
                    return self._json(
                        404, {"error": "no saved brief for this run", "code": "brief_not_found"}
                    )
                encoded = brief.encode("utf-8")
                if len(encoded) > MAX_BRIEF_BYTES:
                    return self._json(
                        413,
                        {
                            "error": "the saved brief is larger than the 2 MiB limit",
                            "code": "brief_too_large",
                        },
                    )
                if query.get("format", [""])[0] == "json":
                    return self._json(
                        200, manager.brief_document(run_id, brief), raw=True
                    )
                self.send_response(200)
                self._headers("text/markdown; charset=utf-8", len(encoded))
                if query.get("download", ["0"])[0] in {"1", "true", "yes"}:
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{run_id}.md"'
                    )
                self.end_headers()
                return self.wfile.write(encoded)
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
                return self._json(
                    404, {"error": "run visualization not found", "code": "not_found"}
                )
            return self._json(404, {"error": "not found", "code": "not_found"})

        def _static(self, name: str, content_type: str) -> None:
            path = WEB_ROOT / name
            if not path.is_file():
                return self._json(404, {"error": "frontend asset missing", "code": "not_found"})
            body = path.read_bytes()
            self.send_response(200)
            self._headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

        def _events(
            self, run_manager: RunManager, run_id: str, query: dict[str, list[str]]
        ) -> None:
            handle = run_manager.get(run_id)
            try:
                after = int(self.headers.get("Last-Event-ID", query.get("after", ["0"])[0]))
            except ValueError:
                after = 0
            if handle is None:
                return self._events_from_disk(run_manager, run_id, after)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(f"retry: {STREAM_RETRY_MS}\n\n".encode())
            self.wfile.flush()
            index = 0
            status_reason = ""
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
                        status = handle.status
                    for event in pending:
                        index += 1
                        event_id = int(event.get("seq", index))
                        if event_id <= after:
                            continue
                        if event.get("kind") == "run_finished":
                            status_reason = str(
                                event.get("payload", {}).get("termination_reason") or ""
                            )
                            # The handle's own status is updated just after the
                            # event is published, so the terminal envelope must
                            # carry the recorded outcome rather than a stale
                            # "starting".
                            status = (
                                "replayed"
                                if handle.run_kind == "replay"
                                else _status_from_finish(event)
                            )
                        envelope = {
                            "run_kind": handle.run_kind,
                            "source_run_id": handle.source_run_id or None,
                            "status": status,
                            "status_reason": status_reason,
                            "historical": False,
                            "warnings": 0,
                            "event": event,
                        }
                        data = json.dumps(
                            run_manager.sanitise(envelope),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode())
                        self.wfile.flush()
                        after = event_id
                    if finished and index >= len(handle.events):
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                return

        def _events_from_disk(self, run_manager: RunManager, run_id: str, after: int) -> None:
            """A-02: a run from an earlier process is still streamable.

            The log is authoritative; the stream is explicitly marked
            `historical` so the browser cannot present it as a live run.
            """
            events, skipped = run_manager.run_events(run_id)
            if not events and skipped:
                return self._json(
                    500,
                    {
                        "error": "the recorded log has no readable events",
                        "code": "log_unreadable",
                    },
                )
            if not events:
                return self._json(404, {"error": "run not found", "code": "run_not_found"})
            started = _first_event(events, "run_started") or {}
            finish = _last_event(events, "run_finished") or {}
            started_payload = started.get("payload", {})
            status = _status_from_finish(finish) if finish else "interrupted"
            status_reason = str(finish.get("payload", {}).get("termination_reason") or "")
            run_kind = str(started_payload.get("mode") or "unknown")
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            # A historical replay is finite: close so the client sees EOF.
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                self.wfile.write(f"retry: {STREAM_RETRY_MS}\n\n".encode())
                for event in events:
                    event_id = int(event.get("seq", 0))
                    if event_id <= after:
                        continue
                    envelope = {
                        "run_kind": run_kind,
                        "source_run_id": None,
                        "status": status,
                        "status_reason": status_reason,
                        "historical": True,
                        "warnings": skipped,
                        "event": event,
                    }
                    data = json.dumps(
                        run_manager.sanitise(envelope),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                return

        def do_POST(self) -> None:  # noqa: N802
            if not self._origin_guard():
                return
            try:
                value = self._body()
                if self.path == "/api/runs":
                    request = NewRun.model_validate(value)
                    if request.reuse_context and request.planner == "ollama":
                        return self._json(
                            400,
                            {
                                "error": "saved-context runs use the deterministic planner",
                                "code": "invalid_request",
                            },
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
                return self._json(404, {"error": "not found", "code": "not_found"})
            except BudgetOverrideRequired as exc:
                return self._json(
                    400,
                    {"error": str(exc), "code": exc.code, "fields": exc.fields},
                )
            except ValidationError as exc:
                return self._json(
                    400,
                    {
                        "error": "invalid run request",
                        "code": "validation",
                        "fields": exc.errors(include_url=False),
                    },
                )
            except FileExistsError as exc:
                return self._json(409, {"error": str(exc), "code": "conflict"})
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc), "code": "invalid_request"})
            except FileNotFoundError as exc:
                return self._json(404, {"error": str(exc), "code": "not_found"})

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._origin_guard():
                return
            match = re.fullmatch(r"/api/runs/([0-9a-f]{12})", urlparse(self.path).path)
            if not match:
                return self._json(404, {"error": "not found", "code": "not_found"})
            handle = manager.get(match.group(1))
            if handle is None:
                return self._json(
                    404, {"error": "run not found", "code": "run_not_found"}
                )
            if handle.finished:
                return self._json(
                    409, {"error": "run is already finished", "code": "run_finished"}
                )
            handle.cancel_event.set()
            return self._json(
                202,
                {
                    "run_id": handle.run_id,
                    "status": "cancellation_requested",
                    "code": "cancellation_requested",
                },
            )

    return ThreadingHTTPServer((host, port), Handler), manager


def _handle_info(handle: RunHandle) -> dict[str, Any]:
    events = handle.events
    started = _first_event(events, "run_started") or {}
    finish = _last_event(events, "run_finished") or {}
    start_payload = started.get("payload", {})
    finish_payload = finish.get("payload", {})
    started_at = started.get("timestamp")
    ended_at = finish.get("timestamp")
    elapsed_ms = finish_payload.get("elapsed_ms")
    if elapsed_ms is None and started_at and ended_at:
        elapsed_ms = round((float(ended_at) - float(started_at)) * 1000, 1)
    pipeline = str(start_payload.get("pipeline") or "") or (
        "rla-phases" if handle.engine == "rla" else "fods-scheduler"
    )
    unavailable = (
        finish_payload.get("unavailable_sources")
        or finish_payload.get("failed_sources")
        or []
    )
    return {
        "run_id": handle.run_id,
        "engine": handle.engine,
        "run_kind": handle.run_kind,
        "source_run_id": handle.source_run_id or None,
        "topic": handle.topic,
        "status": handle.status,
        "status_reason": str(finish_payload.get("termination_reason") or ""),
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_ms": elapsed_ms,
        "pipeline": pipeline,
        "unavailable_sources": [str(item) for item in unavailable]
        if isinstance(unavailable, list)
        else [],
        "event_count": len(handle.events),
        "error": handle.error,
        "output_path": handle.output_path,
        "events_url": f"/api/runs/{handle.run_id}/events",
    }
