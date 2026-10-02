"""P12 Task 10: propose thresholds for an uncalibrated embedding space, never install them.

Same honesty rule the evaluation harness already follows: a number is only
reported when it was measured, and nothing is written without a human decision.
"""

from __future__ import annotations

import pytest

from rla.eval.merge_calibration import calibrate, suggest_thresholds
from rla.models import Extraction


def extractions(n: int = 12) -> list[Extraction]:
    return [
        Extraction(
            paper_id=f"p{i}",
            paper_hash=f"h{i}",
            concepts=[
                {"name": "Graph Attention Networks" if i % 2 == 0 else "Graph Attention Network",
                 "description": "attention over a node neighbourhood",
                 "role": "introduces"},
                {"name": f"Unrelated Concept {i}", "description": "something else entirely",
                 "role": "uses"},
            ],
        )
        for i in range(n)
    ]


class PerfectEmbedder:
    model_id = "ollama/nomic-embed-text"

    def __init__(self):
        self.dimensions = 2

    def key(self, text: str) -> str:
        return f"{self.model_id}:{text}"

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts):
        # The two GAT spellings collapse; everything else is orthogonal.
        out = []
        for text in texts:
            if "ttention" in text:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


async def test_the_report_states_what_it_measured():
    report = await calibrate(extractions(), PerfectEmbedder())

    assert report.model_id == "ollama/nomic-embed-text"
    assert report.pairs_examined >= 1
    assert report.distribution, "a distribution is the evidence"
    assert report.calibrated is False, "nothing is calibrated until a human says so"


async def test_it_proposes_thresholds_and_labels_them_a_proposal():
    report = await calibrate(extractions(), PerfectEmbedder())
    assert report.proposed is not None
    assert 0.0 < report.proposed.auto < 1.0
    assert report.proposed.calibrated is False, "a proposal is never self-certified"


def test_a_proposal_is_refused_when_there_is_no_evidence():
    with pytest.raises(ValueError):
        suggest_thresholds([], false_merge_budget=0.02)


def test_a_proposal_is_withheld_when_the_evidence_is_thin():
    """Fewer than 20 pairs is not a distribution: withhold, do not invent."""
    assert suggest_thresholds([(1.0, 3)], false_merge_budget=0.02) is None


async def test_calibration_never_writes_to_the_registry():
    from rla.pipeline.resolve import EMBEDDING_THRESHOLDS

    before = dict(EMBEDDING_THRESHOLDS)
    await calibrate(extractions(), PerfectEmbedder())
    assert EMBEDDING_THRESHOLDS == before, "installing a threshold is a human decision"


async def test_calibration_accepts_the_documented_budgets():
    report = await calibrate(
        extractions(), PerfectEmbedder(), false_merge_budget=0.02, judge_budget=40
    )
    assert report.false_merge_budget == 0.02
    assert report.proposed is not None
