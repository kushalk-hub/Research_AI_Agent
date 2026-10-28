"""CLI for the FODS-visible research brief workflow."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from threading import Event
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from fods.events import EventLog, RuntimeEvent, read_events
from fods.fixtures import FIXTURE_PAPERS
from fods.models import TaskPlan
from fods.plan import PlanError
from fods.planner import LLMPlanner, canonicalize_llm_research_plan, deterministic_plan
from fods.runtime import run_plan
from fods.sources import build_live_source_pool
from fods.tools import ToolContext, create_registry
from fods.visualize import write_run_html
from rla.config import Settings, get_settings
from rla.llm.factory import build_client
from rla.store.cache import Cache, CostTracker

app = typer.Typer(add_completion=False, no_args_is_help=True, help="FODS research-agent runtime.")
console = Console()


def _show_plan(plan: TaskPlan) -> None:
    tree = Tree("[bold]Proposed task plan (runtime validation follows)[/]")
    for task in plan.tasks:
        deps = ", ".join(task.depends_on) or "none"
        tree.add(
            f"[cyan]{task.id}[/] -> [yellow]{task.tool}[/]  depends on: {deps}  "
            f"priority={task.priority}"
        )
    console.print(tree)


def _print_event(event: RuntimeEvent) -> None:
    style = {
        "task_failed": "red",
        "task_blocked": "red",
        "plan_rejected": "bold red",
        "recovery_decision": "yellow",
        "task_completed": "green",
        "run_finished": "bold green" if event.payload.get("succeeded") else "bold red",
    }.get(event.kind, "cyan")
    timing = event.payload.get("duration_ms", event.payload.get("elapsed_ms"))
    suffix = f" ({timing} ms)" if timing is not None else ""
    console.print(f"[{event.seq:03}] [{style}]{event.kind:<20}[/] {event.message}{suffix}")


def _canonical_provider(settings: Settings, model: str) -> str:
    return settings.canonical_model(model).split("/", 1)[0]


async def _empty_search(_query: str, _limit: int):
    return []


async def _execute(
    *,
    topic: str,
    question: str,
    output: str,
    request: str,
    mode: str,
    planner_mode: str,
    schedule: str,
    concurrency: int,
    reuse_context: bool,
    fail_sources: set[str] | None = None,
    inject_cycle: bool = False,
    invalid_citation: bool = False,
    simulated_delay: float = 0.15,
    event_file: Path | None = None,
    fresh_sources: bool = False,
    source_limit: int = 3,
    run_id: str | None = None,
    event_log: EventLog | None = None,
    event_sink=None,
    print_cli: bool = True,
    cancel_event: Event | None = None,
    settings: Settings | None = None,
    workspace: Path | None = None,
) -> bool:
    command_started = time.perf_counter()
    settings = settings or get_settings()
    settings.ensure_dirs()
    run_workspace = (workspace or Path.cwd()).resolve()
    run_id = run_id or uuid.uuid4().hex[:12]
    run_data = settings.data_dir / "fods"
    output_event_file = event_file or run_data / "runs" / f"{run_id}.jsonl"
    log = event_log or EventLog(
        output_event_file,
        event_sink or (_print_event if print_cli else None),
    )
    log.emit(
        "run_started",
        "FODS research run started",
        run_id=run_id,
        mode=mode,
        planner=planner_mode,
        schedule=schedule,
        concurrency=concurrency,
        source_limit=source_limit,
        reuse_context=reuse_context,
        topic=topic,
        question=question,
        configured_models={
            "planner": settings.model_for_structured,
            "answer": settings.model_for_answer,
            "embedding": settings.embedding_model,
        },
        gemini_key_configured=bool(settings.gemini_api_key),
    )
    cache = Cache(settings.cache_db)
    tracker = CostTracker()
    llm = build_client(settings, cache, tracker)
    pool = None
    separate_source_cache = None

    try:
        if reuse_context:
            source_searchers = {}
        elif mode == "simulate":
            source_searchers = {name: _empty_search for name in FIXTURE_PAPERS}
        elif mode == "live":
            if fresh_sources:
                separate_source_cache = Cache(
                    settings.data_dir / "fods" / "source_cache" / f"{run_id}.db"
                )
            source_cache = separate_source_cache or cache
            pool = build_live_source_pool(settings, source_cache, limit=source_limit)
            source_searchers = pool.searchers
        else:
            raise ValueError("mode must be 'live' or 'simulate'")

        source_names = list(source_searchers)
        selected_planner = planner_mode
        planner_model = settings.model_for_structured
        ollama_ready = llm is not None and _canonical_provider(settings, planner_model) == "ollama"
        if selected_planner == "auto":
            selected_planner = (
                "ollama" if mode == "live" and ollama_ready and not reuse_context else "fixture"
            )
        planner_repairs: list[str] = []
        proposed_tasks = None
        if selected_planner == "ollama":
            if not ollama_ready:
                raise RuntimeError(
                    "Ollama planning requested, but RLA_STRUCTURED_MODEL is not a usable "
                    "ollama/ model"
                )
            if reuse_context:
                raise ValueError(
                    "context-reuse runs use the deterministic plan so no planning call is needed"
                )
            plan = await LLMPlanner(llm, model=planner_model, event_log=log, run_id=run_id).propose(
                request, topic, question, output, source_names
            )
            proposed_tasks = [task.model_dump(mode="json") for task in plan.tasks]
            plan, planner_repairs = canonicalize_llm_research_plan(plan, source_names)
        elif selected_planner == "fixture":
            plan = deterministic_plan(
                request, topic, question, output, source_names, reuse_context=reuse_context
            )
        else:
            raise ValueError("planner must be auto, ollama, or fixture")

        if source_limit:
            plan = plan.model_copy(
                update={
                    "tasks": [
                        task.model_copy(update={"args": {**task.args, "limit": source_limit}})
                        if task.tool.startswith("search_")
                        else task
                        for task in plan.tasks
                    ]
                }
            )

        if inject_cycle:
            source_tasks = [task for task in plan.tasks if task.tool.startswith("search_")]
            if len(source_tasks) < 2:
                raise ValueError("cycle injection needs at least two source tasks")
            source_tasks[0].depends_on = [source_tasks[1].id]
            source_tasks[1].depends_on = [source_tasks[0].id]

        answer_model = settings.model_for_answer
        # Simulation stays deterministic even on a machine with a configured
        # provider. Live mode uses local Ollama by default.
        answer_llm = llm if mode == "live" else None
        if answer_llm is not None and _canonical_provider(settings, answer_model) == "gemini":
            # Do not spend the limited cloud quota unless the caller opts in.
            if os.getenv("RLA_FODS_ALLOW_GEMINI") != "1":
                answer_llm = None

        registry = create_registry(source_searchers)
        ctx = ToolContext(
            run_id=run_id,
            mode=mode,
            topic=topic,
            question=question,
            output_path=output,
            workspace=run_workspace,
            data_dir=settings.data_dir,
            llm=answer_llm,
            event_log=log,
            metadata={
                "planner": selected_planner,
                "proposed_tasks": proposed_tasks,
                "planner_repairs": planner_repairs,
                "source_cache_mode": (
                    "fresh" if fresh_sources and mode == "live" else "configured"
                ),
                "fixtures": FIXTURE_PAPERS,
                "fail_sources": fail_sources or set(),
                "simulated_delay": lambda _name: asyncio.sleep(simulated_delay),
                "answer_model": answer_model,
                "force_invalid_citation": invalid_citation,
                "pre_execution_ms": round((time.perf_counter() - command_started) * 1000, 1),
            },
        )
        if print_cli:
            _show_plan(plan)
            console.print(
                f"mode=[bold]{mode}[/] planner=[bold]{selected_planner}[/] "
                f"schedule=[bold]{schedule}[/] workers={concurrency} "
                f"source_cache={'fresh' if fresh_sources and mode == 'live' else 'configured'} "
                f"event_log={output_event_file}"
            )
        try:
            result = await run_plan(
                plan,
                registry,
                ctx,
                schedule=schedule,
                concurrency=concurrency,
                max_attempts=2,
                event_log=log,
                cancel_event=cancel_event,
            )
        except PlanError:
            if output_event_file.exists():
                visual_file = output_event_file.with_suffix(".html")
                write_run_html(read_events(output_event_file), visual_file)
                console.print(f"Run visualization: {visual_file}")
            if print_cli:
                console.print("[bold red]Plan rejected before any tool execution.[/]")
            return False
        visual_file = output_event_file.with_suffix(".html")
        write_run_html(result.events, visual_file)
        if print_cli:
            console.print(f"Run visualization: {visual_file}")
            console.print(
                f"Context reuse/build and answer result: succeeded={result.succeeded}; "
                f"termination={result.termination_reason}"
            )
        answer_record = next(
            (
                record
                for record in result.states.values()
                if record.task.tool == "draft_cited_answer"
            ),
            None,
        )
        if print_cli and answer_record is not None and isinstance(answer_record.result, dict):
            console.print(Panel(answer_record.result["answer"], title="Cited answer"))
        write_record = next(
            (
                record
                for record in result.states.values()
                if record.task.tool == "write_cited_brief"
            ),
            None,
        )
        if print_cli and write_record is not None and isinstance(write_record.result, dict):
            console.print(f"Saved validated brief: {write_record.result['path']}")
        return result.succeeded
    finally:
        if pool is not None:
            await pool.close()
        if separate_source_cache is not None:
            separate_source_cache.close()
        cache.close()


@app.command("run")
def run_command(
    topic: Annotated[str, typer.Option(help="Research topic to gather papers for.")],
    question: Annotated[str, typer.Option(help="Question to answer from the saved context.")],
    output: Annotated[
        str, typer.Option("--output", help="Explicit workspace-relative brief path.")
    ],
    request: Annotated[
        str, typer.Option(help="Natural-language request sent to the planner.")
    ] = "",
    mode: Annotated[str, typer.Option(help="Tool execution: live or simulated.")] = "simulate",
    planner: Annotated[
        str, typer.Option(help="Plan source: auto, Ollama, or deterministic fixture.")
    ] = "auto",
    schedule: Annotated[str, typer.Option(help="Ready-task policy: fifo or priority.")] = "fifo",
    concurrency: Annotated[int, typer.Option(min=1, max=8)] = 3,
    reuse_context: Annotated[bool, typer.Option("--reuse-context")] = False,
    fail_source: Annotated[list[str] | None, typer.Option("--fail-source")] = None,
    inject_cycle: Annotated[bool, typer.Option("--inject-cycle")] = False,
    invalid_citation: Annotated[bool, typer.Option("--invalid-citation")] = False,
    delay_ms: Annotated[int, typer.Option(min=0, max=5000)] = 150,
    event_log: Annotated[Path | None, typer.Option("--event-log")] = None,
    fresh_sources: Annotated[
        bool,
        typer.Option("--fresh-sources", help="Use a new source cache to prove live API calls."),
    ] = False,
    source_limit: Annotated[int, typer.Option(min=2, max=5)] = 3,
) -> None:
    """Gather, reuse, answer, cite-check, and save a research brief."""
    if schedule not in {"fifo", "priority"}:
        raise typer.BadParameter("schedule must be fifo or priority")
    request_text = request or f"Research {topic} and answer: {question}"
    succeeded = asyncio.run(
        _execute(
            topic=topic,
            question=question,
            output=output,
            request=request_text,
            mode=mode,
            planner_mode=planner,
            schedule=schedule,
            concurrency=concurrency,
            reuse_context=reuse_context,
            fail_sources=set(fail_source or []),
            inject_cycle=inject_cycle,
            invalid_citation=invalid_citation,
            simulated_delay=delay_ms / 1000,
            event_file=event_log,
            fresh_sources=fresh_sources,
            source_limit=source_limit,
        )
    )
    if not succeeded:
        raise typer.Exit(code=1)


@app.command("replay")
def replay_command(event_log: Path) -> None:
    """Render a recorded event log; replay does not execute tools."""
    events = read_events(event_log)
    visual_file = event_log.with_suffix(".html")
    write_run_html(events, visual_file)
    console.print(f"[bold yellow]REPLAY ONLY[/] {event_log}")
    console.print(f"Run visualization: {visual_file}")
    for item in events:
        event = RuntimeEvent(
            seq=int(item["seq"]),
            kind=str(item["kind"]),
            message=str(item["message"]),
            payload=dict(item.get("payload", {})),
            timestamp=float(item.get("timestamp", 0)),
        )
        _print_event(event)


@app.command("serve")
def serve_command(
    host: Annotated[
        str, typer.Option(help="Bind address; defaults to localhost only.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    """Serve the interactive FODS runtime visualizer on this computer."""
    from fods.webapp import make_server

    server, _manager = make_server(host, port)
    console.print(f"FODS Runtime Visualizer: [bold]http://{host}:{port}/[/]")
    console.print("Press Ctrl+C to stop the local server.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        console.print("Stopping FODS visualizer…")
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
