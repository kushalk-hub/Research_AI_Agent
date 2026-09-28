"""Question classification and graph traversal (spec section 6).

Five pure functions of `(graph, question) -> Subgraph`, one per question type.
Pure is the point: traversal decides *what the answer is allowed to see*, and it
must be reproducible and unit-testable without an LLM in the loop. Generation
(P5's second half, `answer.py`) happens afterwards and is the only stage allowed
to be non-deterministic.

The subgraph carries its own citation labels (`[P1]`, `[C4]`) assigned in a
stable order, so a given question always produces the same ids. That is what
lets `validate_citations` strip a hallucinated id without guessing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rla.models import EdgeType, NodeType
from rla.store.graph_store import Graph, year_of

#: Lineage edges point parent -> child, so a child's ancestors are its
#: predecessors and a parent's descendants are its successors.
LINEAGE_EDGES: frozenset[str] = frozenset(
    {str(EdgeType.EXTENDS), str(EdgeType.REPLACES)}
)


class QuestionType(StrEnum):
    LINEAGE = "lineage"
    GAP = "gap"
    COMPARISON = "comparison"
    APPROACHES = "approaches"
    FULL_REPORT = "full_report"


#: Ordered most-specific first. "how did X evolve" is lineage, but "how do X and
#: Y compare" is a comparison, so comparison is tested before lineage.
_CLASSIFY_RULES: tuple[tuple[QuestionType, tuple[str, ...]], ...] = (
    (
        QuestionType.COMPARISON,
        (
            r"\bcompare\b", r"\bversus\b", r"\bvs\.?\b", r"\bdifference between\b",
            r"\bbetter than\b", r"\btrade[- ]?offs?\b", r"\bhow do\b.*\band\b",
        ),
    ),
    (
        QuestionType.GAP,
        (
            r"\bgaps?\b", r"\bunsolved\b", r"\bunresolved\b", r"\bopen problems?\b",
            r"\blimitation", r"\bunder[- ]?explored\b", r"\bunderstudied\b",
            r"\bunexplored\b", r"\bnot (?:yet )?(?:been )?(?:tried|explored|studied)\b",
            r"\bremains?\b", r"\bwhat'?s missing\b", r"\bweakness",
        ),
    ),
    (
        QuestionType.LINEAGE,
        (
            r"\blineage\b", r"\bevol", r"\bhistory of\b", r"\borigin", r"\broots?\b",
            r"\btrace\b", r"\bdeveloped\b", r"\bhow did\b", r"\bprogression\b",
        ),
    ),
    (
        QuestionType.APPROACHES,
        (
            r"\bapproaches?\b", r"\bmethods?\b", r"\btechniques?\b", r"\bstrategies\b",
            r"\bmajor\b", r"\bwhat (?:methods|techniques|approaches)\b",
            r"\bcommonly used\b", r"\bstate of the art\b", r"\bfamilies\b",
        ),
    ),
    (
        QuestionType.FULL_REPORT,
        (
            r"\breport\b", r"\bfull\b", r"\boverview\b", r"\beverything\b",
            r"\bsummary\b", r"\bwhat has been done\b", r"\bthe whole\b",
        ),
    ),
)

_STOPWORDS = frozenset(
    """a an the and or of for to in on with by from is are was were be been what
    which who whom how does do did can could should would will shall may might
    between among about into over under than then them their there these those
    that this these those it its as at we i you they he she""".split()
)


def classify_question(question: str) -> QuestionType:
    """Pick a traversal strategy from the question text.

    Keyword rules rather than an LLM call, so classification is free, instant,
    and testable. A question that matches nothing becomes a full report, which
    is the honest default: answer from the whole graph rather than pretending
    to have understood a narrower ask.
    """
    text = f" {question.lower().strip()} "
    for qtype, patterns in _CLASSIFY_RULES:
        if any(re.search(pattern, text) for pattern in patterns):
            return qtype
    return QuestionType.FULL_REPORT


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _label_text(graph: Graph, node_id: str) -> str:
    data = graph.nodes[node_id]
    parts = [
        str(data.get("label") or data.get("name") or ""),
        " ".join(data.get("aliases") or []),
        str(data.get("description") or ""),
    ]
    return " ".join(p for p in parts if p)


def score_concepts(graph: Graph, text: str) -> list[tuple[str, float]]:
    """Rank Concept nodes against `text`, best first.

    Deliberately lexical and transparent: an embedding lookup would be another
    network call, and a traversal that quietly picks the wrong seed concept
    produces a confident, wrong answer. Overlap on a concept's name, aliases,
    and description is easy to reason about and to assert in tests.
    """
    wanted = _tokens(text)
    if not wanted:
        return []
    scored: list[tuple[str, float]] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("type") != str(NodeType.CONCEPT):
            continue
        have = _tokens(_label_text(graph, node_id))
        if not have:
            continue
        overlap = wanted & have
        if not overlap:
            continue
        # Weight the name far above the description: a concept mentioned once by
        # name is a better seed than one whose description happens to echo the
        # question's wording.
        name_tokens = _tokens(str(data.get("name") or ""))
        alias_tokens = set().union(*(_tokens(a) for a in data.get("aliases") or []))
        weighted = sum(
            1.0 if t in name_tokens else 0.6 if t in alias_tokens else 0.25
            for t in overlap
        )
        scored.append((node_id, weighted / max(1, len(wanted))))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def find_concepts(graph: Graph, text: str, limit: int = 3) -> list[str]:
    """Best-matching Concept nodes for a phrase, strongest first.

    Two thresholds, and both are needed. The relative one (`best * 0.6`) drops
    concepts that merely echo a passing word. The absolute one is expressed in
    raw match weight rather than the normalised score, because normalising by
    the question's token count makes a long question match nothing at all:
    "How do GAT and GCN compare" scores 0.2 against an honest one-word hit, yet
    it is the clearest possible mention. Requiring a raw weight of 0.6 (a name
    or alias hit) instead keeps length-independence.
    """
    scored = score_concepts(graph, text)
    if not scored:
        return []
    wanted = max(1, len(_tokens(text)))
    floor = 0.6 / wanted
    best = scored[0][1]
    return [n for n, s in scored[:limit] if s >= best * 0.6 and s >= floor]


@dataclass(slots=True)
class SubgraphNode:
    node_id: str
    label: str
    type: str
    name: str
    year: int | None = None
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SubgraphEdge:
    source: str
    target: str
    type: str
    evidence: str = ""
    ground_truth: bool = False


@dataclass(slots=True)
class Subgraph:
    """A small slice of the graph plus the citation labels the answer may use."""

    question: str
    question_type: QuestionType
    nodes: list[SubgraphNode] = field(default_factory=list)
    edges: list[SubgraphEdge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    seeds: list[str] = field(default_factory=list)

    @property
    def labels(self) -> set[str]:
        return {n.label for n in self.nodes}

    def node_by_label(self, label: str) -> SubgraphNode | None:
        return next((n for n in self.nodes if n.label == label), None)

    def edge_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.edges:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts

    def render(self) -> str:
        """The exact text the answer LLM sees, labels included."""
        lines = [f"question type: {self.question_type}", f"question: {self.question}", ""]
        if self.notes:
            lines.append("notes:")
            lines += [f"- {n}" for n in self.notes]
            lines.append("")
        lines.append("nodes:")
        for n in self.nodes:
            year = f" ({n.year})" if n.year else ""
            lines.append(f"- [{n.label}] {n.type}{year}: {n.name}")
            if n.detail:
                lines.append(f"    {n.detail}")
        if self.edges:
            lines.append("")
            lines.append("edges:")
            for e in self.edges:
                tag = "" if e.ground_truth else " (inferred)"
                lines.append(f"- [{e.source}] -[{e.type}]-> [{e.target}]{tag}")
        return "\n".join(lines)

    def to_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "question_type": str(self.question_type),
            "nodes": [
                {"id": n.node_id, "label": n.label, "type": n.type, "name": n.name,
                 "year": n.year, "extra": n.extra}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "type": e.type,
                 "ground_truth": e.ground_truth}
                for e in self.edges
            ],
            "notes": self.notes,
            "seeds": self.seeds,
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "papers": sum(1 for n in self.nodes if n.type == str(NodeType.PAPER)),
                "concepts": sum(1 for n in self.nodes if n.type == str(NodeType.CONCEPT)),
                **self.edge_types(),
            },
        }


# -- assembly helpers ----------------------------------------------------------


def _collect(
    graph: Graph, keep: Iterable[str], question: str, qtype: QuestionType, **kwargs: Any
) -> Subgraph:
    """Build a Subgraph from node ids, labelling papers and concepts separately.

    Labels are assigned after sorting, so `[P1]` is the same paper for the same
    question on every run.
    """
    present = [n for n in dict.fromkeys(keep) if graph.has_node(n)]
    # Newest paper first, then concepts: a reader (and the answer LLM) wants
    # chronology, and it is still fully deterministic.
    papers = sorted(
        (n for n in present if graph.nodes[n].get("type") == str(NodeType.PAPER)),
        key=lambda n: (-(year_of(graph, n) or 0), str(graph.nodes[n].get("label") or "")),
    )
    concepts = sorted(
        n for n in present if graph.nodes[n].get("type") == str(NodeType.CONCEPT)
    )
    nodes: list[SubgraphNode] = []
    labels: dict[str, str] = {}
    for index, node_id in enumerate(papers, start=1):
        label = f"P{index}"
        labels[node_id] = label
        nodes.append(_paper_node(graph, node_id, label))
    for index, node_id in enumerate(concepts, start=1):
        label = f"C{index}"
        labels[node_id] = label
        nodes.append(_concept_node(graph, node_id, label))

    edges: list[SubgraphEdge] = []
    for source, target, data in graph.edges(data=True):
        if source in labels and target in labels:
            edges.append(
                SubgraphEdge(
                    source=labels[source],
                    target=labels[target],
                    type=str(data.get("type")),
                    evidence=str(data.get("evidence") or ""),
                    ground_truth=bool(data.get("ground_truth")),
                )
            )
    return Subgraph(question=question, question_type=qtype, nodes=nodes, edges=edges, **kwargs)


def _paper_node(graph: Graph, node_id: str, label: str) -> SubgraphNode:
    data = graph.nodes[node_id]
    return SubgraphNode(
        node_id=node_id,
        label=label,
        type=str(NodeType.PAPER),
        name=str(data.get("label") or node_id),
        year=year_of(graph, node_id),
        detail=str(data.get("abstract") or "")[:280],
        extra={"doi": data.get("doi", ""), "venue": data.get("venue", "")},
    )


def _concept_node(graph: Graph, node_id: str, label: str) -> SubgraphNode:
    data = graph.nodes[node_id]
    aliases = list(data.get("aliases") or [])
    detail = str(data.get("description") or "")
    if aliases:
        detail = f"{detail} (also: {', '.join(aliases)})".strip()
    return SubgraphNode(
        node_id=node_id,
        label=label,
        type=str(NodeType.CONCEPT),
        name=str(data.get("name") or data.get("label") or node_id),
        year=year_of(graph, node_id),
        detail=detail,
        extra={"aliases": aliases},
    )


def _papers_touching(graph: Graph, concept_ids: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for concept in concept_ids:
        out |= _papers_on(graph, concept)
    return out


# -- the five strategies -------------------------------------------------------


def lineage_subgraph(graph: Graph, question: str, max_depth: int = 3) -> Subgraph:
    """Walk ancestry backwards and descendants forwards, ordered by year (spec 6).

    Ancestors are in-neighbours along EXTENDS/REPLACES because those edges run
    parent -> child; descendants are out-neighbours. Papers attached to every
    concept along the chain come along, since the chain alone names no findings.
    """
    seeds = find_concepts(graph, question, limit=1)
    notes: list[str] = []
    if not seeds:
        notes.append(
            "No concept in the graph matches the question, so lineage could not be "
            "anchored. Showing the concepts with the most lineage edges instead."
        )
        seeds = _most_lineage_connected(graph, limit=1)
        if not seeds:
            return Subgraph(
                question=question, question_type=QuestionType.LINEAGE,
                notes=["The graph has no lineage edges to walk."],
            )
        notes.append(f"Anchored on {graph.nodes[seeds[0]].get('name')!r} as a substitute.")

    keep: set[str] = set(seeds)
    chain: set[str] = set(seeds)
    frontier = set(seeds)
    for _ in range(max_depth):
        nxt: set[str] = set()
        for node in frontier:
            for parent in graph.predecessors(node):
                if _edge_types(graph, parent, node) & LINEAGE_EDGES:
                    nxt.add(parent)
            for child in graph.successors(node):
                if _edge_types(graph, node, child) & LINEAGE_EDGES:
                    nxt.add(child)
        nxt -= chain
        if not nxt:
            break
        chain |= nxt
        frontier = nxt
    keep |= chain
    keep |= _papers_touching(graph, chain)
    return _collect(
        graph, keep, question, QuestionType.LINEAGE, seeds=seeds, notes=notes
    )


def gap_subgraph(graph: Graph, question: str, top: int = 8) -> Subgraph:
    """Surface under-extended concepts and unresolved limitations (spec 6, 7).

    Two independent signals, per spec section 7: stated gaps (papers with
    HAS_LIMITATION into the area) and structural gaps (old concepts almost
    nothing builds on, which no single paper states).
    """
    area = find_concepts(graph, question, limit=2)
    notes: list[str] = []
    if not area:
        notes.append(
            "No concept matches the named area; ranked all concepts by stated and "
            "structural gap signals instead."
        )
        pool = [
            n for n, d in graph.nodes(data=True) if d.get("type") == str(NodeType.CONCEPT)
        ]
    else:
        pool = list(area)
        # Concepts that co-occur with the area are in scope too: a gap is often
        # stated about a neighbouring concept rather than the named one.
        neighbours: set[str] = set()
        for node in area:
            for paper in graph.predecessors(node):
                if graph.nodes[paper].get("type") != str(NodeType.PAPER):
                    continue
                for other in graph.successors(paper):
                    if other != node:
                        neighbours.add(other)
        pool += sorted(neighbours - set(area))

    limited: set[str] = set()
    for paper in graph.nodes:
        if graph.nodes[paper].get("type") != str(NodeType.PAPER):
            continue
        limited |= _limitation_targets(graph, paper)

    ranked: list[tuple[str, int]] = []
    for node in pool:
        if graph.nodes[node].get("type") != str(NodeType.CONCEPT):
            continue
        score = 0
        if node in limited:
            score += 10
        # Structural gap: old enough to have been built on, yet nothing does.
        if _lineage_in_degree(graph, node) == 0 and (year_of(graph, node) or 0) > 0:
            score += 3
        if score:
            ranked.append((node, score))
    ranked.sort(key=lambda item: (-item[1], -(year_of(graph, item[0]) or 0), item[0]))
    chosen = [n for n, _ in ranked[:top]]
    if not chosen:
        notes.append("No stated or structural gaps found in the graph.")

    keep: set[str] = set(chosen)
    for node in chosen:
        keep |= _papers_on(graph, node)
    if chosen:
        notes.append(
            f"{len(chosen)} candidate gap concept(s); {sum(1 for n in chosen if n in limited)} "
            "carry a stated limitation."
        )
    return _collect(graph, keep, question, QuestionType.GAP, seeds=area, notes=notes)


def comparison_subgraph(graph: Graph, question: str) -> Subgraph:
    """Common ancestry plus common co-usage, then the divergence (spec 6)."""
    targets = find_concepts(graph, question, limit=2)
    notes: list[str] = []
    if len(targets) == 1:
        # One side of the comparison is absent. Say so, and treat the single
        # match as an area rather than inventing a second concept to contrast.
        single = targets[0]
        notes.append(
            f"Only {graph.nodes[single].get('name')!r} matched, so the divergence "
            "cannot be grounded; showing its lineage and co-used papers instead."
        )
        keep = {single} | _papers_touching(graph, [single])
        return _collect(
            graph, keep, question, QuestionType.COMPARISON, seeds=targets, notes=notes
        )
    if not targets:
        # Nothing matched at all: anchor on the two most-built-upon concepts so
        # the user still gets a usable slice rather than an error.
        pool = [
            n for n, d in graph.nodes(data=True) if d.get("type") == str(NodeType.CONCEPT)
        ]
        if len(pool) < 2:
            notes.append("The graph has fewer than two concepts to compare.")
            return _collect(
                graph, set(), question, QuestionType.COMPARISON, seeds=[], notes=notes
            )
        targets = sorted(pool, key=lambda n: (-_lineage_in_degree(graph, n), n))[:2]
        notes.append(
            "Neither named concept exists; showing the two most built-upon concepts "
            f"instead: {graph.nodes[targets[0]].get('name')!r} and "
            f"{graph.nodes[targets[1]].get('name')!r}."
        )
    if len(targets) < 2:
        notes.append(
            "Fewer than two distinct concepts matched the question, so a comparison "
            "is not supported by the graph."
        )
    left, right = targets[0], targets[1]

    def ancestors(node: str) -> set[str]:
        seen: set[str] = set()
        frontier = {node}
        while frontier:
            nxt: set[str] = set()
            for cur in frontier:
                for parent in graph.predecessors(cur):
                    if _edge_types(graph, parent, cur) & LINEAGE_EDGES and parent not in seen:
                        nxt.add(parent)
            seen |= nxt
            frontier = nxt
        return seen

    def descendants(node: str) -> set[str]:
        seen: set[str] = set()
        frontier = {node}
        while frontier:
            nxt: set[str] = set()
            for cur in frontier:
                for child in graph.successors(cur):
                    if _edge_types(graph, cur, child) & LINEAGE_EDGES and child not in seen:
                        nxt.add(child)
            seen |= nxt
            frontier = nxt
        return seen

    shared_ancestry = ancestors(left) & ancestors(right)
    only_left = descendants(left) - {right} - set(ancestors(right))
    only_right = descendants(right) - {left} - set(ancestors(left))
    both = _papers_touching(graph, [left, right])
    # Papers that apply *both* concepts are what make a comparison grounded;
    # merely touching one of them is not enough.
    papers_using_both = {
        paper
        for paper in both
        if _uses(graph, paper, left) and _uses(graph, paper, right)
    }
    shared_papers = both - papers_using_both

    notes.append(
        f"shared ancestry: {len(shared_ancestry)}; unique to "
        f"{graph.nodes[left].get('name')!r}: {len(only_left)}; unique to "
        f"{graph.nodes[right].get('name')!r}: {len(only_right)}"
    )
    keep = (
        set(targets)
        | shared_ancestry
        | only_left
        | only_right
        | shared_papers
        | papers_using_both
    )
    return _collect(graph, keep, question, QuestionType.COMPARISON, seeds=targets, notes=notes)


def approaches_subgraph(graph: Graph, question: str, top: int = 8) -> Subgraph:
    """Concepts with the most USES in-degree inside the area (spec 6)."""
    area = find_concepts(graph, question, limit=2)
    notes: list[str] = []
    if area:
        neighbours: set[str] = set()
        for node in area:
            for paper in graph.predecessors(node):
                if graph.nodes[paper].get("type") != str(NodeType.PAPER):
                    continue
                for other in graph.successors(paper):
                    if other != node:
                        neighbours.add(other)
        pool = list(area) + sorted(neighbours - set(area))
    else:
        notes.append(
            "No concept matches the question; ranked every concept by how many papers use it."
        )
        pool = [
            n for n, d in graph.nodes(data=True) if d.get("type") == str(NodeType.CONCEPT)
        ]

    ranked = sorted(
        ((n, _uses_in_degree(graph, n)) for n in pool),
        key=lambda item: (-item[1], item[0]),
    )
    chosen = [n for n, degree in ranked[:top] if degree > 0] or [n for n, _ in ranked[:top]]
    if not chosen:
        return Subgraph(
            question=question, question_type=QuestionType.APPROACHES,
            notes=["The graph contains no concepts to rank."],
        )
    notes.append(
        "ranked by number of papers using each concept: "
        + ", ".join(f"{graph.nodes[n].get('name')}={d}" for n, d in ranked[:top] if d)
    )
    keep: set[str] = set(chosen)
    for node in chosen:
        keep |= _papers_on(graph, node)
    return _collect(graph, keep, question, QuestionType.APPROACHES, seeds=area, notes=notes)


def full_report_subgraph(graph: Graph, question: str, max_nodes: int = 40) -> Subgraph:
    """Chronological walk of the field plus every stated gap (spec 6, 7).

    Reports whole-field questions from the entire graph; that is the one case
    where "not the whole graph" is not the useful behaviour.
    """
    papers = [n for n, d in graph.nodes(data=True) if d.get("type") == str(NodeType.PAPER)]
    concepts = [n for n, d in graph.nodes(data=True) if d.get("type") == str(NodeType.CONCEPT)]
    ordered = sorted(
        papers, key=lambda n: (-(year_of(graph, n) or 0), str(graph.nodes[n].get("label") or ""))
    )
    truncated = len(ordered) > max_nodes
    # `max_nodes` is a cap on papers, and the retained walk is the only source of
    # paper nodes, so no later step can quietly put the older ones back.
    keep: set[str] = set(ordered[:max_nodes])
    for paper in list(keep):
        # Concepts the retained papers touch, so the walk is not a bare list.
        # Restricted to Concept nodes on purpose: a paper's successors also
        # include the papers it cites, which would put truncated-away work back
        # into the walk and defeat the cap.
        keep |= {
            other
            for other in graph.successors(paper)
            if graph.nodes[other].get("type") == str(NodeType.CONCEPT)
        }
    for concept in concepts:
        if _lineage_in_degree(graph, concept) or _uses_in_degree(graph, concept):
            keep.add(concept)
    notes = [
        f"chronological walk of {len(ordered)} paper(s), newest first",
        f"{len(concepts)} concept(s) considered",
    ]
    if truncated:
        notes.append(
            f"showing the {max_nodes} most recent papers of {len(ordered)}; older work omitted"
        )
    limitation_edges = sum(
        1 for _, _, d in graph.edges(data=True) if d.get("type") == str(EdgeType.HAS_LIMITATION)
    )
    notes.append(f"{limitation_edges} stated limitation edge(s) in scope")
    return _collect(graph, keep, question, QuestionType.FULL_REPORT, notes=notes)


# -- edge utilities ------------------------------------------------------------


def _edge_types(graph: Graph, source: str, target: str) -> set[str]:
    return {str(d.get("type")) for d in _edges_between(graph, source, target)}


def _edges_between(graph: Graph, source: str, target: str) -> list[dict[str, Any]]:
    """Every parallel edge from source to target.

    `MultiDiGraph.out_edges` takes `data` as its second positional argument, so
    it cannot be used to filter by target; `get_edge_data` is the correct door.
    """
    bundle = graph.get_edge_data(source, target) or {}
    return [dict(data) for data in bundle.values() if isinstance(data, dict)]


def _has_edge_type(graph: Graph, source: str, target: str, edge_type: EdgeType) -> bool:
    return any(
        d.get("type") == str(edge_type) for d in _edges_between(graph, source, target)
    )


def _is_paper(graph: Graph, node: str) -> bool:
    return graph.nodes[node].get("type") == str(NodeType.PAPER)


def _papers_on(graph: Graph, concept: str) -> set[str]:
    """Papers attached to a concept, in either direction."""
    return {
        n
        for n in (*graph.predecessors(concept), *graph.successors(concept))
        if _is_paper(graph, n)
    }


def _uses_in_degree(graph: Graph, concept: str) -> int:
    """How many papers apply this concept."""
    return sum(
        1
        for paper in graph.predecessors(concept)
        if _is_paper(graph, paper) and _has_edge_type(graph, paper, concept, EdgeType.USES)
    )


def _lineage_in_degree(graph: Graph, concept: str) -> int:
    """How many concepts build on this one. Low on an old node means abandoned."""
    return sum(
        1
        for child in graph.predecessors(concept)
        if graph.nodes[child].get("type") == str(NodeType.CONCEPT)
        and _edge_types(graph, child, concept) & LINEAGE_EDGES
    )


def _uses(graph: Graph, paper: str, concept: str) -> bool:
    return any(d.get("type") == str(EdgeType.USES) for d in _edges_between(graph, paper, concept))


def _limitation_targets(graph: Graph, paper: str) -> set[str]:
    return {
        target
        for target in graph.successors(paper)
        if _has_edge_type(graph, paper, target, EdgeType.HAS_LIMITATION)
    }


def _most_lineage_connected(graph: Graph, limit: int = 1) -> list[str]:
    scored: list[tuple[str, int]] = []
    for node, data in graph.nodes(data=True):
        if data.get("type") != str(NodeType.CONCEPT):
            continue
        # `predecessors`/`successors` return iterators in this NetworkX version,
        # so they must be materialised before being counted.
        degree = sum(1 for _ in graph.predecessors(node)) + sum(
            1 for _ in graph.successors(node)
        )
        if degree:
            scored.append((node, degree))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [n for n, _ in scored[:limit]]


STRATEGIES = {
    QuestionType.LINEAGE: lineage_subgraph,
    QuestionType.GAP: gap_subgraph,
    QuestionType.COMPARISON: comparison_subgraph,
    QuestionType.APPROACHES: approaches_subgraph,
    QuestionType.FULL_REPORT: full_report_subgraph,
}


def traverse(
    graph: Graph, question: str, question_type: QuestionType | None = None
) -> Subgraph:
    """Classify (if needed) and run the matching strategy."""
    qtype = question_type or classify_question(question)
    return STRATEGIES[qtype](graph, question)


# -- citation validation -------------------------------------------------------

_CITATION = re.compile(r"\[(?:P|C)\d+\]")


def validate_citations(answer: str, subgraph: Subgraph) -> tuple[str, list[str]]:
    """Remove citation ids that are not in the subgraph.

    The prompt forbids inventing ids, but prompts are not guarantees. Returns the
    cleaned text and the ids that were stripped, so the caller can report how
    much of the answer was unsupported rather than silently shipping it.
    """
    allowed = subgraph.labels
    stripped: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token[1:-1] in allowed:
            return token
        stripped.append(token)
        return ""

    cleaned = _CITATION.sub(_replace, answer)
    if stripped:
        # Collapse the blank where the bad citation sat, so prose does not tear.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" +([,.;:])", r"\1", cleaned)
    return cleaned, stripped
