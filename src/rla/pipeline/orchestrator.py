"""Event-emitting pipeline orchestrator (spec section 8).

The whole point of this module is the shape of `run()`: it *yields* typed Events
rather than returning a result, so the headless JSONL runner and the Textual UI
consume exactly the same stream.

Implemented through P3. Later milestones add their stages to the phase loop and
flip the matching entry in `IMPLEMENTED_PHASES`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from rla.config import Settings, get_settings
from rla.events import Event, Phase, event
from rla.llm.base import LLMClient
from rla.models import Concept, Corpus
from rla.store.cache import Cache, CostTracker
from rla.store.graph_store import Graph

#: Milestone that implements each phase. Phases above the current build are
#: emitted as `pending` events so the UI and the log show the real phase order.
PHASE_MILESTONE: dict[Phase, str] = {
    Phase.SEARCH: "P1",
    Phase.FETCH: "P1",
    Phase.SCORE: "P1",
    Phase.FULLTEXT: "P2 (phase 2)",
    Phase.EXTRACT: "P2",
    Phase.RESOLVE: "P3",
    Phase.GRAPH: "P4",
    Phase.TRAVERSE: "P5",
    Phase.ANSWER: "P5",
    Phase.DONE: "P0",
    Phase.ERROR: "P0",
}

IMPLEMENTED_PHASES: frozenset[Phase] = frozenset(
    {
        Phase.SEARCH,
        Phase.FETCH,
        Phase.SCORE,
        Phase.EXTRACT,
        Phase.RESOLVE,
        Phase.GRAPH,
        Phase.TRAVERSE,
        Phase.ANSWER,
        Phase.DONE,
        Phase.ERROR,
    }
)


@dataclass
class PipelineResult:
    """Filled in place by `Pipeline.run` as stages complete."""

    title: str = ""
    question: str = ""
    corpus: Corpus | None = None
    graph: Graph | None = None
    concepts: list[Concept] = field(default_factory=list)
    answer: str = ""
    #: Populated in P5; typed loosely to keep this module import-light.
    answer_result: Any = None
    extraction: dict[str, Any] = field(default_factory=dict)
    acquisition: dict[str, Any] = field(default_factory=dict)
    resolution: dict[str, Any] = field(default_factory=dict)
    graph_report: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


class Pipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        cache: Cache | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.llm = llm
        self.cache = cache
        self.tracker = tracker or CostTracker()

    async def run(
        self,
        title: str,
        question: str = "",
        result: PipelineResult | None = None,
    ) -> AsyncIterator[Event]:
        """Drive the pipeline, yielding an Event per meaningful step.

        Consumers iterate this; nothing is returned. `result` is populated as a
        side channel so callers that need the corpus or graph still get them.
        """
        result = result if result is not None else PipelineResult(title=title, question=question)
        result.title, result.question = title, question

        # The LLM spender is a process-wide singleton keyed by budget and event
        # loop, so without this a second run in the same loop started already
        # charged for the first one's requests and could refuse work it had budget
        # for. A run is the natural scope for a local spend allowance.
        from rla.llm.retry import reset_spender

        reset_spender()

        yield event(
            Phase.SEARCH,
            f"Starting pipeline for {title!r}",
            sources=len(self.settings.enabled_sources()),
        )

        # --- P1: acquisition ------------------------------------------------
        if self.cache is None:
            yield event(Phase.FETCH, "No cache configured; skipping acquisition", kind="warn")
        else:
            from rla.pipeline.acquisition import Acquisition

            acquisition = Acquisition(self.settings, self.cache, self.llm)
            try:
                async for evt in acquisition.run(title):
                    yield evt
            except Exception as exc:
                result.acquisition = {"error": f"{exc.__class__.__name__}: {exc}"}
                yield event(Phase.FETCH, f"Acquisition failed: {exc}", kind="error")
                yield event(Phase.ERROR, "Pipeline aborted during acquisition", kind="error")
                return

            result.corpus = acquisition.corpus
            result.acquisition = acquisition.report.to_dict()

            if result.corpus is not None:
                self.settings.corpus_path.write_text(
                    result.corpus.model_dump_json(indent=2), "utf-8"
                )
                # Reported under SCORE, the phase that finalises the corpus, so the
                # event stream stays monotonic in phase order.
                yield event(
                    Phase.SCORE,
                    f"Corpus saved to {self.settings.corpus_path.name} "
                    f"({len(result.corpus.papers)} papers)",
                    kind="ok",
                    path=str(self.settings.corpus_path),
                )

        # --- P2 and later milestones ----------------------------------------
        # Walked in phase order rather than run-then-announce: emitting `extract`
        # before the `fulltext` placeholder would make the stream
        # non-monotonic, which is exactly what the TUI status bar relies on.
        # Each phase dispatches on itself; sharing one block across phases
        # would re-run the previous stage for every later phase.
        for phase in (
            Phase.FULLTEXT,
            Phase.EXTRACT,
            Phase.RESOLVE,
            Phase.GRAPH,
            Phase.TRAVERSE,
            Phase.ANSWER,
        ):
            if phase not in IMPLEMENTED_PHASES:
                yield event(
                    phase,
                    f"{phase} stage pending - scheduled for {PHASE_MILESTONE[phase]}",
                    kind="pending",
                )
                continue

            if phase is Phase.EXTRACT:
                if self.llm is None or result.corpus is None:
                    yield event(
                        Phase.EXTRACT,
                        "extraction needs an LLM and a corpus; skipping",
                        kind="pending",
                    )
                    continue
                async for evt in self._run_extraction(result):
                    yield evt

            elif phase is Phase.RESOLVE:
                async for evt in self._run_resolution(result):
                    yield evt

            elif phase is Phase.GRAPH:
                if result.concepts:
                    async for evt in self._run_graph(result):
                        yield evt
                else:
                    yield event(
                        Phase.GRAPH,
                        "graph needs resolved concepts; skipping",
                        kind="pending",
                    )

            elif phase is Phase.TRAVERSE:
                # A question is optional in the build path (`rla run <topic>`), so
                # traversal is only meaningful when one was supplied.
                if not question:
                    yield event(
                        Phase.TRAVERSE,
                        "no question supplied, so there is nothing to traverse",
                        kind="pending",
                    )
                elif result.graph is None:
                    yield event(
                        Phase.TRAVERSE,
                        "traversal needs a built graph; run the graph stage first",
                        kind="pending",
                    )
                else:
                    from rla.pipeline.traverse import traverse

                    sub = traverse(result.graph, question)
                    result.answer_result = sub
                    yield event(
                        Phase.TRAVERSE,
                        f"subgraph selected: {len(sub.nodes)} nodes, {len(sub.edges)} edges",
                        kind="ok",
                        **sub.to_payload(),
                    )

            elif phase is Phase.ANSWER:
                if result.graph is None or not question:
                    yield event(Phase.ANSWER, "no question to answer", kind="pending")
                else:
                    from rla.pipeline.answer import answer_question_result

                    answer_result, answer_events = await answer_question_result(
                        result.graph, question, self.llm
                    )
                    result.answer_result = answer_result
                    result.answer = answer_result.answer if answer_result else ""
                    async for evt in answer_events:
                        yield evt

        stats: dict[str, Any] = {"cache": self.cache.stats() if self.cache else None}
        if self.llm is not None:
            stats["llm"] = self.tracker.to_dict(self.settings.fast_model)
        if result.extraction:
            stats["extraction"] = result.extraction
        if result.resolution:
            stats["resolution"] = result.resolution
        if result.graph_report:
            stats["graph"] = result.graph_report
        result.stats = stats

        yield event(Phase.DONE, "Pipeline finished", kind="ok", **stats)

    async def _run_graph(self, result: PipelineResult) -> AsyncIterator[Event]:
        from rla.pipeline.graph_build import build_graph_stage
        from rla.store.extraction_store import ExtractionStore

        extractions = ExtractionStore(self.settings.extractions_path).all()
        assert result.corpus is not None  # guarded by the caller
        async for evt in build_graph_stage(
            result.corpus,
            result.concepts,
            extractions,
            self.settings.graph_json,
            self.settings.graph_graphml,
        ):
            if "stats" in evt.payload:
                result.graph_report = {
                    k: v for k, v in evt.payload.items() if k not in {"kind", "phase", "message"}
                }
                from rla.store.graph_store import load

                result.graph = load(self.settings.graph_json)
            yield evt

    async def _run_extraction(self, result: PipelineResult) -> AsyncIterator[Event]:
        from rla.pipeline.extraction import extract_papers
        from rla.store.extraction_store import ExtractionStore

        store = ExtractionStore(self.settings.extractions_path)
        assert result.corpus is not None  # guarded by the caller
        async for evt in extract_papers(
            result.corpus.papers,
            self.llm,
            store,
            self.settings.max_concurrency,
            tracker=self.tracker,
            model=self.settings.strong_model,
        ):
            if evt.kind in {"ok", "warn"} and "extracted" in evt.payload:
                result.extraction = {k: v for k, v in evt.payload.items() if k != "cost"}
            yield evt

    async def _run_resolution(self, result: PipelineResult) -> AsyncIterator[Event]:
        from rla.llm.factory import build_embedder
        from rla.pipeline.resolve import resolve_concepts
        from rla.store.extraction_store import ExtractionStore

        extractions = ExtractionStore(self.settings.extractions_path).all()
        if not extractions:
            yield event(
                Phase.RESOLVE,
                "no extractions on disk; run extraction first",
                kind="pending",
            )
            return

        embedder = build_embedder(self.settings, self.cache, self.tracker)
        years = (
            {p.id: p.year for p in result.corpus.papers if p.year}
            if result.corpus is not None
            else {}
        )
        async for evt in resolve_concepts(
            extractions,
            llm=self.llm,
            embedder=embedder,
            concurrency=self.settings.max_concurrency,
            tracker=self.tracker,
            model=self.settings.strong_model,
            paper_years=years,
        ):
            if "concept_nodes" in evt.payload:
                result.concepts = [
                    Concept.model_validate(node) for node in evt.payload["concept_nodes"]
                ]
                result.resolution = {
                    "concepts": len(result.concepts),
                    "merged": len(extractions),
                    "decisions": len(evt.payload.get("decisions", [])),
                }
                self.settings.concepts_path.parent.mkdir(parents=True, exist_ok=True)
                self.settings.concepts_path.write_text(
                    json.dumps(
                        {
                            "concepts": [c.model_dump() for c in result.concepts],
                            "decisions": evt.payload.get("decisions", []),
                        },
                        indent=2,
                    ),
                    "utf-8",
                )
            yield evt
