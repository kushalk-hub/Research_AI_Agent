"""CLI for the FODS-visible research brief workflow."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from functools import wraps
from pathlib import Path
from threading import Event
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.tree import Tree

from fods.events import EventLog, RuntimeEvent, read_events
from fods.fixtures import FIXTURE_PAPERS
from fods.models import Task, TaskPlan
from fods.plan import PlanError
from fods.planner import LLMPlanner, canonicalize_llm_research_plan, deterministic_plan
from fods.research import ResearchProfile, build_query_plan, profile_for
from fods.runtime import run_plan
from fods.sources import build_live_source_pool, selected_live_source_names
from fods.tools import ToolContext, create_registry
from fods.visualize import write_run_html
from rla.config import Settings, get_settings
from rla.llm.factory import build_client
from rla.models import content_hash
from rla.store.cache import Cache, CostTracker
from rla.store.rate_limits import (
    LiveCollectionInProgress,
    LiveCollectionLock,
    RequestAttemptBudget,
    provider_lock_directory,
    provider_policy,
)

# Graph command group
graph_app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Knowledge graph operations."
)

app = typer.Typer(add_completion=False, no_args_is_help=True, help="FODS research-agent runtime.")
app.add_typer(graph_app, name="graph")
console = Console()
FODS_TASK_MAX_ATTEMPTS = 2


def _serialize_graph_mutation(command):
    """Serialize build/update operations across processes per topic on Windows too."""

    @wraps(command)
    def wrapped(*args, **kwargs):
        from fods.knowledge_graph import topic_lock

        topic = kwargs.get("topic") or (args[0] if args else "")
        settings = get_settings()
        lock_path = (
            settings.data_dir
            / "fods"
            / "knowledge_graph"
            / content_hash(topic)[:16]
            / ".mutation.lock"
        )
        with topic_lock(lock_path):
            return command(*args, **kwargs)

    return wrapped


@app.command("preflight")
def preflight_command(
    profile: Annotated[
        str, typer.Option(help="Research profile to inspect: quick or deep.")
    ] = "quick",
    pair: Annotated[
        bool, typer.Option(help="Report the combined Q01 Quick/Deep upper bound.")
    ] = False,
) -> None:
    """Report sources, provider pacing, and hard request ceilings without network calls."""
    if profile not in {"quick", "deep"}:
        raise typer.BadParameter("profile must be quick or deep")
    settings = get_settings()
    choices = ["quick", "deep"] if pair else [profile]
    selected = {}
    total_tasks = 0
    total_attempts = 0
    console.print("[bold]OFFLINE PROVIDER PREFLIGHT[/] — no network requests will be sent")
    console.print(
        f"Workspace provider-lock directory: {provider_lock_directory(settings.data_dir)}"
    )
    console.print(f"HTTP attempts per source request: {settings.max_retries}")
    console.print(f"FODS task attempts per source task: {FODS_TASK_MAX_ATTEMPTS}")
    for name in choices:
        policy = profile_for(name)
        sources = selected_live_source_names(settings, policy.source_limit)
        tasks = len(sources) * policy.query_count
        attempts = tasks * FODS_TASK_MAX_ATTEMPTS * max(0, settings.max_retries)
        selected[name] = sources
        total_tasks += tasks
        total_attempts += attempts
        console.print(
            f"{name}: sources={sources}; planned_source_query_tasks={tasks}; "
            f"hard_http_attempt_budget={attempts}; scheduler_concurrency=3"
        )
        for source in sources:
            rule = provider_policy(source)
            console.print(
                f"  {source}: min_start_interval={rule.min_interval:g}s; "
                f"max_in_flight={rule.max_in_flight or 'not provider-limited'}; "
                f"header_policy={rule.header_policy}; cross_process_lock=enabled"
            )
    console.print(
        f"total_planned_source_query_tasks={total_tasks}; "
        f"total_hard_http_attempt_budget={total_attempts}"
    )
    console.print(
        f"Gemini_opt_in={'enabled' if os.getenv('RLA_FODS_ALLOW_GEMINI') == '1' else 'disabled'}; "
        "fixture_planner_model_calls=0; answer_model_calls=0 when Gemini opt-in is disabled"
    )


def _aux_output_id(data_dir: Path, topic: str, context_id: str) -> str:
    from fods.tools import read_context_snapshot

    context = read_context_snapshot(data_dir, topic, context_id)
    return str(context["context_hash"])


async def _run_auxiliary_plan(
    *,
    plan: TaskPlan,
    settings: Settings,
    context_id: str,
    model: str = "",
    reference_resolvers=None,
    live_reference_sources: bool = False,
    source_limit: int = 2,
    reference_timeout_seconds: int = 60,
    workflow_budget_seconds: int = 600,
    concurrency: int = 4,
) -> bool:
    settings.ensure_dirs()
    log_path = settings.data_dir / "fods" / "runs" / f"{uuid.uuid4().hex[:12]}.jsonl"
    run_id = log_path.stem
    cache_path = (
        settings.data_dir / "fods" / "source_cache" / f"{run_id}.db"
        if live_reference_sources
        else settings.cache_db
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Cache(cache_path)
    llm = None
    pool = None
    log = EventLog(log_path, _print_event)
    try:
        if model:
            local_settings = settings.model_copy(
                update={
                    "structured_model": model,
                    "fallback_models": "",
                    "fallback_on_quota": False,
                }
            )
            llm = build_client(local_settings, cache, CostTracker())
        if live_reference_sources:
            pool = build_live_source_pool(settings, cache, limit=source_limit)
            reference_resolvers = pool.reference_resolvers
        registry = create_registry({}, reference_resolvers=reference_resolvers or {})
        ctx = ToolContext(
            run_id=run_id,
            mode="live",
            topic=plan.topic,
            question=plan.question,
            output_path=plan.output_path,
            workspace=Path.cwd().resolve(),
            data_dir=settings.data_dir,
            llm=llm,
            event_log=log,
            metadata={
                "context_id": context_id,
                "enrichment_model": model,
                "enrichment_prompt_version": "fods-enrichment-prompt-v4",
                "reference_timeout_seconds": reference_timeout_seconds,
                "source_cache_mode": "fresh" if live_reference_sources else "configured",
            },
        )
        result = await run_plan(
            plan,
            registry,
            ctx,
            schedule="priority",
            concurrency=concurrency,
            max_attempts=2,
            event_log=log,
            workflow_budget_seconds=workflow_budget_seconds,
        )
        console.print(f"Run log: {log_path}")
        console.print(
            f"Workflow succeeded={result.succeeded}; termination={result.termination_reason}"
        )
        for record in result.states.values():
            if record.result and isinstance(record.result, dict) and record.result.get("path"):
                console.print(f"Saved artifact: {record.result['path']}")
        return result.succeeded
    finally:
        if pool is not None:
            await pool.close()
        cache.close()


@app.command("enrich")
def enrich_command(
    topic: Annotated[str, typer.Option()],
    model: Annotated[
        str, typer.Option(help="Local Ollama model, for example ollama/qwen3:4b.")
    ] = "ollama/qwen3:4b",
    context_id: Annotated[str, typer.Option(help="Snapshot ID; omit to use the latest.")] = "",
    max_papers: Annotated[int, typer.Option(min=1, max=30)] = 15,
    batch_size: Annotated[int, typer.Option(min=1, max=5)] = 3,
    time_budget: Annotated[int, typer.Option(min=30, max=600)] = 600,
    workers: Annotated[int, typer.Option(min=1, max=8)] = 4,
) -> None:
    """Run bounded abstract extraction as resumable FODS tasks."""
    settings = get_settings()
    if _canonical_provider(settings, model) != "ollama":
        raise typer.BadParameter("enrichment is restricted to a local Ollama model")
    from fods.tools import read_context_snapshot

    context = read_context_snapshot(settings.data_dir, topic, context_id)
    context_id = str(context["context_hash"])
    papers = [p for p in context.get("papers", []) if str(p.get("abstract", "")).strip()][
        :max_papers
    ]
    if not papers:
        raise typer.BadParameter("the selected context has no papers with abstracts")
    batches = [papers[i : i + batch_size] for i in range(0, len(papers), batch_size)]
    if len(batches) + 2 > 30:
        raise typer.BadParameter("batch count exceeds the FODS plan limit")
    stem = f"data/fods/enrichments/{content_hash(context_id, model, str(batch_size))[:20]}.json"
    tasks = [Task(id="load_context", tool="load_saved_context")]
    batch_ids = []
    for index, group in enumerate(batches):
        task_id = f"extract_{index + 1:02d}"
        batch_ids.append(task_id)
        tasks.append(
            Task(
                id=task_id,
                tool="extract_enrichment_batch",
                args={"paper_ids": [str(p["id"]) for p in group]},
                depends_on=["load_context"],
                priority=50,
            )
        )
    tasks.append(
        Task(
            id="save_enrichment",
            tool="save_enrichment",
            args={"output_path": stem},
            depends_on=["load_context", *batch_ids],
            priority=10,
        )
    )
    plan = TaskPlan(
        request=f"Enrich context {context_id}",
        topic=topic,
        question="Extract supported concepts, methods, findings, and limitations",
        output_path=stem,
        workflow="enrichment",
        tasks=tasks,
    )
    succeeded = asyncio.run(
        _run_auxiliary_plan(
            plan=plan,
            settings=settings,
            context_id=context_id,
            model=model,
            workflow_budget_seconds=time_budget,
            concurrency=workers,
        )
    )
    if not succeeded:
        raise typer.Exit(code=1)


@app.command("discover-references")
def discover_references_command(
    topic: Annotated[str, typer.Option()],
    context_id: Annotated[str, typer.Option(help="Snapshot ID; omit to use the latest.")] = "",
    hops: Annotated[int, typer.Option(min=0, max=1)] = 1,
    seed_limit: Annotated[int, typer.Option(min=1, max=10)] = 5,
    source_limit: Annotated[int, typer.Option(min=1, max=2)] = 2,
    source: Annotated[
        str,
        typer.Option(help="Preferred resolver: semantic_scholar or openalex."),
    ] = "semantic_scholar",
    candidate_limit: Annotated[int, typer.Option(min=1, max=20)] = 10,
    time_budget: Annotated[int, typer.Option(min=10, max=300)] = 120,
    workers: Annotated[int, typer.Option(min=1, max=8)] = 4,
) -> None:
    """Resolve provider references for one bounded hop and save a derived snapshot."""
    settings = get_settings()
    context = __import__("fods.tools", fromlist=["read_context_snapshot"]).read_context_snapshot(
        settings.data_dir, topic, context_id
    )
    context_id = str(context["context_hash"])
    if source not in {"semantic_scholar", "openalex"}:
        raise typer.BadParameter("source must be semantic_scholar or openalex")
    topic_key = content_hash(topic)[:16]
    source_cap = min(source_limit, 2) if hops else 0
    provider_order = [
        source,
        *[name for name in ("semantic_scholar", "openalex") if name != source],
    ]
    source_names = provider_order[:source_cap] if hops else []
    native_namespace = "s2" if source == "semantic_scholar" else "openalex"
    seeds = (
        [
            paper
            for paper in context.get("papers", [])
            if (paper.get("external_ids") or {}).get(native_namespace)
        ][:seed_limit]
        if hops
        else []
    )
    if hops and not seeds:
        raise typer.BadParameter(
            f"the selected context has no papers with a {source} source-native ID"
        )
    discovery_key = content_hash(
        context_id,
        str(hops),
        str(seed_limit),
        str(source_limit),
        source,
        str(candidate_limit),
    )[:32]
    output = f"data/fods/topics/{topic_key}/{discovery_key}.json"
    tasks = [Task(id="load_context", tool="load_saved_context")]
    lookup_ids = []
    for i, paper in enumerate(seeds):
        for source in source_names:
            task_id = f"ref_{i + 1:02d}_{source}"
            lookup_ids.append(task_id)
            tasks.append(
                Task(
                    id=task_id,
                    tool="discover_references",
                    args={
                        "seed_paper_id": str(paper["id"]),
                        "resolver_source": source,
                        "max_candidates": candidate_limit,
                    },
                    depends_on=["load_context"],
                    priority=40,
                )
            )
    tasks.append(
        Task(
            id="save_reference_context",
            tool="save_reference_context",
            args={"output_path": output},
            depends_on=["load_context", *lookup_ids],
            priority=10,
        )
    )
    plan = TaskPlan(
        request=f"Discover references for context {context_id}",
        topic=topic,
        question="Resolve provider references with a one-hop cap",
        output_path=output,
        workflow="reference_discovery",
        tasks=tasks,
    )

    def execute_discovery():
        return asyncio.run(
            _run_auxiliary_plan(
                plan=plan,
                settings=settings,
                context_id=context_id,
                live_reference_sources=bool(hops),
                source_limit=max(2, source_limit),
                reference_timeout_seconds=time_budget,
                workflow_budget_seconds=time_budget,
                concurrency=workers,
            )
        )

    if hops:
        try:
            with LiveCollectionLock(settings.data_dir):
                succeeded = execute_discovery()
        except LiveCollectionInProgress as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        succeeded = execute_discovery()
    if not succeeded:
        raise typer.Exit(code=1)


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
    if event.kind == "source_http_attempt":
        suffix += (
            f" [{event.payload.get('provider')}:{event.payload.get('endpoint_class')} "
            f"attempt={event.payload.get('attempt')} wait="
            f"{event.payload.get('actual_wait', 0)}s]"
        )
    elif event.kind == "source_http_response":
        suffix += (
            f" [{event.payload.get('provider')} status={event.payload.get('status')} "
            f"retry={event.payload.get('retry_decision')}]"
        )
    elif event.kind in {"source_rate_limit_stopped", "source_http_budget_stopped"}:
        suffix += f" [{event.payload.get('provider')} stop={event.payload.get('reason')}]"
    console.print(f"[{event.seq:03}] [{style}]{event.kind:<20}[/] {event.message}{suffix}")


def _print_research_summary(result, query_plan, policy: ResearchProfile) -> None:
    context_record = next(
        (
            record
            for record in result.states.values()
            if record.task.tool in {"merge_and_save_context", "load_saved_context"}
            and isinstance(record.result, dict)
        ),
        None,
    )
    context = context_record.result if context_record else {}
    answer_record = next(
        (
            record
            for record in result.states.values()
            if record.task.tool == "draft_cited_answer" and isinstance(record.result, dict)
        ),
        None,
    )
    answer = answer_record.result if answer_record else {}
    answer_text = answer.get("answer", "")
    cited_ids = sorted(set(re.findall(r"\[(P\d+)\]", answer_text)))
    cited_papers = {
        item.get("citation")
        for item in answer.get("evidence", [])
        if item.get("paper", {}).get("id")
    } & set(cited_ids)
    source_errors = [
        {"task_id": event["payload"].get("task_id"), "error": event["message"]}
        for event in result.events
        if event["kind"] == "task_failed"
        and str(event["payload"].get("task_id", "")).startswith("search_")
    ]
    timings = {
        event["payload"].get("task_id", ""): event["payload"].get("duration_ms")
        for event in result.events
        if event["kind"] == "task_completed"
    }
    models = list(
        dict.fromkeys(
            event["payload"].get("model", "")
            for event in result.events
            if event["kind"] == "model_call_completed" and event["payload"].get("model")
        )
    )
    transport = next(
        (event["payload"] for event in result.events if event["kind"] == "run_finished"),
        {},
    )
    provider_telemetry: dict[str, dict[str, Any]] = {}
    for item in result.events:
        payload = item.get("payload", {})
        if item["kind"] not in {"source_http_attempt", "source_http_response"}:
            continue
        provider = str(payload.get("provider", "unknown"))
        entry = provider_telemetry.setdefault(
            provider,
            {
                "http_attempts": 0,
                "statuses": [],
                "waits_seconds": [],
                "rate_limit_headers": [],
            },
        )
        if item["kind"] == "source_http_attempt":
            entry["http_attempts"] += 1
            entry["waits_seconds"].append(payload.get("actual_wait", 0))
        else:
            if payload.get("status") is not None:
                entry["statuses"].append(payload["status"])
            if payload.get("rate_limit_headers"):
                entry["rate_limit_headers"].append(payload["rate_limit_headers"])
    summary = {
        "profile": policy.profile,
        "intent": query_plan.intent.value,
        "queries": query_plan.queries,
        "sources": context.get("source_yield", {}),
        "counts": {
            "raw_candidates": context.get("raw_candidate_count", 0),
            "unique_papers": context.get("unique_paper_count", context.get("paper_count", 0)),
            "retained_context_papers": context.get(
                "retained_paper_count", context.get("paper_count", 0)
            ),
            "evidence_selected_papers": len(answer.get("evidence", [])),
            "cited_papers": len(cited_papers),
        },
        "context_snapshot_id": context.get("context_hash", ""),
        "evidence_type": context.get("evidence_type", "abstract_and_metadata"),
        "source_errors": source_errors,
        "http_attempts": {
            "total": transport.get("http_attempts", 0),
            "by_provider": transport.get("http_attempts_by_provider", {}),
            "hard_budget": transport.get("http_attempt_budget"),
            "used": transport.get("http_attempt_budget_used"),
            "max_in_flight_observed": transport.get("provider_max_in_flight_observed", {}),
            "telemetry": provider_telemetry,
        },
        "cache_policy": context.get("source_yield", {}),
        "extraction": {"status": "not_requested", "extracted": 0},
        "actual_models": models,
        "task_timings_ms": timings,
        "citation_integrity": next(
            (
                event["payload"].get("valid")
                for event in result.events
                if event["kind"] == "citation_validation"
            ),
            None,
        ),
        "claim_support": "unverified",
        "stop_reason": result.termination_reason,
    }
    console.print(Panel(Pretty(summary), title="Research run summary"))


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
    source_limit: int | None = None,
    research_policy: ResearchProfile | None = None,
    context_mode: str = "build",
    context_id: str = "",
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
    policy = research_policy or profile_for(
        "quick", **({"source_limit": source_limit} if source_limit is not None else {})
    )
    effective_source_limit = source_limit or policy.source_limit
    if context_mode not in {"auto", "build", "reuse", "refresh"}:
        raise ValueError("context mode must be auto, build, reuse, or refresh")
    topic_key = content_hash(topic)[:16]
    context_root = settings.data_dir / "fods" / "topics"
    if context_mode == "auto":
        if fresh_sources:
            reuse_context = False
        else:
            reuse_context = reuse_context or bool(
                (context_root / f"{topic_key}.latest").exists()
                or (context_root / f"{topic_key}.json").exists()
            )
    elif context_mode == "reuse":
        reuse_context = True
    else:
        reuse_context = False
    if context_id:
        reuse_context = True
    planned_source_names = (
        selected_live_source_names(settings, effective_source_limit)
        if mode == "live" and not reuse_context
        else []
    )
    planned_source_query_tasks = len(planned_source_names) * policy.query_count
    http_attempt_budget = (
        RequestAttemptBudget(
            max(1, planned_source_query_tasks * FODS_TASK_MAX_ATTEMPTS * settings.max_retries)
        )
        if planned_source_query_tasks
        else None
    )
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
        source_limit=effective_source_limit,
        planned_source_query_tasks=planned_source_query_tasks,
        http_attempt_budget=(http_attempt_budget.maximum if http_attempt_budget else 0),
        task_attempt_limit=FODS_TASK_MAX_ATTEMPTS,
        source_http_retry_attempts=settings.max_retries,
        research_profile=policy.model_dump(mode="json"),
        context_mode="reuse" if reuse_context else context_mode,
        context_id=context_id,
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
            source_searchers = {
                name: _empty_search for name in list(FIXTURE_PAPERS)[:effective_source_limit]
            }
        elif mode == "live":
            if fresh_sources:
                separate_source_cache = Cache(
                    settings.data_dir / "fods" / "source_cache" / f"{run_id}.db"
                )
            source_cache = separate_source_cache or cache
            pool = build_live_source_pool(
                settings,
                source_cache,
                limit=effective_source_limit,
                attempt_budget=http_attempt_budget,
            )
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
        query_llm = (
            llm if mode == "live" and selected_planner == "ollama" and not reuse_context else None
        )
        query_plan = await build_query_plan(
            topic,
            question,
            policy,
            llm=query_llm,
            model=planner_model if query_llm is not None else "",
            event_log=log,
            run_id=run_id,
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
                request,
                topic,
                question,
                output,
                source_names,
                query_plan.queries,
                policy.per_query_limit,
            )
            proposed_tasks = [task.model_dump(mode="json") for task in plan.tasks]
            plan, planner_repairs = canonicalize_llm_research_plan(plan, source_names)
        elif selected_planner == "fixture":
            plan = deterministic_plan(
                request,
                topic,
                question,
                output,
                source_names,
                reuse_context=reuse_context,
                queries=query_plan.queries,
                per_query_limit=policy.per_query_limit,
            )
        else:
            raise ValueError("planner must be auto, ollama, or fixture")

        if not reuse_context:
            plan = plan.model_copy(
                update={
                    "tasks": [
                        task.model_copy(
                            update={"args": {**task.args, "limit": policy.per_query_limit}}
                        )
                        if task.tool.startswith("search_")
                        else task.model_copy(
                            update={
                                "args": {**task.args, "max_results": policy.max_evidence_papers}
                            }
                        )
                        if task.tool == "retrieve_evidence"
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
                "query_plan": query_plan.model_dump(mode="json"),
                "research_policy": policy.model_dump(mode="json"),
                "context_id": context_id,
                "context_mode": "reuse" if reuse_context else context_mode,
                "source_cache_mode": (
                    "fresh" if fresh_sources and mode == "live" else "configured"
                ),
                "fixtures": FIXTURE_PAPERS,
                "fail_sources": fail_sources or set(),
                "simulated_delay": lambda _name: asyncio.sleep(simulated_delay),
                "answer_model": answer_model,
                "force_invalid_citation": invalid_citation,
                "pre_execution_ms": round((time.perf_counter() - command_started) * 1000, 1),
                "http_attempt_budget": http_attempt_budget,
            },
        )
        if print_cli:
            _show_plan(plan)
            console.print(
                f"mode=[bold]{mode}[/] planner=[bold]{selected_planner}[/] "
                f"schedule=[bold]{schedule}[/] workers={concurrency} "
                f"profile=[bold]{policy.profile}[/] target={policy.target_unique_papers} "
                f"budget={policy.budget_seconds}s "
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
                research_budget_seconds=max(
                    0.0, policy.budget_seconds - (time.perf_counter() - command_started)
                ),
                research_profile=policy.model_dump(mode="json"),
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
            _print_research_summary(result, query_plan, policy)
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
    source_limit: Annotated[int | None, typer.Option(min=2, max=5)] = None,
    profile: Annotated[
        str, typer.Option(help="Research latency/coverage profile: quick or deep.")
    ] = "quick",
    target_papers: Annotated[int | None, typer.Option(min=1, max=30)] = None,
    max_retained_papers: Annotated[int | None, typer.Option(min=1, max=50)] = None,
    max_evidence_papers: Annotated[int | None, typer.Option(min=1, max=15)] = None,
    budget_seconds: Annotated[int | None, typer.Option(min=30, max=600)] = None,
    per_query_limit: Annotated[int | None, typer.Option(min=1, max=20)] = None,
    candidate_limit: Annotated[int | None, typer.Option(min=1, max=100)] = None,
    query_count: Annotated[int | None, typer.Option(min=1, max=6)] = None,
    evidence_token_budget: Annotated[int | None, typer.Option(min=1000, max=30000)] = None,
    context_mode: Annotated[
        str, typer.Option(help="Context selection: auto, build, reuse, or refresh.")
    ] = "auto",
    context_id: Annotated[
        str, typer.Option(help="Reuse a named immutable context snapshot ID.")
    ] = "",
) -> None:
    """Gather, reuse, answer, cite-check, and save a research brief."""
    if schedule not in {"fifo", "priority"}:
        raise typer.BadParameter("schedule must be fifo or priority")
    if profile not in {"quick", "deep"}:
        raise typer.BadParameter("profile must be quick or deep")
    overrides = {
        key: value
        for key, value in {
            "source_limit": source_limit,
            "target_unique_papers": target_papers,
            "max_retained_papers": max_retained_papers,
            "max_evidence_papers": max_evidence_papers,
            "budget_seconds": budget_seconds,
            "per_query_limit": per_query_limit,
            "candidate_limit": candidate_limit,
            "query_count": query_count,
            "evidence_token_budget": evidence_token_budget,
        }.items()
        if value is not None
    }
    try:
        policy = profile_for(profile, **overrides)
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc
    if context_mode not in {"auto", "build", "reuse", "refresh"}:
        raise typer.BadParameter("context-mode must be auto, build, reuse, or refresh")
    if output and (Path.cwd() / output).exists():
        raise typer.BadParameter(f"refusing to overwrite existing brief: {output}")
    if event_log is not None and event_log.exists():
        raise typer.BadParameter(f"refusing to overwrite existing event log: {event_log}")
    request_text = request or f"Research {topic} and answer: {question}"

    def execute():
        return asyncio.run(
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
                source_limit=policy.source_limit,
                research_policy=policy,
                context_mode="reuse" if reuse_context else context_mode,
                context_id=context_id,
            )
        )

    if mode == "live":
        try:
            with LiveCollectionLock(get_settings().data_dir):
                succeeded = execute()
        except LiveCollectionInProgress as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        succeeded = execute()
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


@graph_app.command("build")
@_serialize_graph_mutation
def graph_build_command(
    topic: Annotated[str, typer.Option(help="Research topic to build the graph for.")],
    context_id: Annotated[str, typer.Option(help="Context snapshot ID; omit to use latest.")] = "",
    output_json: Annotated[
        str, typer.Option("--output-json", help="Output JSON path for graph.")
    ] = "",
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing graph files.")] = False,
) -> None:
    """Build a deterministic graph snapshot from saved enrichment artifacts."""
    import json
    import time

    from fods.knowledge_graph import (
        classify_inputs,
        empty_snapshot,
        publish,
        statistics,
        update_snapshot,
    )
    from fods.tools import read_context_snapshot

    settings = get_settings()
    context = read_context_snapshot(settings.data_dir, topic, context_id)
    papers, enrichments, eligibility = classify_inputs(settings.data_dir, topic, context)
    if not enrichments:
        raise typer.BadParameter(
            "No current, hash-matched enrichments found for this topic/context."
        )
    topic_key = content_hash(topic)[:16]
    path = (
        Path(output_json)
        if output_json
        else settings.data_dir / "fods" / "knowledge_graph" / topic_key / "graph.json"
    )
    if path.exists() and not force:
        raise typer.BadParameter("Graph snapshot already exists; pass --force to rebuild it.")
    import tracemalloc

    tracemalloc.start()
    start = time.perf_counter()
    graph, changes = update_snapshot(empty_snapshot(topic), papers, enrichments)
    build_ms = round((time.perf_counter() - start) * 1000, 3)
    peak_memory_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    graph["manifest"].update({"context_id": context["context_hash"], "build_ms": build_ms})
    publish_start = time.perf_counter()
    publish(path, graph)
    publish_ms = round((time.perf_counter() - publish_start) * 1000, 3)
    stats = statistics(graph)
    report_path = settings.data_dir / "fods" / "knowledge_graph" / topic_key / "performance.json"
    report_path.write_text(
        json.dumps(
            {
                "initial_build_ms": build_ms,
                "initial_publish_ms": publish_ms,
                "initial_total_ms": round(build_ms + publish_ms, 3),
                "peak_memory_bytes": peak_memory_bytes,
                "normalization_and_indexing_ms": changes["indexing_ms"],
                "validation_ms": changes["validation_ms"],
                "records_inspected": changes["inspected"],
                "eligible_papers": changes["processed"],
                "snapshot_bytes": path.stat().st_size,
                "stats": stats,
                "eligibility": eligibility,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(
        f"Built graph: {stats['nodes']} nodes, {stats['edges']} edges; "
        f"{changes['processed']} eligible papers in {build_ms} ms"
    )
    console.print(f"Snapshot: {path}")
    console.print(f"Measurements: {report_path}")


@graph_app.command("update")
@_serialize_graph_mutation
def graph_update_command(
    topic: Annotated[str, typer.Option(help="Research topic to update the graph for.")],
    context_id: Annotated[str, typer.Option(help="Context snapshot ID; omit to use latest.")] = "",
    delete_paper: Annotated[
        list[str] | None,
        typer.Option("--delete-paper", help="Explicitly remove a paper ID from the graph."),
    ] = None,
) -> None:
    """Apply hash-detected graph changes and atomically publish the result."""
    import json
    import time

    from fods.knowledge_graph import classify_inputs, publish, statistics, update_snapshot
    from fods.tools import read_context_snapshot

    settings = get_settings()
    context = read_context_snapshot(settings.data_dir, topic, context_id)
    papers, enrichments, eligibility = classify_inputs(settings.data_dir, topic, context)
    topic_key = content_hash(topic)[:16]
    path = settings.data_dir / "fods" / "knowledge_graph" / topic_key / "graph.json"
    if not path.exists():
        raise typer.BadParameter("No graph snapshot exists. Run 'fods graph build' first.")
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        start = time.perf_counter()
        graph, changes = update_snapshot(
            previous, papers, enrichments, deleted=set(delete_paper or [])
        )
        graph["manifest"].update(
            {
                "context_id": context["context_hash"],
                "update_ms": round((time.perf_counter() - start) * 1000, 3),
            }
        )
        publish_start = time.perf_counter()
        publish(path, graph)
        changes["publish_ms"] = round((time.perf_counter() - publish_start) * 1000, 3)
        changes["total_ms"] = round(changes["elapsed_ms"] + changes["publish_ms"], 3)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"Graph update was rejected; previous snapshot remains intact: {exc}"
        ) from exc
    stats = statistics(graph)
    report_path = path.with_name("performance.json")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report.setdefault("updates", []).append(
        {**changes, "snapshot_bytes": path.stat().st_size, "eligibility": eligibility}
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    console.print(
        f"Updated: {changes['new']} new, {changes['changed']} changed, "
        f"{changes['deleted']} deleted; {changes['processed']} reprocessed "
        f"in {changes['elapsed_ms']} ms"
    )
    console.print(f"Graph: {stats['nodes']} nodes, {stats['edges']} edges; snapshot: {path}")


@graph_app.command("query")
def graph_query_command(
    topic: Annotated[str, typer.Option(help="Research topic to query.")],
    concept: Annotated[str, typer.Option("--concept", help="Find papers for a concept.")] = "",
    paper: Annotated[str, typer.Option("--paper", help="Find relations for a paper.")] = "",
    concept_a: Annotated[
        str, typer.Option("--concept-a", help="First concept for shared concepts query.")
    ] = "",
    concept_b: Annotated[
        str, typer.Option("--concept-b", help="Second concept for shared concepts query.")
    ] = "",
    method: Annotated[str, typer.Option("--method", help="Find papers using a method.")] = "",
    finding: Annotated[
        str, typer.Option("--finding", help="Find papers reporting a finding.")
    ] = "",
    limitation: Annotated[
        str, typer.Option("--limitation", help="Find papers with a limitation.")
    ] = "",
    cites: Annotated[str, typer.Option("--cites", help="Find papers citing a paper.")] = "",
    max_depth: Annotated[int, typer.Option("--max-depth", min=0, max=5)] = 2,
    max_nodes: Annotated[int, typer.Option("--max-nodes", min=1, max=500)] = 50,
    max_edges: Annotated[int, typer.Option("--max-edges", min=1, max=1000)] = 100,
    output: Annotated[str, typer.Option("--output", help="Output JSON file for results.")] = "",
    max_evidence: Annotated[int, typer.Option("--max-evidence", min=1, max=200)] = 20,
) -> None:
    """Query the existing graph snapshot without rebuilding or making model calls."""
    import json

    from fods.knowledge_graph import query as run_graph_query

    settings = get_settings()
    path = settings.data_dir / "fods" / "knowledge_graph" / content_hash(topic)[:16] / "graph.json"
    if not path.exists():
        raise typer.BadParameter("No graph snapshot found. Run 'fods graph build' first.")
    selected = [
        ("CONCEPT", concept),
        ("PAPER", paper),
        ("METHOD", method),
        ("FINDING", finding),
        ("LIMITATION", limitation),
        ("CITED_BY", cites),
    ]
    selected = [(kind, value) for kind, value in selected if value]
    if concept_a and concept_b:
        selected.append(("SHARED", f"{concept_a}|{concept_b}"))
    if len(selected) != 1:
        raise typer.BadParameter(
            "Specify one query: --concept, --paper, --method, --finding, --limitation, "
            "--cites, or --concept-a with --concept-b."
        )
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    start = time.perf_counter()
    result = run_graph_query(
        snapshot,
        kind=selected[0][0],
        value=selected[0][1],
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_evidence=max_evidence,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    result["query_elapsed_ms"] = elapsed_ms
    if output:
        Path(output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        console.print(json.dumps(result, indent=2, ensure_ascii=False))


@graph_app.command("stats")
def graph_stats_command(topic: Annotated[str, typer.Option()]) -> None:
    """Show the current graph manifest and node/edge counts."""
    import json

    from fods.knowledge_graph import statistics

    path = (
        get_settings().data_dir
        / "fods"
        / "knowledge_graph"
        / content_hash(topic)[:16]
        / "graph.json"
    )
    if not path.exists():
        raise typer.BadParameter("No graph snapshot found. Run 'fods graph build' first.")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    console.print_json(
        json.dumps(
            {"path": str(path), **statistics(snapshot), "manifest": snapshot.get("manifest", {})}
        )
    )


@graph_app.command("follow-up")
def graph_followup_command(
    topic: Annotated[str, typer.Option(help="Research topic whose saved graph to query.")],
    question: Annotated[str, typer.Option(help="A supported graph follow-up question.")],
    max_depth: Annotated[int, typer.Option(min=0, max=5)] = 3,
    max_nodes: Annotated[int, typer.Option(min=1, max=500)] = 200,
    max_edges: Annotated[int, typer.Option(min=1, max=1000)] = 500,
    max_evidence: Annotated[int, typer.Option(min=1, max=200)] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Answer a supported follow-up from the existing graph and its stored evidence."""
    import json

    from fods.graph_followup import route_question, run_followup

    route = route_question(question)
    if route is None:
        typer.echo(
            "Unsupported graph follow-up. Try: 'Which papers use GAT?', "
            "'Which papers discuss graph attention networks?', "
            "'What findings are reported for graph attention networks?', "
            "'What limitations are mentioned for graph attention networks?', "
            "'Which papers cite <paper-id>?', or "
            "'What concepts are shared between <paper-id> and <paper-id>?'. "
            "Use 'fods graph query' for a structured query."
        )
        return

    path = (
        get_settings().data_dir
        / "fods"
        / "knowledge_graph"
        / content_hash(topic)[:16]
        / "graph.json"
    )
    if not path.exists():
        typer.echo(
            f"No graph snapshot found for {topic!r}. Run 'fods graph build --topic {topic!r}' "
            "after saving enrichments. Follow-up never builds a graph automatically."
        )
        return
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    response = run_followup(
        snapshot,
        route,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_evidence=max_evidence,
    )
    response["question"] = question
    if json_output:
        typer.echo(json.dumps(response, indent=2, ensure_ascii=False))
        return

    typer.echo(response["summary"])
    for record in response["evidence_records"]:
        segments = ", ".join(record["segment_ids"])
        typer.echo(
            f"- {record['paper_title']} ({record['paper_id']}) — "
            f"{record['relationship']}: {record['item']}\n"
            f"  Evidence {segments}: {record['excerpt']}"
        )
    for record in response["bibliographic_records"]:
        typer.echo(
            f"- {record['citing_paper_title']} ({record['citing_paper_id']}) cites "
            f"{record['cited_paper_title']} ({record['cited_paper_id']}) "
            "[stored bibliographic reference]"
        )


if __name__ == "__main__":
    app()
