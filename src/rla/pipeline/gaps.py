"""P6 gap analysis: per-paper limitations, cross-paper themes, structural gaps.

Five pure stages, each independently testable, in the order the spec requires:

1. `paper_table`    - one row per paper that states a limitation.
2. `cluster_themes` - group stated gaps by what they are about.
3. `structural_gaps`- old concepts nothing builds on, per the in-degree rule.
4. `rank_gaps`      - order by recency and frequency.
5. `suppress_closed`- drop gaps a later in-corpus paper has already answered.

The two signals are kept apart on purpose. A stated gap is a limitation a paper
admits out loud; a structural gap is a silence in the graph. Merging them into
one list would make an inference look like a quotation, and every downstream
claim about what is unresolved depends on telling those apart.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from rla.models import EdgeType, Extraction, NodeType, Paper
from rla.store.graph_store import Graph, year_of

#: A concept must predate the rest of the corpus by at least this many years
#: before its silence counts as abandonment. Measured against the corpus rather
#: than a fixed calendar year, since "old" is relative to the material available.
#:
#: Three is not arbitrary. A direction cannot be called abandoned on the strength
#: of a corpus that only spans two years: at that point almost every concept looks
#: unbuilt-upon, and flagging all of them is a statement about the corpus, not
#: about the field. Three years is the shortest span in which a concept can
#: plausibly have been built on and not been.
STRUCTURAL_GAP_MIN_AGE = 3

#: A stated gap is ranked down once this many papers say the same thing, because
#: repetition is evidence the problem is real, not evidence it is unresolved.
_SATURATION_AT = 5


# -- 1. the per-paper table ----------------------------------------------------


@dataclass(slots=True)
class LimitationRow:
    paper_id: str
    title: str
    year: int | None
    limitation: str
    open_problem: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "label": self.label,
            "title": self.title,
            "year": self.year,
            "limitation": self.limitation,
            "open_problem": self.open_problem,
        }


def paper_table(
    extractions: Iterable[Extraction],
    papers: dict[str, Paper] | None = None,
) -> list[LimitationRow]:
    """One row per paper that states a limitation of its own method.

    Papers that state nothing are simply absent. A row with an empty limitation
    would be a claim that a paper had no limitations, which is not a thing the
    corpus can establish, so they are excluded rather than filled in.
    """
    titles = {p.id: p for p in (papers or {}).values()}
    rows: list[LimitationRow] = []
    for extraction in extractions:
        limitation = (extraction.stated_limitation or "").strip()
        if not limitation:
            continue
        paper = titles.get(extraction.paper_id)
        rows.append(
            LimitationRow(
                paper_id=extraction.paper_id,
                title=paper.title if paper else extraction.paper_id,
                year=paper.year if paper else None,
                limitation=limitation,
                open_problem=(extraction.inferred_open_problem or "").strip(),
            )
        )
    rows.sort(key=lambda r: (-(r.year or 0), r.paper_id))
    for index, row in enumerate(rows, start=1):
        row.label = f"L{index}"
    return rows


def render_table(rows: Sequence[LimitationRow]) -> str:
    """Markdown table of the per-paper limitations, each with its citation label."""
    if not rows:
        return "_No paper in the corpus states a limitation._"
    lines = ["| # | Paper | Year | Stated limitation |", "|---|---|---|---|"]
    for row in rows:
        text = " ".join(row.limitation.split())
        year = row.year if row.year else "n/a"
        lines.append(f"| [{row.label}] | {_cell(row.title)} | {year} | {_cell(text)} |")
    return "\n".join(lines)


def _cell(text: str, limit: int = 200) -> str:
    """Flatten to one line and clip, so a row cannot break the table layout."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].strip() + "…"


# -- 2. theme clustering -------------------------------------------------------

#: Themes are matched by keyword against the limitation text. An embedding
#: clustering would cost one request per limitation, and the free tier allows
#: ~20 requests a day; the gate needs this to run offline and deterministically.
THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scalability", ("scal", "large-scale", "large scale", "memory", "computational cost",
                     "expensive", "efficien", "throughput", "latency")),
    ("generalisation", ("generaliz", "generaliz", "transfer", "cross-domain", "out-of-distribution",
                        "unseen", "domain-specific", "other domains")),
    ("evaluation", ("evaluat", "benchmark", "dataset", "metric", "baseline", "experiment")),
    ("interpretability", ("interpret", "explainab", "transparent", "black box", "black-box",
                          "reasoning", "human-understandable")),
    ("robustness", ("robust", "noise", "adversarial", "outlier", "perturb", "unstable",
                    "over-smooth", "oversmooth", "stability", "converg")),
    ("data_requirements", ("annotat", "label", "training data", "supervis", "supervis",
                           "data-hungry", "few-shot", "zero-shot")),
    ("theoretical", ("theoret", "convergence proof", "bound", "guarantee", "provably")),
    ("real_world_deployment", ("real-world", "production", "deploy", "latency-critical",
                               "hardware", "resource-constrained", "edge")),
)


@dataclass(slots=True)
class Theme:
    name: str
    rows: list[LimitationRow] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.rows]

    @property
    def newest_year(self) -> int | None:
        years = [r.year for r in self.rows if r.year]
        return max(years) if years else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.name,
            "count": self.count,
            "newest_year": self.newest_year,
            "citations": self.labels,
        }


def classify_theme(text: str) -> str:
    """The first theme whose keywords appear, or `other` when nothing matches."""
    lowered = text.lower()
    for name, keywords in THEME_RULES:
        if any(keyword in lowered for keyword in keywords):
            return name
    return "other"


def cluster_themes(rows: Sequence[LimitationRow]) -> list[Theme]:
    """Group stated gaps by theme, most-repeated first.

    A limitation can match several themes; the first match wins, so every gap
    lands in exactly one bucket and the counts sum to the number of rows. A
    gap claimed by two themes would inflate the totals that ranking depends on.
    """
    buckets: dict[str, Theme] = {}
    for row in rows:
        theme = classify_theme(row.limitation)
        buckets.setdefault(theme, Theme(theme)).rows.append(row)
    ordered = sorted(buckets.values(), key=lambda t: (-t.count, t.name))
    return ordered


# -- 3. structural gaps --------------------------------------------------------


@dataclass(slots=True)
class StructuralGap:
    concept_id: str
    name: str
    year: int | None
    in_degree: int
    papers: list[str] = field(default_factory=list)
    label: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "label": self.label,
            "name": self.name,
            "year": self.year,
            "lineage_in_degree": self.in_degree,
            "papers": self.papers,
            "reason": self.reason,
        }


def _lineage_in_degree(graph: Graph, concept: str) -> int:
    """In-degree along EXTENDS/REPLACES, counting distinct source concepts.

    In-degree is what the spec asks for ("very few `EXTENDS` edges pointing to
    them"), and it is what traverse.py already uses for its structural-gap
    heuristic, so both stages flag the same concepts.

    Note that `EXTENDS` runs parent -> child, so this counts the concepts this
    one descends from. Reading it as "successors" would mean `successors()`; the
    two disagree on direction, and this follows the spec's literal wording.
    """
    count = 0
    for parent in graph.predecessors(concept):
        if graph.nodes[parent].get("type") != str(NodeType.CONCEPT):
            continue
        bundle = graph.get_edge_data(parent, concept) or {}
        if any(
            d.get("type") in {str(EdgeType.EXTENDS), str(EdgeType.REPLACES)}
            for d in bundle.values()
        ):
            count += 1
    return count


def _corpus_max_year(graph: Graph) -> int:
    """Newest year anywhere in the graph, concepts and papers alike."""
    years = [
        y
        for _, data in graph.nodes(data=True)
        if (y := (data.get("year") or data.get("first_seen_year"))) is not None
    ]
    return max(years) if years else 0


def structural_gaps(
    graph: Graph | None,
    min_age: int = STRUCTURAL_GAP_MIN_AGE,
) -> list[StructuralGap]:
    """Old concepts that nothing in the corpus builds on.

    The spec's rule, exactly: a concept with very few `EXTENDS` edges pointing
    at it *despite being old* is an abandoned or under-explored direction. Old
    is measured against the corpus's own span, so the same corpus does not start
    reporting gaps just because the calendar year moved on, and a recent corpus
    is not treated as having no history to abandon.

    Accepts a missing graph: stated gaps do not depend on the graph, and a report
    that refuses to run without one would hide the gaps it can establish.
    """
    if graph is None:
        return []
    cutoff = _corpus_max_year(graph) - min_age
    gaps: list[StructuralGap] = []
    for node, data in graph.nodes(data=True):
        if data.get("type") != str(NodeType.CONCEPT):
            continue
        year = year_of(graph, node)
        if not year or year > cutoff:
            continue
        degree = _lineage_in_degree(graph, node)
        if degree > 0:
            continue
        papers = [
            n
            for n in graph.predecessors(node)
            if graph.nodes[n].get("type") == str(NodeType.PAPER)
        ]
        gaps.append(
            StructuralGap(
                concept_id=node,
                name=str(data.get("name") or data.get("label") or node),
                year=year,
                in_degree=degree,
                papers=sorted(papers),
                reason=(
                    f"first seen {year}, {min_age}+ years before the corpus ends; "
                    "no concept in the corpus extends or replaces it"
                ),
            )
        )
    gaps.sort(key=lambda g: (-(g.year or 0), g.name))
    for index, gap in enumerate(gaps, start=1):
        gap.label = f"S{index}"
    return gaps


# -- 4. ranking ----------------------------------------------------------------


@dataclass(slots=True)
class RankedGap:
    key: str
    kind: str
    title: str
    score: float
    citations: list[str] = field(default_factory=list)
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "score": round(self.score, 3),
            "citations": self.citations,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def rank_gaps(
    themes: Sequence[Theme],
    structural: Sequence[StructuralGap],
    current_year: int = 2026,
) -> list[RankedGap]:
    """Order every gap by recency and frequency.

    Frequency is worth a lot but not unbounded: once several papers say the same
    thing, more repetitions stop being evidence that the problem is open and
    start being evidence that the field has noticed it. Hence the log cap.
    """
    ranked: list[RankedGap] = []
    for theme in themes:
        weight = min(theme.count, _SATURATION_AT)
        recency = ((theme.newest_year or 0) - 2000) / 30.0
        ranked.append(
            RankedGap(
                key=f"theme:{theme.name}",
                kind="stated",
                title=theme.name.replace("_", " "),
                score=weight + max(0.0, recency),
                citations=theme.labels,
                detail=f"{theme.count} paper(s) state a limitation in this theme",
                evidence=[r.limitation for r in theme.rows],
            )
        )
    for gap in structural:
        recency = ((gap.year or 0) - 2000) / 30.0
        ranked.append(
            RankedGap(
                key=f"structural:{gap.concept_id}",
                kind="structural",
                title=gap.name,
                score=1.0 + max(0.0, recency),
                citations=[gap.label],
                detail=gap.reason,
            )
        )
    ranked.sort(key=lambda g: (-g.score, g.kind, g.title))
    return ranked


# -- 5. suppression ------------------------------------------------------------

#: Phrases signalling that a later paper is answering an earlier paper's complaint.
_CLOSURE_MARKERS = (
    "addresses",
    "we address",
    "overcomes",
    "solves",
    "resolves",
    "our method handles",
    "in contrast to",
    "unlike prior",
    "improves upon",
    "mitigates",
)


def _closure_signals(text: str) -> set[str]:
    """Content words that, shared with a gap, suggest the gap was answered."""
    lowered = text.lower()
    if not any(marker in lowered for marker in _CLOSURE_MARKERS):
        return set()
    words = set(re.findall(r"[a-z][a-z-]{3,}", lowered))
    return {w for w in words if w not in _CLOSURE_MARKERS and len(w) > 4}


def suppress_closed(
    ranked: Sequence[RankedGap],
    extractions: Sequence[Extraction],
    papers: dict[str, Paper] | None = None,
    rows: Sequence[LimitationRow] = (),
) -> tuple[list[RankedGap], list[RankedGap]]:
    """Drop stated gaps a later in-corpus paper has already answered.

    Only within-corpus evidence counts, since the corpus is all we can cite. A
    stated gap counts as closed when a strictly newer paper carries an explicit
    closure marker ("we address", "overcomes", ...) and shares two or more content
    words with the gap. Requiring the marker is what stops a paper that merely
    happens to use the same vocabulary from silently erasing an open problem.

    A paper that states no limitation is still eligible to close a gap: the
    method that fixes someone else's problem is usually the one not complaining
    about one of its own.

    Structural gaps are passed through untouched, since a mention is not lineage.
    """
    titles = papers or {}
    years = {p.id: p.year for p in titles.values()}
    rows_by_label = {r.label: r for r in rows}
    order = sorted(extractions, key=lambda e: (years.get(e.paper_id) or 0, e.paper_id))

    keep: list[RankedGap] = []
    closed: list[RankedGap] = []
    for gap in ranked:
        if gap.kind != "stated":
            # Structural gaps are graph-derived: they say nothing in the corpus
            # builds on a concept. A later paper's abstract mentioning that
            # concept does not change that, and closing one on a title match
            # would erase real evidence of neglect. A structural gap is resolved
            # by an EXTENDS edge appearing, which raises its in-degree.
            keep.append(gap)
            continue
        gap_text = " ".join([gap.title, gap.detail, *gap.evidence]).lower()
        gap_words = set(re.findall(r"[a-z][a-z-]{3,}", gap_text))

        # The gap is as recent as the newest paper that raised it.
        source_rows = [rows_by_label[c] for c in gap.citations if c in rows_by_label]
        source_years = [r.year for r in source_rows if r.year]
        latest = max(source_years) if source_years else None

        closure: RankedGap | None = None
        for extraction in order:
            paper_year = years.get(extraction.paper_id)
            if source_rows and any(r.paper_id == extraction.paper_id for r in source_rows):
                continue  # a paper cannot answer its own complaint
            if (
                latest is not None
                and paper_year is not None
                and paper_year <= latest
            ):
                continue
            text = " ".join(
                [
                    titles[extraction.paper_id].title if extraction.paper_id in titles else "",
                    _summary_of(extraction),
                ]
            )
            shared = _closure_signals(text) & gap_words
            if len(shared) >= 2:
                closure = RankedGap(
                    key=f"closed:{gap.key}",
                    kind="closed",
                    title=gap.title,
                    score=0.0,
                    citations=[extraction.paper_id],
                    detail=(
                        f"closed by {titles[extraction.paper_id].title!r}"
                        if extraction.paper_id in titles
                        else "closed by a later in-corpus paper"
                    ),
                    evidence=sorted(shared),
                )
                break
        if closure is not None:
            closed.append(closure)
        else:
            keep.append(gap)
    return keep, closed


def _summary_of(extraction: Extraction) -> str:
    return extraction.summary or ""


# -- the report ---------------------------------------------------------------


@dataclass(slots=True)
class GapReport:
    rows: list[LimitationRow] = field(default_factory=list)
    themes: list[Theme] = field(default_factory=list)
    structural: list[StructuralGap] = field(default_factory=list)
    ranked: list[RankedGap] = field(default_factory=list)
    closed: list[RankedGap] = field(default_factory=list)
    papers_with_limitations: int = 0
    papers_considered: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "papers_considered": self.papers_considered,
            "papers_with_limitations": self.papers_with_limitations,
            "per_paper": [r.to_dict() for r in self.rows],
            "themes": [t.to_dict() for t in self.themes],
            "structural": [g.to_dict() for g in self.structural],
            "gaps": [g.to_dict() for g in self.ranked],
            "suppressed": [g.to_dict() for g in self.closed],
        }

    def citation_index(self) -> dict[str, str]:
        """Map every emitted label to the text it stands for."""
        index = {r.label: r.limitation for r in self.rows}
        index.update({g.label: g.name for g in self.structural})
        return index


def build_gap_report(
    extractions: Sequence[Extraction],
    graph: Graph | None,
    papers: Sequence[Paper] | None = None,
    current_year: int = 2026,
) -> GapReport:
    """All five stages, in order. Pure: no I/O, no model calls."""
    by_id = {p.id: p for p in (papers or [])}
    rows = paper_table(extractions, by_id)
    themes = cluster_themes(rows)
    structural = structural_gaps(graph)
    ranked = rank_gaps(themes, structural, current_year)
    keep, closed = suppress_closed(ranked, extractions, by_id, rows)
    return GapReport(
        rows=rows,
        themes=themes,
        structural=structural,
        ranked=keep,
        closed=closed,
        papers_with_limitations=len(rows),
        papers_considered=len(extractions),
    )


def render_report(report: GapReport) -> str:
    """Markdown for `rla report`. Every claim line carries a citation label."""
    out: list[str] = ["# Research gaps", ""]

    out.append("## What the corpus covers")
    out.append("")
    out.append(
        f"{report.papers_considered} paper(s) analysed; "
        f"{report.papers_with_limitations} state a limitation of their own method."
    )
    out.append("")

    out.append("## Per-paper stated limitations")
    out.append("")
    out.append(render_table(report.rows))
    out.append("")

    out.append("## Synthesised gaps, ranked")
    out.append("")
    if not report.ranked:
        out.append("_No gap could be grounded in this corpus._")
    else:
        for index, gap in enumerate(report.ranked, start=1):
            cites = " ".join(f"[{c}]" for c in gap.citations)
            out.append(f"{index}. **{gap.title}** ({gap.kind}) {cites}")
            out.append(f"   - {gap.detail}")
            if gap.evidence:
                out.append(f"   - evidence: {_cell(gap.evidence[0], 240)}")
        out.append("")

    if report.closed:
        out.append("## Suppressed as already addressed")
        out.append("")
        for gap in report.closed:
            out.append(f"- **{gap.title}**: {gap.detail}")
        out.append("")

    return "\n".join(out)


def report_stats(report: GapReport) -> dict[str, Any]:
    return {
        "papers_considered": report.papers_considered,
        "papers_with_limitations": report.papers_with_limitations,
        "themes": len(report.themes),
        "structural": len(report.structural),
        "gaps": len(report.ranked),
        "suppressed": len(report.closed),
    }
