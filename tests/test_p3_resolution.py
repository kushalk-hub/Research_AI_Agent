"""P3 gate: acronym and alias pairs collapse to one node, over-merges do not, and
every decision carries its evidence."""

from __future__ import annotations

import json
import math

from rla.events import PIPELINE_PHASES as PHASE_ORDER
from rla.events import Phase
from rla.llm.base import LLMError
from rla.models import Concept, ConceptMention, Extraction
from rla.pipeline.resolve import (
    AUTO_MERGE,
    EMBEDDING_THRESHOLDS,
    MAX_JUDGE_CALLS,
    MAYBE_MERGE,
    STAGE,
    MergeDecision,
    MergeThresholds,
    collect_mentions,
    normalise_name,
    resolve_concepts,
    thresholds_for,
)
from rla.store.cache import CostTracker


def vec(degrees: float) -> list[float]:
    """Unit vector at `degrees`, so `cosine` between two of them is the cosine of
    the angle between them. Keeps expected similarities exact and legible."""
    radians = math.radians(degrees)
    return [round(math.cos(radians), 4), round(math.sin(radians), 4)]


class FakeEmbedder:
    """Duck-typed `Embedder`: one vector per text, from a dict or a callable."""

    def __init__(self, vectors: dict[str, list[float]] | None = None, fn=None) -> None:
        self.vectors = vectors or {}
        self.fn = fn
        self.texts: list[str] = []

    async def embed_many(self, texts):
        self.texts.extend(texts)
        return [self.vectors.get(t) or self.fn(t) for t in texts]

    @property
    def call_count(self) -> int:
        return len(self.texts)


class FakeJudge:
    """Answers the CONCEPT_RESOLUTION prompt from a lookup keyed by (A, B)."""

    def __init__(self, verdicts: dict[tuple[str, str], str], fail: bool = False) -> None:
        self.verdicts = verdicts
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def generate_structured(self, prompt, schema, **kwargs):
        await _tick()
        a = _after(prompt, "Concept A: ")
        b = _after(prompt, "Concept B: ")
        self.calls.append((a, b))
        if self.fail:
            raise LLMError("503 model overloaded")
        verdict = self.verdicts.get((a, b), "different")
        return schema.model_validate(
            {"verdict": verdict, "confidence": 0.9, "canonical": a if verdict == "same" else ""}
        )


async def _tick() -> None:
    import asyncio

    await asyncio.sleep(0)


def _after(text: str, marker: str) -> str:
    tail = text.split(marker, 1)[1]
    return tail.splitlines()[0].strip()


def extraction(paper_id: str, *names: str, description: str = "") -> Extraction:
    return Extraction(
        paper_id=paper_id,
        paper_hash=f"hash-{paper_id}",
        summary="s",
        concepts=[ConceptMention(name=name, description=description) for name in names],
    )


async def drain(extractions, **kwargs) -> tuple[list, list, list]:
    events = [evt async for evt in resolve_concepts(extractions, **kwargs)]
    final = events[-1]
    return events, final.payload["concept_nodes"], final.payload["decisions"]


def names_of(nodes: list[dict]) -> set[str]:
    return {node["name"] for node in nodes}


def node_named(nodes: list[dict], name: str) -> dict:
    return next(node for node in nodes if node["name"] == name)


# -- Tier 1: normalised name, no model required ---------------------------------


def test_normalise_folds_case_punctuation_and_spacing():
    assert normalise_name("Graph Attention Networks") == normalise_name("graph attention networks")
    assert normalise_name("GAT") == normalise_name("G.A.T.")
    assert normalise_name("  node   classification ") == "node classification"


def test_it_does_not_expand_acronyms_because_that_is_a_judgement():
    # The dangerous mistake: string-expanding GAT into the long form would claim
    # identity without ever asking anyone.
    assert normalise_name("GAT") != normalise_name("graph attention networks")


async def test_the_same_name_in_two_spellings_merges_with_no_model_at_all():
    events, nodes, _ = await drain(
        [
            extraction("p1", "Graph Attention Networks"),
            extraction("p2", "graph attention networks"),
        ],
        llm=None,
        embedder=None,
    )

    assert len(nodes) == 1
    assert nodes[0]["paper_ids"] == ["p1", "p2"]
    assert sorted(nodes[0]["aliases"]) == ["Graph Attention Networks", "graph attention networks"]
    assert any("normalised name only" in evt.message for evt in events)


async def test_a_corpus_with_no_concepts_resolves_to_nothing():
    _, nodes, decisions = await drain([])
    assert nodes == []
    assert decisions == []


# -- Tier 2: decisively similar pairs skip the model ---------------------------


async def test_a_decisively_similar_pair_merges_without_spending_a_judge_call():
    judge = FakeJudge({})
    embedder = FakeEmbedder({"attention mechanism": vec(0), "attention mechanisms": vec(2)})

    _, nodes, decisions = await drain(
        [extraction("p1", "attention mechanism"), extraction("p2", "attention mechanisms")],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 1
    assert judge.calls == []
    assert [d["reason"] for d in decisions] == ["auto-similarity"]
    assert f">= {AUTO_MERGE}" in decisions[0]["evidence"]


async def test_a_pair_below_the_similarity_band_is_never_considered_at_all():
    judge = FakeJudge({})
    embedder = FakeEmbedder({"graph attention networks": vec(0), "node classification": vec(90)})

    _, nodes, decisions = await drain(
        [extraction("p1", "graph attention networks"), extraction("p2", "node classification")],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 2
    assert judge.calls == []
    assert decisions == []


# -- Tier 3: the borderline band is the only thing that spends a call -----------


async def test_the_gate_pair_an_acronym_and_its_long_form_become_one_node():
    """PLAN.md P3: "GAT" and "graph attention networks" must resolve to one node."""
    judge = FakeJudge({("GAT", "graph attention networks"): "same"})
    embedder = FakeEmbedder(
        {
            "GAT": vec(0),
            "graph attention networks": vec(32),  # cos 0.848 -> borderline
            "inductive bias": vec(180),  # orthogonal, never a candidate
        }
    )

    _, nodes, decisions = await drain(
        [
            extraction("p1", "GAT"),
            extraction("p2", "graph attention networks"),
            extraction("p3", "inductive bias"),
        ],
        llm=judge,
        embedder=embedder,
    )

    gat = node_named(nodes, "GAT")
    assert gat["paper_ids"] == ["p1", "p2"]
    assert "graph attention networks" in gat["aliases"]
    assert len(judge.calls) == 1
    assert decisions[0]["verdict"] == "same"
    assert decisions[0]["canonical"] == "GAT"


async def test_a_method_and_the_task_it_serves_are_kept_apart():
    """The classic over-merge: GCN and GAT sound alike and are both "graph NNs"."""
    judge = FakeJudge({("graph convolutional networks", "graph attention networks"): "different"})
    embedder = FakeEmbedder(
        {
            "graph convolutional networks": vec(0),
            "graph attention networks": vec(30),
        }
    )

    _, nodes, decisions = await drain(
        [
            extraction("p1", "graph convolutional networks"),
            extraction("p2", "graph attention networks"),
        ],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 2
    assert decisions[0]["verdict"] == "different"


async def test_a_method_and_the_task_it_is_applied_to_are_kept_apart():
    judge = FakeJudge({("graph attention networks", "node classification"): "different"})
    embedder = FakeEmbedder({"graph attention networks": vec(0), "node classification": vec(28)})

    _, nodes, _ = await drain(
        [
            extraction("p1", "graph attention networks"),
            extraction("p2", "node classification"),
        ],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 2


async def test_a_failing_judge_never_merges():
    judge = FakeJudge({}, fail=True)
    embedder = FakeEmbedder({"GAT": vec(0), "graph attention networks": vec(30)})

    _, nodes, decisions = await drain(
        [extraction("p1", "GAT"), extraction("p2", "graph attention networks")],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 2
    assert decisions[0]["reason"] == "judge-failed"
    assert "overloaded" in decisions[0]["evidence"]


async def test_merging_is_transitive_across_a_chain_of_pairs():
    judge = FakeJudge(
        {
            ("graph attention networks", "GAT"): "same",
            ("GAT", "graph attention net"): "same",
        }
    )
    embedder = FakeEmbedder(
        {
            "graph attention networks": vec(0),
            "GAT": vec(32),  # 32 deg from each neighbour
            "graph attention net": vec(64),  # 64 deg from the first: below the band
        }
    )

    _, nodes, _ = await drain(
        [
            extraction("p1", "graph attention networks"),
            extraction("p2", "GAT"),
            extraction("p3", "graph attention net"),
        ],
        llm=judge,
        embedder=embedder,
    )

    assert len(nodes) == 1
    assert sorted(nodes[0]["aliases"]) == ["GAT", "graph attention net", "graph attention networks"]
    assert nodes[0]["paper_ids"] == ["p1", "p2", "p3"]


async def test_the_judge_budget_is_bounded_and_the_cutoff_is_reported():
    # Auto-merge is free, so it must not be what stops the run: push its threshold
    # out of reach to isolate the judge budget as the only limiter. Thresholds now
    # travel explicitly per embedding space (P12 Task 9), so the override is passed
    # as a parameter rather than monkeypatched onto the module.
    out_of_reach = MergeThresholds(auto=1.1, maybe=MAYBE_MERGE, calibrated=True)
    names = [f"concept {i}" for i in range(45)]
    judge = FakeJudge(
        {(names[i], names[j]): "different" for i in range(45) for j in range(i + 1, 45)}
    )
    # 1 degree apart over a 44 degree spread: every pair lands inside the band.
    embedder = FakeEmbedder(fn=lambda text: vec(float(text.split()[1]) * 1.0))
    extractions = [extraction(f"p{i}", name) for i, name in enumerate(names)]

    events, nodes, decisions = await drain(
        extractions, llm=judge, embedder=embedder, thresholds=out_of_reach
    )

    assert len(judge.calls) == MAX_JUDGE_CALLS
    assert len(decisions) == MAX_JUDGE_CALLS
    assert len(nodes) == 45  # nothing merged, nothing silently dropped
    assert any("judge budget reached" in evt.message for evt in events)


async def test_the_budget_does_not_block_free_auto_merges(monkeypatch):
    """Only model calls are rationed; the costless tier still runs in full."""
    monkeypatch.setattr("rla.pipeline.resolve.MAX_JUDGE_CALLS", 0)
    embedder = FakeEmbedder({"attention mechanism": vec(0), "attention mechanisms": vec(2)})

    _, nodes, decisions = await drain(
        [extraction("p1", "attention mechanism"), extraction("p2", "attention mechanisms")],
        llm=FakeJudge({}),
        embedder=embedder,
    )

    assert len(nodes) == 1
    assert [d["reason"] for d in decisions] == ["auto-similarity"]


# -- Evidence and bookkeeping --------------------------------------------------


async def test_every_decision_records_its_evidence_merges_and_refusals_alike():
    judge = FakeJudge(
        {
            ("GAT", "graph attention networks"): "same",
            ("graph attention networks", "graph convolutional networks"): "different",
        }
    )
    # 32 degrees apart, so both candidate pairs land in the borderline band and
    # the first-to-third pair is too far apart to matter.
    embedder = FakeEmbedder(
        {
            "GAT": vec(0),
            "graph attention networks": vec(32),
            "graph convolutional networks": vec(64),
        }
    )

    _, nodes, decisions = await drain(
        [
            extraction("p1", "GAT"),
            extraction("p2", "graph attention networks"),
            extraction("p3", "graph convolutional networks"),
        ],
        llm=judge,
        embedder=embedder,
    )

    # Pair order follows similarity, so index by pair rather than by position.
    by_pair = {(d["kept"], d["merged"]): d for d in decisions}
    assert by_pair[("GAT", "graph attention networks")]["verdict"] == "same"
    assert by_pair[("graph attention networks", "graph convolutional networks")]["verdict"] == (
        "different"
    )
    for decision in decisions:
        assert decision["evidence"]
        assert decision["reason"]
        assert decision["kept"] and decision["merged"]
    assert len(nodes) == 2


async def test_the_dominant_spelling_wins_and_the_others_become_aliases():
    _, nodes, _ = await drain(
        [
            extraction("p1", "Graph Attention Network"),
            extraction("p2", "graph attention network"),
            extraction("p3", "graph attention network"),
        ]
    )

    assert nodes[0]["name"] == "graph attention network"
    assert set(nodes[0]["aliases"]) == {"Graph Attention Network", "graph attention network"}


async def test_years_come_from_the_corpus_so_first_seen_is_real():
    extractions = [
        extraction("p-old", "attention"),
        extraction("p-new", "Attention"),
    ]

    _, nodes, _ = await drain(extractions, paper_years={"p-old": 2015, "p-new": 2021})

    assert nodes[0]["first_seen_year"] == 2015
    assert nodes[0]["id"] == "concept:attention"


async def test_a_paper_mentioned_twice_is_listed_once():
    _, nodes, _ = await drain([extraction("p1", "attention", "attention")])
    assert nodes[0]["paper_ids"] == ["p1"]


async def test_blank_mentions_never_become_nodes():
    assert collect_mentions([extraction("p1", "  ", "")]) == []


async def test_the_cost_of_the_judge_calls_is_reported():
    tracker = CostTracker()
    judge = FakeJudge({("GAT", "graph attention networks"): "same"})
    embedder = FakeEmbedder({"GAT": vec(0), "graph attention networks": vec(30)})
    tracker.record(STAGE, input_tokens=200, output_tokens=20)

    events, _, _ = await drain(
        [extraction("p1", "GAT"), extraction("p2", "graph attention networks")],
        llm=judge,
        embedder=embedder,
        tracker=tracker,
        model="gemini-2.5-flash",
    )

    cost = events[-1].payload["cost"]
    assert cost["input_tokens"] == 200
    assert cost["output_tokens"] == 20
    assert cost["calls"] >= 1
    # A priced model yields a real figure...
    assert cost["estimated_usd"] is not None
    assert cost["cost_status"] == "ok"


async def test_an_unpriced_judge_model_reports_unknown_rather_than_free():
    """The judge stage must not invent a cost for a model it cannot price.

    The audit found the reported cost was a lower bound in two ways at once: the
    configured model never reached the provider, and unknown usage rendered as
    zero. Here the model is deliberately unpriced, so the honest report is
    `None` plus a reason, not a confident $0.00.
    """
    tracker = CostTracker()
    judge = FakeJudge({("GAT", "graph attention networks"): "same"})
    embedder = FakeEmbedder({"GAT": vec(0), "graph attention networks": vec(30)})
    tracker.record(STAGE, input_tokens=200, output_tokens=20)

    events, _, _ = await drain(
        [extraction("p1", "GAT"), extraction("p2", "graph attention networks")],
        llm=judge,
        embedder=embedder,
        tracker=tracker,
        model="a-model-this-build-cannot-price",
    )

    cost = events[-1].payload["cost"]
    assert cost["calls"] >= 1
    assert cost["input_tokens"] == 200  # tokens are still attributed
    assert cost["estimated_usd"] is None
    assert cost["cost_status"] == "unpriced_model"


async def test_a_failing_embedder_degrades_to_name_only_rather_than_crashing():
    class BrokenEmbedder:
        async def embed_many(self, texts):
            raise LLMError("embedding failed: quota exceeded")

    events, nodes, _ = await drain(
        [extraction("p1", "GAT"), extraction("p2", "graph attention networks")],
        llm=None,
        embedder=BrokenEmbedder(),
    )

    assert len(nodes) == 2  # GAT is not string-identical, so it stays separate
    assert any("embedding failed" in evt.message for evt in events)


# -- Orchestrator wiring -------------------------------------------------------


async def test_resolve_runs_after_extract_and_persists_concepts(settings, cache, monkeypatch):
    monkeypatch.setattr("rla.pipeline.acquisition.build_sources", lambda *a, **k: {})
    from rla.pipeline.orchestrator import IMPLEMENTED_PHASES, Pipeline, PipelineResult

    # Keep it offline: with a key set, resolution would try to embed for real.
    settings.gemini_api_key = ""
    settings.extractions_path.parent.mkdir(parents=True, exist_ok=True)
    settings.extractions_path.write_text(
        extraction("p1", "GAT").model_dump_json()
        + "\n"
        + extraction("p2", "graph attention networks").model_dump_json()
        + "\n",
        "utf-8",
    )

    assert Phase.RESOLVE in IMPLEMENTED_PHASES
    result = PipelineResult()
    events = [
        evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("t", result=result)
    ]

    phases = [evt.phase for evt in events]
    assert phases == sorted(phases, key=lambda p: list(PHASE_ORDER).index(p))
    assert result.resolution["concepts"] == 2

    saved = json.loads(settings.concepts_path.read_text("utf-8"))
    # Round-trips through the real model, so the file is a valid artifact.
    assert {Concept.model_validate(c).name for c in saved["concepts"]} == {
        "GAT",
        "graph attention networks",
    }


async def test_resolve_reports_pending_when_extraction_has_not_run(settings, cache, monkeypatch):
    monkeypatch.setattr("rla.pipeline.acquisition.build_sources", lambda *a, **k: {})
    from rla.pipeline.orchestrator import Pipeline

    events = [evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("t")]

    resolve_events = [evt for evt in events if evt.phase is Phase.RESOLVE]
    assert resolve_events
    assert resolve_events[0].kind == "pending"
    assert "no extractions" in resolve_events[0].message


# ---------------------------------------------------------------------------
# P12: thresholds belong to an embedding space, not to the project
# ---------------------------------------------------------------------------


def test_the_gemini_thresholds_are_unchanged():
    """0.92 / 0.70 were calibrated on Gemini's embedding space; they must not move."""
    assert AUTO_MERGE == 0.92
    assert MAYBE_MERGE == 0.70
    calibrated = thresholds_for("gemini/gemini-embedding-001")
    assert calibrated.auto == 0.92
    assert calibrated.maybe == 0.70
    assert calibrated.calibrated is True


def test_thresholds_are_keyed_by_canonical_id():
    """Two providers exposing the same bare model name must not collide."""
    assert "gemini/gemini-embedding-001" in EMBEDDING_THRESHOLDS


def test_an_unknown_embedding_space_is_uncalibrated_and_disables_auto_merge():
    uncalibrated = thresholds_for("ollama/nomic-embed-text")
    assert uncalibrated.auto is None
    assert uncalibrated.calibrated is False
    # The judge floor still exists, so candidates are still surfaced.
    assert uncalibrated.maybe > 0


async def test_an_uncalibrated_space_performs_zero_auto_merges():
    """The safety property: more duplicates, never a fused lineage path."""
    extractions = [
        extraction(
            "p1", "Graph Attention Networks", description="attention over a neighbourhood"
        ),
        extraction(
            "p2", "graph attention networks", description="attention over a neighbourhood"
        ),
        extraction("p3", "Deep Reinforcement Learning", description="policies from rewards"),
    ]

    class PerfectEmbedder:
        model_id = "ollama/nomic-embed-text"

        def __init__(self):
            self.dimensions = 3

        async def embed_many(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    decisions: list[MergeDecision] = []
    async for evt in resolve_concepts(
        extractions,
        llm=AlwaysSame(),
        embedder=PerfectEmbedder(),
        concurrency=1,
        thresholds=thresholds_for("ollama/nomic-embed-text"),
    ):
        if "decisions" in evt.payload:
            decisions = [MergeDecision(**d) for d in evt.payload["decisions"]]

    auto = [d for d in decisions if d.reason == "auto-similarity"]
    assert not auto, f"auto-merge must be off for an uncalibrated space: {auto}"
    assert EMBEDDING_THRESHOLDS["gemini/gemini-embedding-001"].auto == 0.92


async def test_the_judge_stays_within_its_budget_for_an_uncalibrated_space():
    calls = 0

    class Counting:
        async def generate_structured(
            self, prompt, schema, *, model=None, temperature=0.0, stage="llm", retries=2
        ):
            nonlocal calls
            calls += 1
            return schema.model_construct(verdict="different", confidence=0.5, canonical="")

    vectors = [[1.0, i / 100.0, 0.0] for i in range(20)]
    extractions = [extraction(f"p{i}", f"concept {i}") for i in range(20)]

    async for _ in resolve_concepts(
        extractions,
        llm=Counting(),
        embedder=VectorEmbedder(vectors),
        concurrency=1,
        thresholds=thresholds_for("ollama/nomic-embed-text"),
    ):
        pass

    assert calls <= MAX_JUDGE_CALLS


class AlwaysSame:
    async def generate_structured(
        self, prompt, schema, *, model=None, temperature=0.0, stage="llm", retries=2
    ):
        return schema.model_construct(verdict="different", confidence=0.5, canonical="")


class VectorEmbedder:
    model_id = "ollama/nomic-embed-text"

    def __init__(self, vectors):
        self.vectors = vectors
        self.dimensions = len(vectors[0])

    async def embed_many(self, texts):
        return self.vectors[: len(texts)]
