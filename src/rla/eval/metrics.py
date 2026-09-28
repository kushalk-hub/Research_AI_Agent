"""Precision/recall/F1 for the extracted graph against a reference set.

Three decisions worth stating up front, because each one changes the numbers:

Concept matching is by normalised name, never by id
    The pipeline mints ids like `concept:graph-attention-networks`; a labeler
    writes "Graph Attention Networks". Comparing ids would score the slugger, not
    the extractor. Names are lowercased, stripped of punctuation, and de-pluralised
    so "GATs" matches "GAT".

Edges are scored only when the nodes match
    A predicted edge between two concepts the reference never lists is not a
    "wrong edge", it is a set of two possibly-good nodes joined wrongly. Counting
    it as a false positive would penalise correct extraction for a bad join, so
    edges are matched within the intersection of matched nodes and the rest are
    reported separately as `edges_with_unmatched_endpoints`.

Paper-id and concept-id relations are scored apart
    `paper --INTRODUCES--> concept` and `concept --EXTENDS--> concept` fail for
    completely different reasons. One pooled precision figure hides which.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from rla.models import EdgeType

#: Relation types that connect a paper to a concept. Scored as a separate family.
PAPER_CONCEPT_TYPES = frozenset({EdgeType.INTRODUCES, EdgeType.USES})

_PLURAL_EXCEPTIONS = {"analysis", "basis", "bias", "data", "loss", "ssm", "gas"}


def normalise_concept(name: str) -> str:
    """Fold a concept name to its comparison key.

    Lowercased, accents stripped, punctuation to spaces, and a trailing plural
    `s` dropped. Deliberately conservative: over-normalising would merge distinct
    concepts and quietly inflate recall.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    words = text.split()
    if words:
        last = words[-1]
        if last.endswith("s") and not last.endswith("ss") and last not in _PLURAL_EXCEPTIONS:
            words[-1] = last[:-1]
    return " ".join(words)


@dataclass(frozen=True)
class EdgeKey:
    source: str
    target: str
    type: EdgeType

    def to_tuple(self) -> tuple[str, str, EdgeType]:
        return (self.source, self.target, self.type)


@dataclass
class ScoreSet:
    """Precision/recall/F1 over one family of items, with the counts behind it."""

    name: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    def __post_init__(self) -> None:
        if self.name == "":
            raise ValueError("a score set needs a name for the report to label it")

    @property
    def precision(self) -> float | None:
        """None, not 0.0, when nothing was predicted.

        An undefined precision is not a failure, and reporting it as 0% would
        understate a run that simply made no claims to check.
        """
        predicted = self.true_positives + self.false_positives
        if predicted == 0:
            return None
        return self.true_positives / predicted

    @property
    def recall(self) -> float | None:
        actual = self.true_positives + self.false_negatives
        if actual == 0:
            return None
        return self.true_positives / actual

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": _round(self.precision),
            "recall": _round(self.recall),
            "f1": _round(self.f1),
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def score_items(
    name: str,
    predicted: Iterable[str],
    actual: Iterable[str],
) -> ScoreSet:
    """Score one flat set of normalised keys."""
    pred = set(predicted)
    truth = set(actual)
    hits = len(pred & truth)
    return ScoreSet(
        name=name,
        true_positives=hits,
        false_positives=len(pred - truth),
        false_negatives=len(truth - pred),
    )


def match_nodes(
    predicted_names: Iterable[str],
    reference_names: Iterable[str],
) -> tuple[dict[str, str], set[str], set[str]]:
    """Match predicted concept names to reference names by normalised key.

    Returns `(pred_to_ref, unmatched_pred, unmatched_ref)`. A predicted name whose
    normalised key collides with several reference names is left unmatched rather
    than guessed: the collision is reported so a reader can see the reference set
    is ambiguous.
    """
    ref_by_key: dict[str, list[str]] = {}
    for name in reference_names:
        ref_by_key.setdefault(normalise_concept(name), []).append(name)

    matches: dict[str, str] = {}
    unmatched_pred: set[str] = set()
    for name in predicted_names:
        candidates = ref_by_key.get(normalise_concept(name), [])
        if len(candidates) == 1:
            matches[name] = candidates[0]
        else:
            unmatched_pred.add(name)

    matched_ref = set(matches.values())
    unmatched_ref = set(reference_names) - matched_ref
    return matches, unmatched_pred, unmatched_ref


def _is_paper_id(value: str, paper_ids: set[str]) -> bool:
    return value in paper_ids


def score_edges(
    name: str,
    predicted: Iterable[EdgeKey],
    reference: Iterable[EdgeKey],
    predicted_paper_ids: set[str] | None = None,
) -> tuple[ScoreSet, int]:
    """Score a family of edges, matching endpoints by node identity.

    For paper-to-concept edges the paper endpoint is an id and is compared
    literally. For concept-to-concept edges both endpoints are matched through
    `match_nodes` first, so a slug difference is not scored as a wrong edge.

    Also returns how many predicted edges had at least one endpoint that the
    reference set does not mention. Those are neither right nor wrong as edges,
    so they are reported rather than folded into the false-positive count.
    """
    pred = list(predicted)
    truth = list(reference)
    paper_ids = predicted_paper_ids or set()

    # Index reference concept names so concept endpoints can be normalised.
    ref_concepts: set[str] = set()
    for edge in truth:
        for endpoint in (edge.source, edge.target):
            if not _is_paper_id(endpoint, paper_ids):
                ref_concepts.add(endpoint)
    ref_paper_ids = {
        e.source for e in truth if _is_paper_id(e.source, paper_ids)
    } | {e.target for e in truth if _is_paper_id(e.target, paper_ids)}

    concept_matches, _, _ = match_nodes(
        [e.source for e in pred if not _is_paper_id(e.source, paper_ids)]
        + [e.target for e in pred if not _is_paper_id(e.target, paper_ids)],
        ref_concepts,
    )

    def canonical(edge: EdgeKey) -> EdgeKey | None:
        """Rewrite a predicted edge onto reference names, or give up."""
        source = (
            edge.source
            if _is_paper_id(edge.source, paper_ids) or edge.source in ref_paper_ids
            else concept_matches.get(edge.source)
        )
        target = (
            edge.target
            if _is_paper_id(edge.target, paper_ids) or edge.target in ref_paper_ids
            else concept_matches.get(edge.target)
        )
        if source is None or target is None:
            return None
        return EdgeKey(source, target, edge.type)

    canon_pred = set()
    unmatchable = 0
    for edge in pred:
        c = canonical(edge)
        if c is None:
            unmatchable += 1
        else:
            canon_pred.add(c)
    canon_truth = {e.to_tuple() for e in truth}
    hits = len(canon_pred & canon_truth)
    return (
        ScoreSet(
            name=name,
            true_positives=hits,
            false_positives=len(canon_pred - canon_truth),
            false_negatives=len(canon_truth - canon_pred),
        ),
        unmatchable,
    )


@dataclass
class ExtractionScores:
    """Everything measured about one extracted graph, plus what was not measured."""

    nodes: ScoreSet
    concept_edges: ScoreSet
    paper_concept_edges: ScoreSet
    #: Predicted edges whose endpoints are not in the reference set at all. Not
    #: counted as false positives, and not silently dropped either.
    edges_with_unmatched_endpoints: int = 0
    #: Why node/edge accuracy was not measured, when it was not.
    not_scored_reason: str = ""
    unmatched_reference_nodes: list[str] = field(default_factory=list)
    unmatched_predicted_nodes: list[str] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return not self.not_scored_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "not_scored_reason": self.not_scored_reason,
            "nodes": self.nodes.to_dict(),
            "concept_edges": self.concept_edges.to_dict(),
            "paper_concept_edges": self.paper_concept_edges.to_dict(),
            "edges_with_unmatched_endpoints": self.edges_with_unmatched_endpoints,
            "unmatched_reference_nodes": sorted(self.unmatched_reference_nodes),
            "unmatched_predicted_nodes": sorted(self.unmatched_predicted_nodes),
        }


def score_extraction(
    predicted_nodes: Iterable[str],
    predicted_edges: Iterable[EdgeKey],
    reference_nodes: Iterable[str],
    reference_edges: Iterable[EdgeKey],
    *,
    predicted_paper_ids: set[str] | None = None,
    reference: Any = None,
) -> ExtractionScores:
    """Score an extracted graph against a reference set.

    `reference` is the `ReferenceSet`; it is only used to enforce the provenance
    rule. Pass a derived set and every score comes back `measured=False` with the
    reason attached, rather than a number that looks like a measurement.
    """
    from rla.eval.ground_truth import assess_reference_set

    if reference is not None:
        assessment = assess_reference_set(reference)
        if not assessment.can_score_extraction:
            reason = " ".join(assessment.blockers)
            return ExtractionScores(
                nodes=ScoreSet("nodes"),
                concept_edges=ScoreSet("concept edges"),
                paper_concept_edges=ScoreSet("paper-concept edges"),
                not_scored_reason=reason,
            )

    pred_names = list(predicted_nodes)
    ref_names = list(reference_nodes)
    node_scores = score_items(
        "nodes",
        (normalise_concept(n) for n in pred_names),
        (normalise_concept(n) for n in ref_names),
    )
    matches, unmatched_pred, unmatched_ref = match_nodes(pred_names, ref_names)

    paper_ids = predicted_paper_ids or set()
    concept_pred, concept_ref = [], []
    paper_pred, paper_ref = [], []
    for edge in predicted_edges:
        (paper_pred if _touches_paper(edge, paper_ids) else concept_pred).append(edge)
    for edge in reference_edges:
        (paper_ref if _touches_paper(edge, paper_ids) else concept_ref).append(edge)

    concept_scores, concept_unmatchable = score_edges(
        "concept edges", concept_pred, concept_ref, paper_ids
    )
    paper_scores, paper_unmatchable = score_edges(
        "paper-concept edges", paper_pred, paper_ref, paper_ids
    )

    return ExtractionScores(
        nodes=node_scores,
        concept_edges=concept_scores,
        paper_concept_edges=paper_scores,
        edges_with_unmatched_endpoints=concept_unmatchable + paper_unmatchable,
        unmatched_reference_nodes=sorted(unmatched_ref),
        unmatched_predicted_nodes=sorted(unmatched_pred),
    )


def _touches_paper(edge: EdgeKey, paper_ids: set[str]) -> bool:
    return edge.source in paper_ids or edge.target in paper_ids
