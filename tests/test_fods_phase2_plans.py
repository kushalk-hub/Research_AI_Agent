from __future__ import annotations

import pytest

from fods.models import Task, TaskPlan
from fods.plan import PlanError, validate_plan
from fods.tools import create_registry


def _context_load(topic: str = "Graph Attention Networks") -> Task:
    return Task(id="load", tool="load_saved_context")


def test_enrichment_plan_requires_each_batch_to_depend_on_context():
    plan = TaskPlan(
        request="Enrich a saved context",
        topic="Graph Attention Networks",
        question="Extract methods and findings",
        output_path="data/fods/enrichments/example.json",
        workflow="enrichment",
        tasks=[
            _context_load(),
            Task(id="batch", tool="extract_enrichment_batch", args={"paper_ids": ["p1"]}),
            Task(
                id="save",
                tool="save_enrichment",
                args={"output_path": "data/fods/enrichments/example.json"},
                depends_on=["load", "batch"],
            ),
        ],
    )
    registry = create_registry({})
    with pytest.raises(PlanError, match="depend directly"):
        validate_plan(plan, registry.schemas())


def test_zero_hop_reference_plan_is_a_valid_copy_snapshot():
    path = "data/fods/topics/topic/new-snapshot.json"
    plan = TaskPlan(
        request="Copy a context without reference expansion",
        topic="Graph Attention Networks",
        question="No expansion",
        output_path=path,
        workflow="reference_discovery",
        tasks=[
            Task(id="load", tool="load_saved_context"),
            Task(
                id="save",
                tool="save_reference_context",
                args={"output_path": path},
                depends_on=["load"],
            ),
        ],
    )
    assert validate_plan(plan, create_registry({}).schemas()) == [["load"], ["save"]]
