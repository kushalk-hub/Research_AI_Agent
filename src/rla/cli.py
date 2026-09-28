"""`rla` command line interface."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from rla.config import get_settings
from rla.events import Event
from rla.llm.factory import build_client
from rla.models import Corpus
from rla.pipeline.gaps import GapReport
from rla.pipeline.orchestrator import Pipeline, PipelineResult
from rla.store.cache import Cache, CostTracker
from rla.store.graph_store import load as load_graph
from rla.store.graph_store import stats as graph_stats

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Graph-based research literature agent."
)
console = Console()

#: Milestone in which each still-unimplemented command becomes functional.
#: Commands still awaiting their milestone. `ask`, `report`, and `tui` are done,
#: so they are absent: a command that reaches `_pending` without an entry here
#: would raise a KeyError instead of printing the milestone.
COMMAND_MILESTONE = {
    "eval": "P8",
}

PHASE_STYLE = {
    "search": "cyan",
    "fetch": "blue",
    "score": "magenta",
    "fulltext": "yellow",
    "extract": "green",
    "resolve": "green",
    "graph": "yellow",
    "traverse": "cyan",
    "answer": "bright_cyan",
    "gaps": "magenta",
    "done": "bold green",
    "error": "bold red",
}


def _pending(command: str) -> None:
    milestone = COMMAND_MILESTONE[command]
    console.print(
        f"[yellow]{command}[/] is not implemented yet - scheduled for [bold]{milestone}[/]."
    )
    console.print("See PLAN.md section 3 for the acceptance gate it must clear.")


def _print_event(evt: Event) -> None:
    style = PHASE_STYLE.get(str(evt.phase), "white")
    marker = {"error": "x", "warn": "!", "ok": "+", "pending": "."}.get(evt.kind, "-")
    console.print(f"[{style}]{str(evt.phase):<9}[/] [{style}]{marker}[/] {evt.message}")


def _build_pipeline() -> tuple[Pipeline, Cache, PipelineResult]:
    """Wire the pipeline once, so `run` and `tui` cannot drift apart.

    The LLM client is built by the factory from configuration, so selecting a
    provider is an env var rather than a code edit.

    Returns the cache too because the caller owns its lifetime: `run` closes it
    when the stream ends, the TUI closes it when the worker finishes.
    """
    settings = get_settings()
    cache = Cache(settings.cache_db)
    tracker = CostTracker()
    llm = build_client(settings, cache, tracker)
    return Pipeline(settings, llm, cache, tracker), cache, PipelineResult()


async def _stream(title: str, question: str, as_jsonl: bool) -> PipelineResult:
    pipeline, cache, result = _build_pipeline()
    try:
        if as_jsonl:
            async for evt in pipeline.run(title, question, result):
                print(json.dumps(evt.to_dict(), ensure_ascii=False), flush=True)
        else:
            async for evt in pipeline.run(title, question, result):
                _print_event(evt)
    finally:
        cache.close()
    return result


@app.command()
def run(
    title: Annotated[str, typer.Option("--title", "-t", help="Research project title.")] = "",
    question: Annotated[str, typer.Option("--question", "-q", help="Question to answer.")] = "",
    jsonl: Annotated[bool, typer.Option("--jsonl", help="Emit one JSON event per line.")] = False,
) -> None:
    """Run the pipeline, streaming events as they happen."""
    if not title:
        title = typer.prompt("Research project title")
    asyncio.run(_stream(title, question, jsonl))


@app.command()
def doctor(
    check_llm: Annotated[
        bool, typer.Option("--llm/--no-llm", help="Send a live test request to the LLM.")
    ] = False,
) -> None:
    """Report configuration, enabled sources, and cache state."""
    settings = get_settings()
    settings.ensure_dirs()
    table = Table(title="rla doctor", show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")

    key_ok = bool(settings.gemini_api_key)
    table.add_row(
        "GEMINI_API_KEY", "[green]set[/]" if key_ok else "[red]missing[/]", settings.fast_model
    )
    for source in settings.enabled_sources():
        table.add_row(f"source:{source}", "[green]enabled[/]", "keyless")
    if not settings.serpapi_api_key:
        table.add_row(
            "source:serpapi",
            "[yellow]disabled[/]",
            "no SERPAPI_API_KEY - recent preprints may be missed",
        )

    with Cache(settings.cache_db) as cache:
        cache_stats = cache.stats()
    table.add_row("cache", "[green]ok[/]", json.dumps(cache_stats))
    table.add_row(
        "data dir",
        "[green]ok[/]" if settings.data_dir.exists() else "[red]missing[/]",
        str(settings.data_dir),
    )

    console.print(table)
    if not key_ok:
        console.print(
            "[yellow]LLM stages will not run without a key. Data acquisition (P1) is keyless.[/]"
        )
        return
    if not check_llm:
        console.print("[dim]run `rla doctor --llm` to verify the key actually works[/]")
        return

    status, detail = asyncio.run(_probe_llm(settings))
    console.print(f"LLM [{'green' if status == 'ok' else 'red'}]{status}[/] {detail}")


async def _probe_llm(settings) -> tuple[str, str]:
    """Verify the key against the live API.

    Deliberately constructed *without* a cache. A cache-first probe reports a
    stale "ok" from a call that succeeded under an earlier key, which is exactly
    the situation this command exists to detect -- a green light here must mean
    a real request went out just now.

    Every configured model is probed, not just the text one. A key can be
    perfectly valid while a model on it is retired (404) or outside the tier
    (429 "limit: 0"), and those failures only surface much later as a dead
    extraction or resolution stage.

    Probes the *configured* backend, so `RLA_LLM_PROVIDER=litellm rla doctor --llm`
    verifies the routing layer rather than the Gemini SDK behind it.
    """
    from rla.llm.base import LLMError
    from rla.llm.embeddings import Embedder
    from rla.llm.errors import ProviderError
    from rla.llm.factory import build_client

    try:
        client = build_client(settings, None, CostTracker())
    except Exception as exc:
        return "unusable", f"cannot build the configured backend: {exc}"
    if client is None:
        return "unusable", "GEMINI_API_KEY is not set"

    problems: list[str] = []

    for label, model in (
        ("structured", settings.model_for_structured),
        ("answer", settings.model_for_answer),
    ):
        try:
            text = await client.generate_text(
                "Reply with the single word: ok", stage="doctor", model=model
            )
            detail = f"{label} {model} ok ({text.strip()[:20]!r})"
        except LLMError as exc:
            reason = " ".join(str(exc).split())
            problems.append(f"{label} {model}: {reason[:120]}{_hint(reason)}")
            continue
        if not problems:
            console.print(f"[green]{detail}[/]")

    console.print(f"[dim]backend: {client.backend.name}[/]")

    try:
        vector = await Embedder(settings, None, CostTracker()).embed_one("doctor")
        if not problems:
            console.print(
                f"[green]embedding {settings.embedding_model} ok ({len(vector)} dims)[/]"
            )
    except (LLMError, ProviderError) as exc:
        reason = " ".join(str(exc).split())
        problems.append(f"embedding {settings.embedding_model}: {reason[:120]}{_hint(reason)}")

    if not problems:
        return "ok", f"{settings.model_for_structured}, {settings.embedding_model} reachable"
    return "unusable", "; ".join(problems)


def _hint(reason: str) -> str:
    """Turn a recognisable failure into the one action that actually fixes it."""
    low = reason.lower()
    if "credential" in low or "api key" in low:
        return " - looks like an OAuth token, not an AI Studio key"
    if "not_found" in low or "404" in reason:
        return " - model retired; pick a current one in .env"
    if "limit: 0" in low or "resource_exhausted" in low:
        return " - free tier has no quota for this model; use a flash-tier model"
    if "quota" in low and "day" in low:
        return " - the daily per-model allowance is spent; use a model with quota left"
    return ""


@app.command()
def stats() -> None:
    """Summarise the cached corpus and built graph."""
    settings = get_settings()

    corpus_table = Table(title="corpus", show_header=True, header_style="bold")
    corpus_table.add_column("metric")
    corpus_table.add_column("value")
    if settings.corpus_path.exists():
        corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
        for key, value in corpus.stats().items():
            corpus_table.add_row(key, str(value))
        for source, count in sorted(corpus.source_yield.items()):
            corpus_table.add_row(f"yield:{source}", str(count))
    else:
        corpus_table.add_row("status", "[yellow]no corpus yet - run `rla build` (P1)[/]")
    console.print(corpus_table)

    graph_table = Table(title="graph", show_header=True, header_style="bold")
    graph_table.add_column("metric")
    graph_table.add_column("value")
    if settings.graph_json.exists():
        for key, value in graph_stats(load_graph(settings.graph_json)).items():
            graph_table.add_row(key, str(value))
    else:
        graph_table.add_row("status", "[yellow]no graph yet - built in P4[/]")
    console.print(graph_table)


@app.command()
def sources(
    probe: Annotated[
        str, typer.Option("--probe", help="Query to test each source against.")
    ] = "graph attention networks",
    use_cache: Annotated[
        bool,
        typer.Option(
            "--cache/--no-cache",
            help="Answer from the HTTP cache instead of calling the source.",
        ),
    ] = False,
) -> None:
    """Probe every enabled source and report which ones actually work.

    Worth running before a build: a source behind bot protection or a rate limit
    fails silently as "zero results" otherwise.

    Bypasses the cache by default. A cached reply proves a source worked at some
    point, not that it works now, and a stale "ok" is how a dead source slips
    through and yields a citation-less corpus.
    """
    asyncio.run(_probe_sources(probe, use_cache=use_cache))


async def _probe_sources(probe: str, use_cache: bool = False) -> None:
    import httpx

    from rla.pipeline.acquisition import PER_QUERY_LIMIT, _short, build_sources

    settings = get_settings()
    settings.ensure_dirs()
    cache = Cache(settings.cache_db)
    # A throwaway cache path: the probe must not read or write the build cache.
    probe_cache = cache if use_cache else Cache(settings.cache_db.with_suffix(".probe.db"))
    adapters = build_sources(settings, probe_cache)

    table = Table(title=f"source probe: {probe!r}", show_header=True, header_style="bold")
    table.add_column("source")
    table.add_column("status")
    table.add_column("results", justify="right")
    table.add_column("detail")

    async def check(name: str, source) -> tuple[str, int, str]:
        try:
            papers = await source.search(probe, 5)
        except (RuntimeError, httpx.HTTPError) as exc:
            return "unusable", 0, _short(exc)
        return ("ok" if papers else "empty"), len(papers), ""

    results: dict[str, tuple[str, int]] = {}
    for name, source in adapters.items():
        status, count, detail = await check(name, source)
        results[name] = (status, count)
        colour = {"ok": "green", "empty": "yellow", "unusable": "red"}[status]
        note = detail or f"limit {PER_QUERY_LIMIT.get(name, 20)}"
        if not use_cache:
            note = f"{note}, no cache"
        table.add_row(
            name,
            f"[{colour}]{status}[/]",
            str(count),
            note,
        )

    console.print(table)
    live = [name for name, (status, _) in results.items() if status == "ok"]
    dead = [name for name, (status, _) in results.items() if status != "ok"]
    console.print(f"[green]live:[/] {', '.join(live) if live else 'none'}")
    if dead:
        console.print(f"[red]not usable:[/] {', '.join(dead)}")
    if not use_cache:
        probe_cache.close()
        with suppress(OSError):
            settings.cache_db.with_suffix(".probe.db").unlink()
    cache.close()


@app.command()
def build(
    title: Annotated[str, typer.Option("--title", "-t", help="Research project title.")] = "",
    jsonl: Annotated[bool, typer.Option("--jsonl", help="Emit one JSON event per line.")] = False,
) -> None:
    """Acquire a corpus of 40-100 papers from every enabled source."""
    if not title:
        title = typer.prompt("Research project title")
    result = asyncio.run(_stream(title, "", jsonl))
    if result.corpus is None:
        raise typer.Exit(code=1)
    _print_acquisition(result)


def _print_acquisition(result: PipelineResult) -> None:
    report = result.acquisition
    table = Table(title="acquisition", show_header=True, header_style="bold")
    table.add_column("metric")
    table.add_column("value")
    for key, value in report.items():
        if key == "notes":
            continue
        table.add_row(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
    console.print(table)

    if result.corpus is not None:
        stats = result.corpus.stats()
        console.print(
            f"[green]corpus:[/] {stats['papers']} papers, "
            f"{stats['with_abstract']} with abstracts, {stats['with_year']} with years, "
            f"{stats['with_doi']} with DOIs"
        )
        console.print(f"[dim]queries:[/] {', '.join(result.corpus.queries)}")

    for note in report.get("notes", []):
        console.print(f"[yellow]note:[/] {note}")


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question to answer.")] = "",
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Print the answer as Markdown.")
    ] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl", help="Emit one JSON event per line.")] = False,
) -> None:
    """Answer a lineage, gap, comparison, or overview question from the built graph.

    Reads the graph written by `rla run`; it does not re-acquire anything, so it
    costs one answer request and nothing else.
    """
    if not question:
        question = typer.prompt("Question")
    settings = get_settings()
    if not settings.graph_json.exists():
        console.print(
            f"[red]no graph at[/] {settings.graph_json}\n"
            "Build one first with [bold]rla run -t \"<topic>\"[/]."
        )
        raise typer.Exit(code=1)

    graph = load_graph(settings.graph_json)
    if graph is None or graph.number_of_nodes() == 0:
        console.print("[red]the graph on disk is empty[/]; rebuild it with `rla run`.")
        raise typer.Exit(code=1)

    from rla.pipeline.answer import answer_question_result, render_markdown

    cache = Cache(settings.cache_db)
    tracker = CostTracker()
    llm = build_client(settings, cache, tracker)
    if llm is None:
        console.print(
            "[yellow]no GEMINI_API_KEY set[/]; showing the traversed subgraph only."
        )
    answer, events = asyncio.run(answer_question_result(graph, question, llm))
    cache.close()

    for evt in events:
        if jsonl:
            print(json.dumps(evt.to_dict(), ensure_ascii=False), flush=True)
        else:
            _print_event(evt)

    if answer is None:
        raise typer.Exit(code=1)
    console.print()
    console.print(render_markdown(answer) if markdown else answer.answer)
    if answer.stripped_citations and not jsonl:
        console.print(
            f"[yellow]stripped {len(answer.stripped_citations)} unsupported citation(s):[/] "
            + ", ".join(answer.stripped_citations)
        )


@app.command()
def report(
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Print the report as Markdown.")
    ] = True,
    jsonl: Annotated[
        bool, typer.Option("--jsonl", help="Emit the report as one JSON document.")
    ] = False,
) -> None:
    """Emit the full report: per-paper limitations plus synthesized gaps.

    Reads the corpus, the extraction store, and the graph written by `rla run`.
    Costs no LLM requests: every claim comes from an extraction or a graph edge,
    which is the point of the section, since a gap nobody said out loud has to be
    visible as an inference rather than as a quotation.
    """
    from rla.pipeline.gaps import build_gap_report, render_report, report_stats
    from rla.store.extraction_store import ExtractionStore

    settings = get_settings()
    if not settings.corpus_path.exists():
        console.print(
            f"[red]no corpus at[/] {settings.corpus_path}\n"
            "Build one first with [bold]rla run -t \"<topic>\"[/]."
        )
        raise typer.Exit(code=1)

    corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
    store = ExtractionStore(settings.extractions_path)
    store.load()
    extractions = store.all()
    graph = load_graph(settings.graph_json) if settings.graph_json.exists() else None

    gap_report = build_gap_report(extractions, graph, corpus.papers)
    if jsonl:
        print(json.dumps(gap_report.to_dict(), ensure_ascii=False, indent=2), flush=True)
        return

    console.print(render_report(gap_report) if markdown else _render_plain(gap_report))
    stats = report_stats(gap_report)
    console.print(
        f"[dim]{stats['papers_considered']} paper(s), "
        f"{stats['papers_with_limitations']} with a stated limitation, "
        f"{stats['themes']} theme(s), {stats['structural']} structural gap(s), "
        f"{stats['gaps']} ranked gap(s), {stats['suppressed']} suppressed.[/]"
    )


def _render_plain(gap_report: GapReport) -> str:
    """Gap report without Markdown, for terminals that render it badly."""
    from rla.pipeline.gaps import render_report

    return re.sub(r"[*_`#]", "", render_report(gap_report))


@app.command()


def eval() -> None:
    """Run the evaluation harness and write eval/report.md."""
    from rla.config import get_settings
    from rla.eval.run_eval import render_table, run_eval

    settings = get_settings()
    eval_dir = Path(settings.data_dir) / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    report = run_eval(settings)

    # Write Markdown report
    md = render_table(report)
    (eval_dir / "report.md").write_text(md, encoding="utf-8")

    # Write JSON serialisation for programmatic use
    (eval_dir / "results.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )

    console.print("[green]Evaluation complete.[/]")
    console.print(f"  Report: {eval_dir / 'report.md'}")
    console.print(f"  JSON:   {eval_dir / 'results.json'}")


@app.command()
def tui(
    title: Annotated[str, typer.Option("--title", "-t", help="Research project title.")] = "",
    question: Annotated[str, typer.Option("--question", "-q", help="Question to answer.")] = "",
) -> None:
    """Run the pipeline in a live terminal UI: phases, counters, tree, answer.

    Reads the same event stream as `rla run`, so what the UI shows and what the
    headless runner logs cannot drift apart. Requires the `tui` extra:
    `pip install -e ".[tui]"`.
    """
    try:
        from rla.tui.app import RlaApp
        from rla.tui.state import PipelineState
    except ImportError as exc:
        console.print(
            f"[red]the TUI needs Textual:[/] {exc}\n"
            'Install it with [bold]pip install -e ".[tui]"[/].'
        )
        raise typer.Exit(code=1) from exc

    if not title:
        title = typer.prompt("Research project title")

    state = PipelineState(title=title, question=question)
    if not get_settings().gemini_api_key:
        # Warn before the app takes over the screen, or it scrolls off unseen.
        console.print("[yellow]no GEMINI_API_KEY set;[/] LLM stages will be skipped.")

    pipeline, cache, result = _build_pipeline()

    async def _events():
        try:
            async for evt in pipeline.run(title, question, result):
                yield evt
        finally:
            cache.close()

    RlaApp(state, _events()).run()


@app.command()
def events() -> None:
    """Print the pipeline phase order the TUI status bar will use."""
    from rla.events import PIPELINE_PHASES

    for index, phase in enumerate(PIPELINE_PHASES, start=1):
        console.print(f"{index}. [cyan]{phase}[/]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
