"""Graph construction: fold extractions into one graph (spec §2 layer 3, §5).

The graph mixes two kinds of edge and the distinction matters for everything
downstream:

- `Paper --CITES--> Paper` is **ground truth** from citation metadata, and is
  already handled in the P0 graph store.
- Every other edge is **LLM-derived** from a P2 extraction, and is therefore only
  as trustworthy as the extraction. Provenance is recorded on each edge's
  `evidence` field so a reader can trace any edge back to the paper it came from.

**Edge direction.** Spec §5 writes `Concept --EXTENDS--> Concept` and glosses it
as "B builds on A", so the arrow runs parent -> child: the *older* concept is the
source and the strictly *newer* one is the target. `enforce_temporal_constraints`
checks exactly that, and getting it backwards would silently delete every
legitimate lineage edge while keeping the impossible ones.

**What is deliberately not modelled.** The extraction prompt returns a richer
relation vocabulary (`extends`, `replaces`, `combines`, `applies-to-new-domain`,
`critiques`) than the seven edge types in the schema, and the two do not map
one-to-one. Every mapping decision is counted in the report rather than dropped
quietly, so a run always says what it could not represent.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Sequence
from pathlib import Path
from typing import Any

from rla.events import Event, Phase, event
from rla.models import Concept, Corpus, EdgeType, Extraction, Paper, Relation, RelationType
from rla.pipeline.resolve import normalise_name
from rla.store.graph_store import Graph, build_graph, enforce_temporal_constraints, save, stats

#: `ConceptMention.role` -> edge type. An unrecognised role is treated as `uses`,
#: the weakest claim, rather than dropped.
ROLE_EDGES: dict[str, EdgeType] = {
    "introduces": EdgeType.INTRODUCES,
    "uses": EdgeType.USES,
    "limitation": EdgeType.HAS_LIMITATION,
}

#: How each extraction relation is expressed in the §5 schema, given the concepts
#: a paper introduces (`child`) and the relation target named in the extraction
#: (`target`).
#:
#:   extends / replaces / combines are statements about a lineage, so they become
#:   concept -> concept edges in the parent -> child direction. A paper that
#:   introduces nothing new cannot anchor a lineage edge, so those cases are
#:   counted under `relation_without_introduced_concept`.
#:
#:   critiques and applies-to-new-domain are statements about a *paper* relative
#:   to a concept, and the schema has no matching paper->concept edge, so they
#:   map onto the two that do exist: HAS_LIMITATION (the paper says this is
#:   deficient, which is what powers gap detection) and USES respectively.
RELATION_EDGES: dict[RelationType, EdgeType] = {
    RelationType.EXTENDS: EdgeType.EXTENDS,
    RelationType.REPLACES: EdgeType.REPLACES,
    RelationType.COMBINES: EdgeType.COMBINES_WITH,
    RelationType.CRITIQUES: EdgeType.HAS_LIMITATION,
    RelationType.APPLIES_TO_NEW_DOMAIN: EdgeType.USES,
}

#: Relations that anchor a lineage edge on a concept the paper introduces.
LINEAGE_RELATIONS = frozenset({RelationType.EXTENDS, RelationType.REPLACES, RelationType.COMBINES})


def name_index(concepts: Iterable[Concept]) -> dict[str, str]:
    """Map every spelling of a concept — canonical name and alias — to its id.

    Extraction targets arrive as free-text names, so they have to be matched back
    onto resolved nodes. Matching is on the P3 normalised form, which means
    "G.A.T." and "gat" both land on the same node.
    """
    index: dict[str, str] = {}
    for concept in concepts:
        for spelling in (concept.name, *concept.aliases):
            key = normalise_name(spelling)
            if key:
                # First writer wins, so a name shared by two concepts stays
                # deterministic instead of depending on list order.
                index.setdefault(key, concept.id)
    return index


def resolve_name(name: str, index: dict[str, str]) -> str | None:
    return index.get(normalise_name(name))


def relations_from_extraction(
    extraction: Extraction,
    index: dict[str, str],
    unresolved: list[dict[str, str]],
) -> list[Relation]:
    """Turn one paper's extraction into schema-conformant relations."""
    paper_id = extraction.paper_id
    out: list[Relation] = []

    def resolve(name: str, source: str) -> str | None:
        concept_id = resolve_name(name, index)
        if concept_id is None:
            unresolved.append({"paper_id": paper_id, "name": name, "from": source})
        return concept_id

    # --- paper -> concept ---------------------------------------------------
    for mention in extraction.concepts:
        edge_type = ROLE_EDGES.get(mention.role.strip().lower(), EdgeType.USES)
        concept_id = resolve(mention.name, f"concept:{mention.role}")
        if concept_id is None:
            continue
        out.append(
            Relation(
                source_id=paper_id,
                target_id=concept_id,
                edge_type=edge_type,
                evidence=f"{paper_id}: role={mention.role}",
            )
        )

    # --- concept -> concept lineage ----------------------------------------
    # Anchored only on concepts this paper *introduces*. A paper that merely
    # uses a concept did not create a new version of it, so letting such a
    # mention anchor a lineage edge would invent descendants and would also
    # smuggle in backwards edges for the temporal filter to have to clean up.
    introduced = [
        resolve_name(m.name, index)
        for m in extraction.concepts
        if m.role.strip().lower() == "introduces"
    ]
    children = [c for c in dict.fromkeys(i for i in introduced if i)]

    parent: str | None = None
    if extraction.relation and extraction.relation_target:
        parent = resolve(extraction.relation_target, "relation")
    if parent is None and extraction.relation:
        unresolved.append(
            {"paper_id": paper_id, "name": "", "from": f"relation:{extraction.relation}"}
        )

    if parent is not None and extraction.relation in LINEAGE_RELATIONS:
        evidence = f"{paper_id}: {extraction.relation.value} {extraction.relation_target}"
        for child in children:
            out.append(
                Relation(
                    source_id=parent,
                    target_id=child,
                    edge_type=RELATION_EDGES[extraction.relation],
                    relation=extraction.relation,
                    evidence=evidence,
                )
            )
    elif parent is not None:
        out.append(
            Relation(
                source_id=paper_id,
                target_id=parent,
                edge_type=RELATION_EDGES[extraction.relation],
                relation=extraction.relation,
                evidence=f"{paper_id}: {extraction.relation.value} {extraction.relation_target}",
            )
        )

    # --- what the paper says it builds on ----------------------------------
    # The primary lineage signal: the extraction prompt asks for it explicitly,
    # separately from the single relation verb above.
    for name in extraction.builds_on:
        built_on = resolve(name, "builds_on")
        if built_on is None:
            continue
        for child in children:
            out.append(
                Relation(
                    source_id=built_on,
                    target_id=child,
                    edge_type=EdgeType.EXTENDS,
                    relation=RelationType.EXTENDS,
                    evidence=f"{paper_id}: builds_on {name}",
                )
            )

    return out


def collect_relations(
    extractions: Sequence[Extraction], concepts: Sequence[Concept]
) -> tuple[list[Relation], list[dict[str, str]]]:
    """All derived relations, plus one deduplicated row per unresolvable name."""
    index = name_index(concepts)
    unresolved: list[dict[str, str]] = []
    relations: list[Relation] = []
    for extraction in extractions:
        relations.extend(relations_from_extraction(extraction, index, unresolved))
    return relations, _dedupe_unresolved(unresolved)


def _dedupe_unresolved(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per (paper, name, from) so the report stays readable at scale."""
    seen: dict[tuple[str, str, str], dict[str, str]] = {}
    for entry in entries:
        seen.setdefault((entry["paper_id"], entry["name"], entry["from"]), entry)
    return list(seen.values())


def build_research_graph(
    papers: Sequence[Paper],
    concepts: Sequence[Concept],
    extractions: Sequence[Extraction],
) -> tuple[Graph, dict[str, Any]]:
    """Assemble the full graph and report everything the schema could not hold."""
    relations, unresolved = collect_relations(extractions, concepts)
    graph, counts, violations = build_graph(papers, concepts, relations)

    report: dict[str, Any] = {
        "citations": counts.citations,
        "derived_edges": counts.added,
        "skipped_missing_endpoint": counts.skipped_missing_endpoint,
        "duplicate_relations": counts.duplicate,
        "temporal_violations_dropped": len(violations),
        "temporal_violations": violations,
    }

    extracted_ids = {e.paper_id for e in extractions}

    by_type = Counter(str(r.edge_type) for r in relations)
    report.update(
        {
            "papers": len(papers),
            "concepts": len(concepts),
            "extractions": len(extractions),
            "papers_without_extraction": [p.id for p in papers if p.id not in extracted_ids],
            "papers_without_concepts": [e.paper_id for e in extractions if not e.concepts],
            "relations_by_type": dict(sorted(by_type.items())),
            "unresolved_targets": _dedupe_unresolved(unresolved),
            "unresolved_target_count": len(_dedupe_unresolved(unresolved)),
            "stats": stats(graph),
        }
    )
    return graph, report


def _no_extraction_report(reason: str, papers: int) -> dict[str, Any]:
    return {
        "papers": papers,
        "concepts": 0,
        "extractions": 0,
        "papers_without_extraction": [],
        "papers_without_concepts": [],
        "relations_by_type": {},
        "unresolved_targets": [],
        "unresolved_target_count": 0,
        "reason": reason,
    }


def save_graph(graph: Graph, json_path: Path, graphml_path: Path) -> None:
    save(graph, json_path, graphml_path)


async def build_graph_stage(
    corpus: Corpus,
    concepts: Sequence[Concept],
    extractions: Sequence[Extraction],
    json_path: Path,
    graphml_path: Path,
) -> AsyncIterator[Event]:
    """Build, persist, and describe the graph. The last event carries the report."""
    from rla.store.extraction_store import reconcile_extractions

    integrity = reconcile_extractions(corpus, extractions)
    if not integrity.intact:
        yield event(
            Phase.GRAPH,
            f"refusing to build a graph: {len(integrity.stale)} stored extraction(s) belong "
            f"to a different corpus and {len(integrity.superseded)} describe superseded "
            f"paper content. A graph built now would be wrong in a way no reader could "
            f"detect. {integrity.advice}",
            kind="error",
            stale_extractions=len(integrity.stale),
            superseded_extractions=len(integrity.superseded),
            blocked=True,
        )
        return

    if integrity.missing:
        yield event(
            Phase.GRAPH,
            f"{len(integrity.missing)} corpus paper(s) have no extraction; building a "
            "partial graph",
            kind="warn",
            missing_extractions=len(integrity.missing),
            blocked=False,
        )

    if not concepts:
        report = _no_extraction_report(
            "no resolved concepts; run resolution first", len(corpus.papers)
        )
        yield event(
            Phase.GRAPH,
            "no resolved concepts on disk; run resolution first",
            kind="pending",
            **report,
        )
        return

    graph, report = build_research_graph(corpus.papers, concepts, extractions)

    # The gate is "zero temporal violations", so assert the invariant the
    # builder claims rather than trusting the count it printed.
    remaining = enforce_temporal_constraints(graph)
    if remaining:
        yield event(
            Phase.GRAPH,
            f"internal error: {len(remaining)} temporal violations survived cleaning",
            kind="error",
            violations=[{"source": s, "target": t} for s, t, _ in remaining],
        )

    if report["skipped_missing_endpoint"]:
        yield event(
            Phase.GRAPH,
            f"{report['skipped_missing_endpoint']} relation(s) were dropped because an "
            "endpoint is not in the graph",
            kind="warn",
            skipped_missing_endpoint=report["skipped_missing_endpoint"],
        )

    save_graph(graph, json_path, graphml_path)

    stats_ = report["stats"]
    yield event(
        Phase.GRAPH,
        f"{stats_['nodes']} nodes ({stats_.get('nodes_Paper', 0)} papers, "
        f"{stats_.get('nodes_Concept', 0)} concepts), {stats_['edges']} edges "
        f"({report['relations_by_type'].get('CITES', 0)} citation, "
        f"{sum(v for k, v in report['relations_by_type'].items() if k != 'CITES')} derived)",
        kind="ok",
        path=str(json_path),
        graphml=str(graphml_path),
        **report,
    )


def load_graph(json_path: Path) -> Graph | None:
    """Read a persisted graph, or None when it has never been built."""
    if not json_path.exists():
        return None
    from rla.store.graph_store import load

    return load(json_path)


def describe(graph: Graph) -> str:
    return json.dumps(stats(graph), indent=2)
