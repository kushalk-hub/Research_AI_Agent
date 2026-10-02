"""Propose merge thresholds for an embedding space that has not been calibrated.

Reports the similarity distribution over the concepts actually in the corpus, then
proposes an automatic-merge boundary at a stated false-merge budget. It never
writes to `EMBEDDING_THRESHOLDS`: installing a threshold is a human decision,
because a wrong one silently fuses two concepts and deletes the lineage path
between them -- the most expensive error in the whole system.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rla.llm.embedding_base import EmbeddingProvider, cosine
from rla.models import Extraction
from rla.pipeline.resolve import MAYBE_MERGE, MergeThresholds, collect_mentions, group_by_name

#: A proposal drawn from fewer pairs than this is calibrated-looking and wrong,
#: so it is withheld rather than returned.
MIN_EVIDENCE_PAIRS = 20


@dataclass(slots=True)
class CalibrationReport:
    model_id: str
    mentions: int = 0
    names: int = 0
    pairs_examined: int = 0
    distribution: list[tuple[float, int]] = field(default_factory=list)
    proposed: MergeThresholds | None = None
    false_merge_budget: float = 0.0
    calibrated: bool = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "mentions": self.mentions,
            "names": self.names,
            "pairs_examined": self.pairs_examined,
            "distribution": [{"similarity": round(s, 4), "count": c} for s, c in self.distribution],
            "proposed": None
            if self.proposed is None
            else {"auto": self.proposed.auto, "maybe": self.proposed.maybe,
                  "calibrated": self.proposed.calibrated},
            "false_merge_budget": self.false_merge_budget,
            "calibrated": self.calibrated,
            "note": (
                "A proposal is evidence, not a decision. Nothing was written to "
                "EMBEDDING_THRESHOLDS; automatic merging stays disabled for this "
                "embedding model until a human installs a threshold."
            ),
        }

    def render(self) -> str:
        lines = [
            f"embedding model : {self.model_id}",
            f"mentions/names  : {self.mentions} / {self.names}",
            f"pairs examined  : {self.pairs_examined}",
            "",
            "similarity distribution:",
        ]
        lines += [f"  {s:.3f}  {'#' * min(c, 60)}  ({c})" for s, c in self.distribution]
        if self.proposed is None:
            lines += ["", "no threshold proposed: too few pairs to have evidence"]
        else:
            lines += [
                "",
                f"PROPOSED (not installed): auto >= {self.proposed.auto}, "
                f"judge floor {self.proposed.maybe}",
                f"budget: at most {self.false_merge_budget:.1%} false merges",
            ]
        lines += ["", self.to_dict()["note"]]
        return "\n".join(lines)


def suggest_thresholds(
    distribution: Sequence[tuple[float, int]], *, false_merge_budget: float = 0.02
) -> MergeThresholds | None:
    """The similarity boundary above which at most the budget would auto-merge.

    Walked from the most similar pairs down: the boundary sits where the pairs
    above it first exceed the budget. When even the most similar pairs alone
    exceed it, there is no room for a boundary inside any observed mode, so the
    proposal splits the two top modes instead of certifying a value where the
    evidence is densest. Returns None rather than a number when there is not
    enough evidence, because a threshold invented from a handful of pairs is
    worse than no threshold: it would be calibrated-looking and wrong.
    """
    total = sum(count for _, count in distribution)
    if total == 0:
        raise ValueError("cannot propose a threshold from an empty similarity distribution")
    if total < MIN_EVIDENCE_PAIRS:
        return None
    allowed = max(0, int(total * false_merge_budget))
    levels = sorted(distribution)
    above = 0
    for index in range(len(levels) - 1, -1, -1):
        similarity, count = levels[index]
        if above + count > allowed:
            if index == len(levels) - 1:
                if len(levels) < 2:
                    # Every pair sits at one similarity: no separation to bound.
                    return None
                midpoint = round((levels[-1][0] + levels[-2][0]) / 2, 4)
                return MergeThresholds(auto=midpoint, maybe=MAYBE_MERGE, calibrated=False)
            return MergeThresholds(auto=round(similarity, 4), maybe=MAYBE_MERGE, calibrated=False)
        above += count
    # The budget covers every pair: nothing to bound, so propose nothing rather
    # than a boundary that would merge the whole corpus by default.
    return None


async def calibrate(
    extractions: Sequence[Extraction],
    embedder: EmbeddingProvider,
    *,
    false_merge_budget: float = 0.02,
    judge_budget: int = 40,
) -> CalibrationReport:
    """Measure the similarity distribution and propose a boundary. Writes nothing.

    `judge_budget` is accepted so the call matches the documented interface; the
    pass performs no judge calls itself, it only proposes the boundary the
    resolver's bounded judge path would then be read against.
    """
    _ = judge_budget
    mentions = collect_mentions(extractions)
    clusters = group_by_name(mentions)
    report = CalibrationReport(
        model_id=embedder.model_id,
        mentions=len(mentions),
        names=len(clusters),
        false_merge_budget=false_merge_budget,
    )
    if len(clusters) < 2:
        return report

    vectors = await embedder.embed_many([g[0].centroid_text() for g in clusters])
    buckets: dict[int, int] = {}
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine(vectors[i], vectors[j])
            buckets[int(score * 20)] = buckets.get(int(score * 20), 0) + 1
            report.pairs_examined += 1

    report.distribution = [
        (bucket / 20.0, count) for bucket, count in sorted(buckets.items())
    ]
    report.proposed = suggest_thresholds(report.distribution, false_merge_budget=false_merge_budget)
    return report
