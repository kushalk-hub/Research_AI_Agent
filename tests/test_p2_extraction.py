"""P2 gate: one structured call per paper, 100% parse rate, resumable, costed."""

from __future__ import annotations

import asyncio
import json

import pytest

from rla.events import PIPELINE_PHASES as PHASE_ORDER
from rla.llm.base import LLMError
from rla.models import ConceptMention, Extraction, Paper, RelationType
from rla.pipeline.extraction import (
    STAGE,
    ExtractionReport,
    PaperFacts,
    build_prompt,
    extract_papers,
)
from rla.store.cache import CostTracker
from rla.store.extraction_store import ExtractionStore

FACTS = PaperFacts(
    summary="Introduces a sparse attention module for multi-agent graphs.",
    concepts=[
        ConceptMention(name="graph attention networks", description="attend over neighbours"),
        ConceptMention(name="multi-agent systems", role="applies-to-new-domain"),
    ],
    builds_on=["vector attention"],
    relation=RelationType.EXTENDS,
    relation_target="graph attention networks",
    stated_limitation="Assumes a static graph topology.",
    inferred_open_problem="How to handle graphs that change during inference.",
)


class RecordingLLM:
    """Counts calls and hands back a valid, schema-shaped answer."""

    def __init__(
        self,
        tracker: CostTracker | None = None,
        fail_on: set[str] | None = None,
        auth_error: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.tracker = tracker
        self.fail_on = fail_on or set()
        self.auth_error = auth_error

    async def generate_structured(self, prompt, schema, **kwargs):
        self.calls.append(prompt)
        # Yield to the loop the way a real network call does. Without this the
        # tasks would all run in one scheduling pass and per-paper progress
        # would be untestable.
        await asyncio.sleep(0)
        if self.auth_error:
            raise LLMError("401 UNAUTHENTICATED: request had invalid authentication credentials")
        paper_id = next(
            line.split(":", 1)[1].strip()
            for line in prompt.splitlines()
            if line.startswith("Title:")
        )
        if paper_id in self.fail_on:
            raise LLMError("429 resource exhausted")
        if self.tracker is not None:
            self.tracker.record(STAGE, input_tokens=900, output_tokens=150)
        return schema.model_validate(json.loads(FACTS.model_dump_json()))


@pytest.fixture
def corpus() -> list[Paper]:
    return [
        Paper(
            id=f"p{i}",
            title=f"Paper {i}",
            year=2020 + i,
            abstract=f"Abstract for paper {i}. It studies agents and graphs.",
        )
        for i in range(5)
    ]


# -- Prompt --------------------------------------------------------------------


def test_prompt_carries_the_paper_and_bounds_the_body():
    paper = Paper(id="p1", title="A Study", year=2024, venue="NeurIPS", abstract="x " * 5000)
    prompt = build_prompt(paper)

    assert "A Study" in prompt
    assert "NeurIPS" in prompt
    assert "--- ABSTRACT ---" in prompt
    # Bounded, and explicitly marked as truncated rather than silently cut.
    assert "[...]" in prompt
    assert len(prompt) < 6000


def test_a_paper_without_an_abstract_still_produces_a_usable_prompt():
    prompt = build_prompt(Paper(id="p1", title="Title Only", year=None))
    assert "Title Only" in prompt
    assert "unknown" in prompt
    assert "no text available" in prompt


# -- Facts mapping -------------------------------------------------------------


def test_ids_are_stamped_from_the_corpus_not_the_model():
    paper = Paper(id="p-real", title="A Study", year=2024, abstract="text")
    extraction = PaperFacts(summary="s").to_extraction(paper)

    assert extraction.paper_id == "p-real"
    assert extraction.paper_hash == paper.content_hash
    assert extraction.extraction_hash


def test_blank_concepts_are_dropped_rather_than_kept_as_empty_nodes():
    extraction = PaperFacts(
        concepts=[ConceptMention(name="  "), ConceptMention(name="graph networks")]
    ).to_extraction(Paper(id="p1", title="t", abstract="a"))
    assert [c.name for c in extraction.concepts] == ["graph networks"]


def test_an_absent_limitation_stays_empty_instead_of_being_invented():
    extraction = PaperFacts(summary="s").to_extraction(Paper(id="p1", title="t", abstract="a"))
    assert extraction.stated_limitation == ""
    assert extraction.inferred_open_problem == ""


# -- The stage itself ----------------------------------------------------------


@pytest.mark.asyncio
async def test_every_paper_yields_a_parsed_extraction(corpus, tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM()

    events = [evt async for evt in extract_papers(corpus, llm, store, concurrency=2)]

    summary = events[-1]
    assert summary.payload["extracted"] == 5
    assert summary.payload["failed"] == 0
    assert summary.payload["parse_rate"] == 1.0
    assert len(llm.calls) == 5
    assert len(store) == 5
    assert {e.paper_id for e in store.all()} == {p.id for p in corpus}


@pytest.mark.asyncio
async def test_results_are_persisted_before_the_run_finishes(corpus, tmp_path):
    """A run killed mid-flight must leave a usable prefix on disk."""
    path = tmp_path / "extractions.jsonl"
    store = ExtractionStore(path)
    llm = RecordingLLM()
    seen = 0

    async for _ in extract_papers(corpus, llm, store, concurrency=1):
        seen += 1
        if seen == 3:
            break

    assert path.exists()
    reloaded = ExtractionStore(path)
    assert len(reloaded) == 2
    # Stopped early: not every paper was attempted, and the in-flight one was
    # cancelled rather than left running.
    assert 2 <= len(llm.calls) < len(corpus)


@pytest.mark.asyncio
async def test_an_interrupted_run_resumes_without_recalling_the_model(corpus, tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    first = RecordingLLM()

    seen = 0
    async for _ in extract_papers(corpus, first, store, concurrency=1):
        seen += 1
        if seen == 3:
            break
    stored_before = len(store)
    assert stored_before == 2
    assert len(first.calls) < len(corpus)

    second = RecordingLLM()
    events = [evt async for evt in extract_papers(corpus, second, store, concurrency=2)]

    assert events[0].payload["reused"] == stored_before
    assert events[-1].payload["extracted"] == len(corpus) - stored_before
    # Only the papers that were never stored reach the model the second time.
    assert len(second.calls) == len(corpus) - stored_before
    assert len(store) == len(corpus)


@pytest.mark.asyncio
async def test_a_changed_abstract_invalidates_the_stored_extraction(corpus, tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    first = RecordingLLM()
    async for _ in extract_papers(corpus, first, store, concurrency=2):
        pass
    assert len(store) == 5

    enriched = corpus[0].model_copy(
        update={"abstract": "A corrected and considerably longer abstract about agents."}
    )
    second = RecordingLLM()
    events = [evt async for evt in extract_papers([*corpus[1:], enriched], second, store)]

    assert events[0].payload["reused"] == 4
    assert events[-1].payload["extracted"] == 1
    assert len(second.calls) == 1


@pytest.mark.asyncio
async def test_one_bad_paper_does_not_sink_the_batch(corpus, tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM(fail_on={"Paper 2"})

    events = [evt async for evt in extract_papers(corpus, llm, store, concurrency=5)]

    summary = events[-1]
    assert summary.payload["extracted"] == 4
    assert summary.payload["failed"] == 1
    assert summary.kind == "warn"
    assert "p2" in summary.payload["failures"]
    assert any(evt.kind == "error" and evt.payload.get("paper_id") == "p2" for evt in events)
    assert len(store) == 4


@pytest.mark.asyncio
async def test_every_paper_failing_is_reported_not_silently_empty(corpus, tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM(fail_on={p.title for p in corpus})

    events = [evt async for evt in extract_papers(corpus, llm, store, concurrency=5)]

    assert events[-1].payload["extracted"] == 0
    assert events[-1].payload["failed"] == 5
    assert len(store) == 0


@pytest.mark.asyncio
async def test_repeated_identical_failures_are_collapsed_not_repeated(corpus, tmp_path):
    """One hundred copies of the same error is noise, not information."""
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM(fail_on={p.title for p in corpus})

    events = [evt async for evt in extract_papers(corpus, llm, store, concurrency=5)]

    per_paper = [e for e in events if e.payload.get("paper_id")]
    assert len(per_paper) == 3
    assert any("5 papers failed with the same error" in e.message for e in events)
    # The full count is still in the summary payload, so nothing is lost.
    assert events[-1].payload["failed"] == 5


@pytest.mark.asyncio
async def test_bad_credentials_stop_the_stage_instead_of_failing_100_times(tmp_path):
    papers = [Paper(id=f"p{i}", title=f"Paper {i}", year=2024, abstract="text") for i in range(20)]
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM(auth_error=True)

    events = [evt async for evt in extract_papers(papers, llm, store, concurrency=4)]

    stop = events[-1]
    assert stop.kind == "error"
    assert "stopping after" in stop.message
    assert "rla doctor --llm" in stop.message
    # Far fewer than 20 attempts: the point is to not keep paying for a 401.
    assert len(llm.calls) < 20
    assert stop.payload["extracted"] == 0


@pytest.mark.asyncio
async def test_a_transient_failure_does_not_stop_the_stage(tmp_path):
    """429s are per-request, not systemic: the stage must ride them out."""
    papers = [Paper(id=f"p{i}", title=f"Paper {i}", year=2024, abstract="text") for i in range(6)]
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    llm = RecordingLLM(fail_on={"Paper 0", "Paper 1"})

    events = [evt async for evt in extract_papers(papers, llm, store, concurrency=3)]

    assert events[-1].payload["extracted"] == 4
    assert events[-1].payload["failed"] == 2
    assert len(store) == 4


@pytest.mark.asyncio
async def test_concurrency_is_bounded(corpus, tmp_path):
    live = 0
    peak = 0

    class CountingLLM(RecordingLLM):
        async def generate_structured(self, prompt, schema, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return await super().generate_structured(prompt, schema, **kwargs)

    store = ExtractionStore(tmp_path / "extractions.jsonl")
    async for _ in extract_papers(corpus, CountingLLM(), store, concurrency=2):
        pass

    assert peak <= 2


@pytest.mark.asyncio
async def test_the_cost_of_the_stage_is_reported(corpus, tmp_path):
    tracker = CostTracker()
    store = ExtractionStore(tmp_path / "extractions.jsonl")

    events = [
        evt
        async for evt in extract_papers(
            corpus, RecordingLLM(tracker), store, tracker=tracker, model="gemini-2.5-flash"
        )
    ]

    cost = events[-1].payload["cost"]
    assert cost is not None
    assert cost["calls"] == 5
    assert cost["input_tokens"] == 4500
    assert cost["output_tokens"] == 750
    assert cost["estimated_usd"] > 0
    assert cost["model_priced"] is True
    assert tracker.stage_report(STAGE, "gemini-2.5-flash")["calls"] == 5


def test_an_unpriced_model_is_flagged_rather_than_reported_as_free():
    """A missing price must not look like a confident $0.00.

    Model names churn, so a configured model that this build has no rate for
    would otherwise understate spend without saying so. The estimate is `None`
    and `cost_status` names the reason, rather than a fabricated zero.
    """
    tracker = CostTracker()
    tracker.record("extract", input_tokens=1_000_000, output_tokens=0)
    report = tracker.stage_report("extract", "some-model-released-tomorrow")
    assert report["estimated_usd"] is None
    assert report["model_priced"] is False
    assert report["cost_status"] == "unpriced_model"

    # A genuinely free model is still priced, and says so.
    assert tracker.stage_report("extract", "gemini-embedding-001")["model_priced"] is True


# -- Store ---------------------------------------------------------------------


def test_a_corrupt_line_is_skipped_rather_than_fatal(tmp_path):
    path = tmp_path / "extractions.jsonl"
    good = Extraction(paper_id="p1", paper_hash="h1", summary="ok")
    path.write_text(good.model_dump_json() + "\nnot json at all\n" + "\n", encoding="utf-8")
    store = ExtractionStore(path)
    assert len(store) == 1
    assert store.get("h1") is not None


def test_a_later_line_supersedes_an_earlier_one_for_the_same_paper(tmp_path):
    path = tmp_path / "extractions.jsonl"
    path.write_text(
        Extraction(paper_id="p1", paper_hash="h1", summary="first").model_dump_json()
        + "\n"
        + Extraction(paper_id="p1", paper_hash="h1", summary="second").model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    store = ExtractionStore(path)
    assert len(store) == 1
    assert store.get("h1").summary == "second"


def test_an_extraction_without_a_paper_hash_is_refused(tmp_path):
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    with pytest.raises(ValueError, match="paper_hash"):
        store.add(Extraction(paper_id="p1", summary="orphan"))


def test_report_defaults_to_an_empty_corpus():
    report = ExtractionReport()
    assert report.to_dict()["parse_rate"] == 0.0


# -- Orchestrator wiring -------------------------------------------------------


class _OnePaperSource:
    """Stands in for a real adapter so the wiring test needs no network."""

    name = "fake"
    requires_key = False

    async def search(self, query: str, limit: int) -> list[Paper]:
        return [
            Paper(
                id="p1",
                title="Sparse Graph Reasoning for Multi-Agent Systems",
                year=2024,
                abstract="We introduce a sparse attention module for agent graphs.",
                sources=["fake"],
            )
        ]

    async def references(self, paper, limit):
        return []

    async def citations(self, paper, limit):
        return []


class PipelineLLM(RecordingLLM):
    """Also answers query expansion, which runs before extraction."""

    async def generate_structured(self, prompt, schema, **kwargs):
        if schema.__name__ == "QuerySet":
            return schema(queries=["graph agents"])
        return await super().generate_structured(prompt, schema, **kwargs)


@pytest.mark.asyncio
async def test_the_pipeline_runs_extraction_after_acquisition(settings, cache, monkeypatch):
    monkeypatch.setattr(
        "rla.pipeline.acquisition.build_sources", lambda *a, **k: {"fake": _OnePaperSource()}
    )
    from rla.pipeline.orchestrator import Pipeline, PipelineResult

    result = PipelineResult()
    events = [
        evt
        async for evt in Pipeline(settings, PipelineLLM(), cache, CostTracker()).run(
            "graph agents", result=result
        )
    ]

    phases = [evt.phase for evt in events]
    # Ordering matters: the status bar walks phases monotonically.
    assert phases.index(PHASE_ORDER[3]) < phases.index(PHASE_ORDER[4])
    assert result.extraction["extracted"] == 1
    assert result.stats["extraction"]["parse_rate"] == 1.0
    assert settings.extractions_path.exists()
    assert len(ExtractionStore(settings.extractions_path)) == 1


@pytest.mark.asyncio
async def test_extraction_is_not_repeated_on_a_second_pipeline_run(settings, cache, monkeypatch):
    monkeypatch.setattr(
        "rla.pipeline.acquisition.build_sources", lambda *a, **k: {"fake": _OnePaperSource()}
    )
    from rla.pipeline.orchestrator import Pipeline

    first = PipelineLLM()
    async for _ in Pipeline(settings, first, cache, CostTracker()).run("graph agents"):
        pass
    assert len(first.calls) == 2  # one query expansion, one extraction

    second = PipelineLLM()
    events = [
        evt async for evt in Pipeline(settings, second, cache, CostTracker()).run("graph agents")
    ]

    assert len(second.calls) == 1  # expansion only; extraction came from the store
    assert any(e.payload.get("reused") == 1 for e in events)
