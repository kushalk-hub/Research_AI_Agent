from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from fods.models import Task, TaskPlan, TaskState
from fods.runtime import run_plan
from fods.tools import (
    DiscoverReferencesArgs,
    EnrichedConcept,
    EnrichmentBatchOutput,
    EvidenceFact,
    ExtractionBatchArgs,
    PaperEnrichment,
    SaveReferenceContextArgs,
    ToolContext,
    create_registry,
    read_context_snapshot,
)
from rla.models import Paper, content_hash


class _StructuredModel:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate_structured(self, *_args, **_kwargs):
        self.calls += 1
        return self.response


def _case(tmp_path, *, valid_excerpt: bool):
    paper = Paper(
        id="paper-1",
        title="Graph attention",
        year=2022,
        abstract="We introduce graph attention for neighborhood aggregation.",
    )
    excerpt = (
        "We introduce graph attention"
        if valid_excerpt
        else "The authors report a different unsupported claim"
    )
    result = EnrichmentBatchOutput(
        items=[
            PaperEnrichment(
                paper_id=paper.id,
                paper_hash=paper.ensure_hash(),
                concepts=[
                    EnrichedConcept(
                        text="graph attention", role="introduces", evidence_excerpt=excerpt
                    )
                ],
                methods=[EvidenceFact(text="neighborhood aggregation", evidence_excerpt=excerpt)],
                findings=[],
                limitations=[],
                relations=[],
            )
        ]
    )
    context = {
        "snapshot_reused": True,
        "context_hash": "a" * 32,
        "papers": [paper.model_dump(mode="json")],
    }
    model = _StructuredModel(result)
    ctx = ToolContext(
        run_id="enrich-test",
        mode="live",
        topic="Graph attention",
        question="Extract supported concepts",
        output_path="enrichment.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        llm=model,
        dependency_results={"load": context},
        metadata={"enrichment_model": "ollama/qwen3:4b"},
    )
    return ctx, model


async def test_validated_enrichment_cache_is_reused_for_identical_inputs(tmp_path):
    ctx, model = _case(tmp_path, valid_excerpt=True)
    tool = create_registry({}).get("extract_enrichment_batch")
    args = ExtractionBatchArgs(paper_ids=["paper-1"])

    first = await tool.handler(ctx, args)
    second = await tool.handler(ctx, args)

    assert first["cache_reused"] is False
    assert second["cache_reused"] is True
    assert model.calls == 1
    cache_files = list((ctx.data_dir / "fods" / "enrichment_cache").glob("*.json"))
    assert len(cache_files) == 1
    cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cached["input_hashes"]["paper-1"] == first["input_hashes"]["paper-1"]


async def test_unsupported_evidence_is_rejected_before_cache_write(tmp_path):
    ctx, _model = _case(tmp_path, valid_excerpt=False)
    tool = create_registry({}).get("extract_enrichment_batch")

    with pytest.raises(ValueError, match="exact evidence excerpt"):
        await tool.handler(ctx, ExtractionBatchArgs(paper_ids=["paper-1"]))

    cache_dir = ctx.data_dir / "fods" / "enrichment_cache"
    assert not cache_dir.exists() or not list(cache_dir.glob("*.json"))


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("wrong_id", "unknown paper IDs"),
        ("wrong_hash", "paper hash mismatch"),
        ("dangling_relation", "relation endpoint"),
        ("malformed_schema", "extra_forbidden"),
    ],
)
async def test_invalid_structured_outputs_are_rejected_without_cache(
    tmp_path, failure, expected_message
):
    ctx, model = _case(tmp_path, valid_excerpt=True)
    original = model.response.items[0]
    if failure == "wrong_id":
        item = original.model_copy(update={"paper_id": "outside-batch"})
        model.response = EnrichmentBatchOutput(items=[item])
    elif failure == "wrong_hash":
        item = original.model_copy(update={"paper_hash": "0" * 64})
        model.response = EnrichmentBatchOutput(items=[item])
    elif failure == "dangling_relation":
        relation = {
            "source_term": "graph attention",
            "target_term": "unknown concept",
            "relation_type": "extends",
            "evidence_excerpt": "We introduce graph attention",
        }
        data = original.model_dump(mode="json")
        data["relations"] = [relation]
        item = PaperEnrichment.model_validate(data)
        model.response = EnrichmentBatchOutput(items=[item])
    else:
        model.response = {"items": [{"paper_id": "paper-1", "unknown": "field"}]}
    tool = create_registry({}).get("extract_enrichment_batch")

    with pytest.raises(Exception, match=expected_message):
        await tool.handler(ctx, ExtractionBatchArgs(paper_ids=["paper-1"]))

    cache_dir = ctx.data_dir / "fods" / "enrichment_cache"
    assert not cache_dir.exists() or not list(cache_dir.glob("*.json"))


async def test_poisoned_cache_entry_is_recomputed_then_compatible_result_resumes(tmp_path):
    ctx, model = _case(tmp_path, valid_excerpt=True)
    tool = create_registry({}).get("extract_enrichment_batch")
    args = ExtractionBatchArgs(paper_ids=["paper-1"])
    first = await tool.handler(ctx, args)
    cache_path = next((ctx.data_dir / "fods" / "enrichment_cache").glob("*.json"))
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    cached["output"]["items"][0]["paper_hash"] = "0" * 64
    cache_path.write_text(json.dumps(cached), encoding="utf-8")

    regenerated = await tool.handler(ctx, args)
    resumed = await tool.handler(ctx, args)

    assert first["cache_reused"] is False
    assert regenerated["cache_reused"] is False
    assert resumed["cache_reused"] is True
    assert model.calls == 2


async def test_partial_batch_failure_keeps_successful_cache_for_resume(tmp_path):
    papers = [
        Paper(
            id=f"paper-{index}",
            title=f"Graph paper {index}",
            year=2022,
            abstract=f"This abstract supports graph method number {index}.",
        )
        for index in (1, 2)
    ]
    context = {
        "schema_version": 2,
        "topic": "Graph attention",
        "papers": [paper.model_dump(mode="json") for paper in papers],
    }
    context["context_hash"] = content_hash("Graph attention", json.dumps(context, sort_keys=True))
    topic_key = content_hash("Graph attention")[:16]
    context_root = tmp_path / "data" / "fods" / "topics"
    context_root.mkdir(parents=True)
    (context_root / f"{topic_key}.json").write_text(json.dumps(context), encoding="utf-8")

    class BatchModel:
        def __init__(self, fail_paper_2: bool):
            self.fail_paper_2 = fail_paper_2
            self.calls: list[str] = []

        async def generate_structured(self, prompt, _schema, **_kwargs):
            request = json.loads(prompt.split("Papers:\n", 1)[1])[0]
            paper_id = request["paper_id"]
            self.calls.append(paper_id)
            if self.fail_paper_2 and paper_id == "paper-2":
                return {"items": [{"paper_id": "malformed"}]}
            return EnrichmentBatchOutput(
                items=[
                    PaperEnrichment(
                        paper_id=paper_id,
                        paper_hash=request["paper_hash"],
                        concepts=[],
                        methods=[],
                        findings=[],
                        limitations=[],
                        relations=[],
                    )
                ]
            )

    plan = TaskPlan(
        request="Enrich two papers",
        topic="Graph attention",
        question="Extract supported concepts",
        output_path="enrichment.json",
        workflow="enrichment",
        tasks=[
            Task(id="load_context", tool="load_saved_context"),
            Task(
                id="batch_1",
                tool="extract_enrichment_batch",
                args={"paper_ids": ["paper-1"]},
                depends_on=["load_context"],
                priority=90,
            ),
            Task(
                id="batch_2",
                tool="extract_enrichment_batch",
                args={"paper_ids": ["paper-2"]},
                depends_on=["load_context"],
                priority=80,
            ),
            Task(
                id="save_enrichment",
                tool="save_enrichment",
                args={"output_path": "enrichment.json"},
                depends_on=["load_context", "batch_1", "batch_2"],
            ),
        ],
    )
    first_model = BatchModel(fail_paper_2=True)
    base = ToolContext(
        run_id="partial-enrichment-1",
        mode="live",
        topic="Graph attention",
        question="Extract supported concepts",
        output_path="enrichment.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        llm=first_model,
        metadata={
            "context_id": context["context_hash"],
            "enrichment_model": "ollama/qwen3:4b",
        },
    )
    registry = create_registry({})

    first = await run_plan(plan, registry, base, concurrency=1, max_attempts=1)

    assert not first.succeeded
    assert first.states["batch_1"].state is TaskState.COMPLETED
    assert first.states["batch_2"].state is TaskState.FAILED
    assert first.states["save_enrichment"].state is TaskState.BLOCKED
    assert first_model.calls == ["paper-1", "paper-2"]

    second_model = BatchModel(fail_paper_2=False)
    second = await run_plan(
        plan,
        registry,
        replace(base, run_id="partial-enrichment-2", llm=second_model),
        concurrency=1,
        max_attempts=1,
    )

    assert second.succeeded
    assert second_model.calls == ["paper-2"]
    assert second.states["save_enrichment"].result["papers_enriched"] == 2


async def test_reference_resolution_writes_reusable_child_snapshot(tmp_path):
    seed = Paper(
        id="seed",
        title="Seed paper",
        year=2021,
        external_ids={"s2": "seed-s2"},
        references=["target-s2"],
    )
    target = Paper(
        id="target",
        title="Referenced paper",
        year=2019,
        external_ids={"s2": "target-s2"},
    )
    saved_context = {
        "schema_version": 2,
        "topic": "Graph attention",
        "papers": [seed.model_dump(mode="json")],
    }
    saved_context["context_hash"] = content_hash(
        "Graph attention", json.dumps(saved_context, sort_keys=True)
    )
    context_root = tmp_path / "data" / "fods" / "topics"
    topic_key = content_hash("Graph attention")[:16]
    parent_path = context_root / topic_key / f"{saved_context['context_hash']}.json"
    parent_path.parent.mkdir(parents=True)
    parent_path.write_text(json.dumps(saved_context), encoding="utf-8")
    original_parent_bytes = parent_path.read_bytes()
    latest_path = context_root / f"{topic_key}.latest"
    latest_path.write_text(saved_context["context_hash"], encoding="utf-8")
    saved_context["snapshot_reused"] = True
    saved_context["snapshot_path"] = str(parent_path)

    async def resolve(_paper, _limit):
        return [target]

    registry = create_registry({}, reference_resolvers={"semantic_scholar": resolve})
    base = ToolContext(
        run_id="references-test",
        mode="live",
        topic="Graph attention",
        question="Resolve one-hop references",
        output_path="references.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        dependency_results={"load": saved_context},
    )
    lookup = await registry.get("discover_references").handler(
        base,
        DiscoverReferencesArgs(
            seed_paper_id="seed", resolver_source="semantic_scholar", max_candidates=5
        ),
    )
    assert lookup["status"] == "resolved"
    assert lookup["papers"][0]["native_reference_observed"] is True

    save_ctx = replace(
        base,
        dependency_results={"load": saved_context, "reference": lookup},
    )
    saved = await registry.get("save_reference_context").handler(
        save_ctx, SaveReferenceContextArgs(output_path="references.json")
    )
    child = read_context_snapshot(base.data_dir, base.topic, saved["context_id"])

    assert child["parent_context_id"] == saved_context["context_hash"]
    assert parent_path.read_bytes() == original_parent_bytes
    assert [paper["id"] for paper in child["discovered_papers"]] == ["target"]
    assert child["reference_discovery"]["source_edges"][0]["edge_type"] == (
        "SOURCE_CITATION_REFERENCE"
    )


async def test_reference_timeout_fails_bounded_without_writing_snapshot(tmp_path):
    seed = Paper(
        id="seed",
        title="Seed paper",
        year=2021,
        external_ids={"s2": "seed-s2"},
        references=["target-s2"],
    )
    context = {
        "snapshot_reused": True,
        "context_hash": "c" * 32,
        "papers": [seed.model_dump(mode="json")],
    }

    async def slow_resolve(_paper, _limit):
        await asyncio.sleep(1)
        return []

    registry = create_registry({}, reference_resolvers={"semantic_scholar": slow_resolve})
    ctx = ToolContext(
        run_id="timeout-test",
        mode="live",
        topic="Graph attention",
        question="Resolve one-hop references",
        output_path="references.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        dependency_results={"load": context},
        metadata={"reference_timeout_seconds": 0.01},
    )

    from fods.runtime import RetryableToolError

    with pytest.raises(RetryableToolError, match="semantic_scholar references"):
        await registry.get("discover_references").handler(
            ctx,
            DiscoverReferencesArgs(
                seed_paper_id="seed", resolver_source="semantic_scholar", max_candidates=5
            ),
        )

    assert not (ctx.data_dir / "fods" / "topics").exists()


async def test_malformed_reference_record_fails_without_writing_snapshot(tmp_path):
    seed = Paper(
        id="seed",
        title="Seed paper",
        year=2021,
        external_ids={"s2": "seed-s2"},
    )
    context = {
        "snapshot_reused": True,
        "context_hash": "e" * 32,
        "papers": [seed.model_dump(mode="json")],
    }

    async def malformed_resolver(_paper, _limit):
        return [{"title": "missing required paper fields"}]

    registry = create_registry({}, reference_resolvers={"semantic_scholar": malformed_resolver})
    ctx = ToolContext(
        run_id="malformed-reference-test",
        mode="live",
        topic="Graph attention",
        question="Resolve one-hop references",
        output_path="references.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        dependency_results={"load": context},
    )

    with pytest.raises(ValueError, match="malformed paper record"):
        await registry.get("discover_references").handler(
            ctx,
            DiscoverReferencesArgs(
                seed_paper_id="seed", resolver_source="semantic_scholar", max_candidates=5
            ),
        )

    assert not (ctx.data_dir / "fods" / "topics").exists()


def test_legacy_context_is_reused_only_for_its_verified_snapshot_id(tmp_path):
    context = {
        "schema_version": 2,
        "topic": "Graph attention",
        "papers": [Paper(id="p1", title="Paper").model_dump(mode="json")],
    }
    context["context_hash"] = content_hash("Graph attention", json.dumps(context, sort_keys=True))
    topic_key = content_hash("Graph attention")[:16]
    root = tmp_path / "fods" / "topics"
    root.mkdir(parents=True)
    (root / f"{topic_key}.json").write_text(json.dumps(context), encoding="utf-8")

    loaded = read_context_snapshot(tmp_path, "Graph attention", context["context_hash"])
    assert loaded["context_hash"] == context["context_hash"]
    assert loaded["snapshot_reused"] is True
    with pytest.raises(ValueError, match="does not match the requested"):
        read_context_snapshot(tmp_path, "Graph attention", "f" * 32)


async def test_conflicting_strong_identifiers_are_preserved_as_ambiguous(tmp_path):
    seed = Paper(
        id="seed",
        title="Seed paper",
        year=2021,
        external_ids={"openalex": "W-seed"},
    )
    existing = Paper(
        id="existing",
        title="Same title",
        year=2020,
        doi="10.1234/old",
        external_ids={"openalex": "W-old"},
    )
    candidate = Paper(
        id="candidate",
        title="Same title",
        year=2020,
        doi="10.1234/new",
        external_ids={"openalex": "W-new"},
    )
    context = {
        "snapshot_reused": True,
        "context_hash": "d" * 32,
        "papers": [seed.model_dump(mode="json"), existing.model_dump(mode="json")],
    }

    async def resolve(_paper, _limit):
        return [candidate]

    registry = create_registry({}, reference_resolvers={"openalex": resolve})
    base = ToolContext(
        run_id="ambiguous-test",
        mode="live",
        topic="Graph attention",
        question="Resolve one-hop references",
        output_path="references.json",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        dependency_results={"load": context},
    )
    lookup = await registry.get("discover_references").handler(
        base,
        DiscoverReferencesArgs(seed_paper_id="seed", resolver_source="openalex", max_candidates=5),
    )
    save_ctx = replace(base, dependency_results={"load": context, "reference": lookup})
    saved = await registry.get("save_reference_context").handler(
        save_ctx, SaveReferenceContextArgs(output_path="references.json")
    )

    assert saved["records"][0]["status"] == "ambiguous"
    assert saved["records"][0]["referenced_paper_id"] == "candidate"
    child = read_context_snapshot(base.data_dir, base.topic, saved["context_id"])
    assert [paper["id"] for paper in child["discovered_papers"]] == ["candidate"]
