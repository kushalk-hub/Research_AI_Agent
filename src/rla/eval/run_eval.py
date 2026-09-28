"""`rla eval`: run the P8 comparison and write `eval/report.md`.

The gate has a clause in it that is easy to skip and hard to fake: "The
graph-vs-baseline delta is reported honestly even if unfavourable." So the rules
this module enforces are:

1. **Nothing is reported as measured when it was not.** Node/edge precision and
   recall require a hand-labelled reference set. The shipped set is not one, so
   the report says the numbers are unavailable and why, instead of printing a
   number derived from the pipeline's own output.
2. **Every score carries its judge kind.** A heuristic number is never presented
   as an LLM judgement, and the table shows which it is per row.
3. **Unfavourable results get the same prominence as favourable ones.** A
   refuted gap is a real finding and is reported first when it is the majority.
4. **Coverage is reported next to every mean.** A mean over 2 of 12 questions is
   not a mean over 12, and the denominator is stated.
5. **The comparison is symmetric.** Both arms are retrieved/scored the same way,
   and the evidence each is given is the same evidence.

What this can measure today, without any LLM budget:

- gap validity against 37 held-out papers (independent of the extractor)
- which papers each arm surfaces for each question (overlap, not quality)
- citation validity and citation support, mechanically, for both arms

What it cannot: LLM-judged correctness or completeness, and anything requiring
hand labels. Both are reported as gaps in the evaluation itself.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rla.config import Settings
from rla.eval.baseline_rag import (
    RagResult,
    evidence_text,
    paper_labels,
    retrieve,
)
from rla.eval.gap_validity import GapVerdict, Verdict, check_gap, split_held_out, summarise
from rla.eval.ground_truth import (
    ReferenceAssessment,
    assess_reference_set,
    empty_template,
    load_reference_set,
    render_template,
)
from rla.eval.judge import (
    AnswerScore,
    HeuristicJudge,
    Judge,
    JudgeKind,
    aggregate,
    coverage,
)
from rla.eval.metrics import EdgeKey, ExtractionScores, score_extraction
from rla.models import Corpus, EdgeType, Paper
from rla.pipeline.gaps import GapReport, build_gap_report
from rla.store.extraction_store import ExtractionStore
from rla.store.graph_store import Graph
from rla.store.graph_store import load as load_graph

#: The evaluation question set. Kept in code, not data, so it is reviewable in a
#: diff and cannot be quietly swapped for questions the system happens to do well
#: on. Every one is answerable from the 26 extracted papers.
EVAL_QUESTIONS: tuple[str, ...] = (
    "What is graph attention and which papers introduce it?",
    "How does attention get used across graph agent architectures?",
    "Which concepts does this work combine to build multi-agent systems?",
    "What did early work on agent graphs lead to?",
    "How are agents represented as graphs?",
    "Which papers use both attention and graph neural networks?",
    "How do multi-agent systems handle large graphs?",
    "What open problems are reported for graph-based agents?",
    "Which concepts appeared earliest in this literature?",
    "What does the graph say about reinforcement learning for agents?",
    "How do recent papers build on earlier agent architectures?",
    "Which methods are combined rather than extended?",
)

#: Concepts whose understudy the gap analysis flags; checked against held-out
#: papers. Read off the live report rather than hard-coded, in `run_eval`.
DEFAULT_TOP_K = 5


@dataclass
class ArmResult:
    """One system's answer to one question, plus the evidence it was given."""

    system: str
    question: str
    answer: str
    evidence: str
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "question": self.question,
            "answer": self.answer,
            "citations": list(self.citations),
        }


@dataclass
class ComparisonRow:
    """One rubric dimension, graph arm against baseline arm."""

    dimension: str
    judge_kind: JudgeKind
    graph_value: float | None
    rag_value: float | None
    graph_coverage: float
    rag_coverage: float
    mechanical: bool

    @property
    def delta(self) -> float | None:
        """graph - rag. None when either side is unscored."""
        if self.graph_value is None or self.rag_value is None:
            return None
        return self.graph_value - self.rag_value

    @property
    def favours(self) -> str:
        """Which arm the delta favours, stated plainly either way."""
        d = self.delta
        if d is None:
            return "not comparable"
        if abs(d) < 1e-9:
            return "tie"
        return "graph" if d > 0 else "baseline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "judge_kind": str(self.judge_kind),
            "graph": None if self.graph_value is None else round(self.graph_value, 4),
            "rag": None if self.rag_value is None else round(self.rag_value, 4),
            "delta": None if self.delta is None else round(self.delta, 4),
            "favours": self.favours,
            "graph_coverage": round(self.graph_coverage, 3),
            "rag_coverage": round(self.rag_coverage, 3),
            "mechanical": self.mechanical,
        }


@dataclass
class EvalReport:
    """The whole evaluation, in one object the CLI and the markdown both read."""

    generated_at: str
    corpus_papers: int
    extracted_papers: int
    held_out_papers: int
    graph_nodes: int
    graph_edges: int
    reference: ReferenceAssessment
    extraction_scores: ExtractionScores
    comparisons: list[ComparisonRow] = field(default_factory=list)
    gap_verdicts: list[GapVerdict] = field(default_factory=list)
    question_count: int = 0
    judge_kind: JudgeKind = JudgeKind.HEURISTIC
    #: What the evaluation could not do, in the report's own words.
    limitations: list[str] = field(default_factory=list)
    #: Paper ids both arms surfaced, per question. Overlap is not quality.
    overlap: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "corpus_papers": self.corpus_papers,
            "extracted_papers": self.extracted_papers,
            "held_out_papers": self.held_out_papers,
            "graph": {"nodes": self.graph_nodes, "edges": self.graph_edges},
            "reference": self.reference.to_dict(),
            "extraction": self.extraction_scores.to_dict(),
            "judge_kind": str(self.judge_kind),
            "questions": self.question_count,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "gap_validity": {
                "summary": summarise(self.gap_verdicts),
                "verdicts": [v.to_dict() for v in self.gap_verdicts],
            },
            "limitations": list(self.limitations),
        }


def _graph_concept_names(graph: Graph) -> list[str]:
    return [
        str(data.get("name"))
        for _, data in graph.nodes(data=True)
        if data.get("type") == "Concept" and data.get("name")
    ]


def _graph_edges(graph: Graph, paper_ids: set[str]) -> list[EdgeKey]:
    """Predicted edges, with concept endpoints as names so they can be matched."""
    names: dict[str, str] = {}
    for node, data in graph.nodes(data=True):
        if data.get("type") == "Concept" and data.get("name"):
            names[node] = str(data["name"])
    edges: list[EdgeKey] = []
    for source, target, data in graph.edges(data=True):
        edge_type = data.get("type")
        try:
            kind = EdgeType(edge_type)
        except ValueError:
            continue  # an unknown type is a data problem, not a metric
        if kind is EdgeType.CITES:
            # Citation edges come from metadata and are ground truth by
            # construction; scoring them against a hand-labelled set would
            # measure the labeler, not the extractor.
            continue
        if source in names and target in names:
            edges.append(EdgeKey(names[source], names[target], kind))
        elif source in paper_ids or target in paper_ids:
            paper = source if source in paper_ids else target
            concept = target if source in paper_ids else source
            if concept in names:
                edges.append(EdgeKey(paper, names[concept], kind))
    return edges


def build_comparison(
    graph_scores: Sequence[AnswerScore],
    rag_scores: Sequence[AnswerScore],
    judge_kind: JudgeKind,
) -> list[ComparisonRow]:
    """One row per dimension, over dimensions both arms were asked for."""
    dimensions: list[str] = []
    for score in [*graph_scores, *rag_scores]:
        for name in score.scores:
            if name not in dimensions:
                dimensions.append(name)

    rows: list[ComparisonRow] = []
    for dimension in dimensions:
        mechanical = any(
            s.scores[dimension].mechanical
            for s in [*graph_scores, *rag_scores]
            if dimension in s.scores
        )
        rows.append(
            ComparisonRow(
                dimension=dimension,
                judge_kind=judge_kind,
                graph_value=aggregate(graph_scores, dimension),
                rag_value=aggregate(rag_scores, dimension),
                graph_coverage=coverage(graph_scores, dimension),
                rag_coverage=coverage(rag_scores, dimension),
                mechanical=mechanical,
            )
        )
    return rows


def run_eval(
    settings: Settings,
    *,
    questions: Sequence[str] = EVAL_QUESTIONS,
    top_k: int = DEFAULT_TOP_K,
    judge: Judge | None = None,
    reference_path: Path | None = None,
    max_gaps: int = 8,
) -> EvalReport:
    """Run every check that can run, and report the ones that cannot."""
    settings.ensure_dirs()
    judge = judge or HeuristicJudge()
    corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
    graph = load_graph(settings.graph_json)

    store = ExtractionStore(settings.extractions_path)
    store.load()
    extractions = store.all()
    extracted_ids = {e.paper_id for e in extractions}

    paper_ids = {p.id for p in corpus.papers}
    extracted_ids, held_out_ids = split_held_out(paper_ids, extracted_ids)
    held_out = [p for p in corpus.papers if p.id in held_out_ids]

    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    # --- reference set and extraction accuracy -----------------------------
    ref_path = reference_path or (Path("eval") / "ground_truth.json")
    if ref_path.exists():
        reference = load_reference_set(ref_path)
    else:
        reference = empty_template()
    assessment = assess_reference_set(reference)

    if graph is None:
        graph_nodes = graph_edges = 0
        predicted_names: list[str] = []
        predicted_edges: list[EdgeKey] = []
    else:
        graph_nodes, graph_edges = graph.number_of_nodes(), graph.number_of_edges()
        predicted_names = _graph_concept_names(graph)
        predicted_edges = _graph_edges(graph, paper_ids)

    extraction_scores = score_extraction(
        predicted_names,
        predicted_edges,
        list(reference.concept_names()),
        [EdgeKey(e.source, e.target, e.type) for e in reference.edges],
        predicted_paper_ids=paper_ids,
        reference=reference,
    )

    # --- both arms over the same questions ----------------------------------
    graph_scores: list[AnswerScore] = []
    rag_scores: list[AnswerScore] = []
    overlap: dict[str, list[str]] = {}
    #: The shared citation vocabulary. Both arms label papers the same way so the
    #: judge checks retrieval, not label formatting.
    labels = paper_labels(sorted(extracted_ids))

    for question in questions:
        rag: RagResult = retrieve(
            question, corpus.papers, top_k=top_k, allow=extracted_ids
        )
        rag_evidence = evidence_text(rag, labels)
        rag_citations = [labels[h.paper_id] for h in rag.hits if h.paper_id in labels]
        rag_scores.append(
            judge.score(
                "rag-over-abstracts", question, rag_evidence, rag_evidence, rag_citations
            )
        )

        graph_answer, graph_evidence, graph_cites, graph_paper_ids = _graph_answer(
            graph, question, labels
        )
        graph_scores.append(
            judge.score(
                "graph", question, graph_answer, graph_evidence, graph_cites
            )
        )
        rag_ids = {h.paper_id for h in rag.hits}
        overlap[question] = sorted(rag_ids & graph_paper_ids)

    # --- gap validity against held-out papers ------------------------------
    gap_verdicts: list[GapVerdict] = []
    if graph is not None:
        gap_verdicts = _check_top_gaps(
            graph, settings, held_out, max_gaps=max_gaps
        )

    report = EvalReport(
        generated_at=generated_at,
        corpus_papers=len(corpus.papers),
        extracted_papers=len(extracted_ids),
        held_out_papers=len(held_out),
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        reference=assessment,
        extraction_scores=extraction_scores,
        comparisons=build_comparison(graph_scores, rag_scores, judge.kind),
        gap_verdicts=gap_verdicts,
        question_count=len(questions),
        judge_kind=judge.kind,
        overlap=overlap,
    )
    report.limitations = _limitations(report, held_out)
    return report


def _graph_answer(
    graph: Graph | None,
    question: str,
    labels: dict[str, str],
) -> tuple[str, str, list[str], set[str]]:
    """The graph arm's answer, built from traversal over the extracted subgraph.

    Traversal emits its own `[P1]`/`[C2]` labels scoped to one question, which
    would collide with the baseline's labels for different papers. So the subgraph
    is re-emitted under the shared vocabulary: papers by the label the baseline
    uses for the same id, concepts by their own `[C..]` label. Without this the
    judge resolves the graph arm's citations against papers it was never shown, and
    scores label format instead of retrieval.

    Returns the answer, the evidence, the citable labels, and the paper ids behind
    them, so the caller can measure overlap with the baseline by id.
    """
    from rla.pipeline.traverse import traverse

    if graph is None or not labels:
        return "", "", [], set()
    sub = traverse(graph, question)

    lines: list[str] = []
    citations: list[str] = []
    paper_ids: set[str] = set()
    for node in sub.nodes:
        year = f" ({node.year})" if node.year else ""
        if node.type == "paper":
            shared = labels.get(node.node_id)
            if shared is None:
                continue  # outside the labelled vocabulary, so not citable
            citations.append(shared)
            paper_ids.add(node.node_id)
            lines.append(f"[{shared}] {node.name}{year}")
        else:
            lines.append(f"[{node.label}] {node.name}{year}")
    evidence = "\n".join(lines)
    return evidence, evidence, sorted(set(citations)), paper_ids


def _concept_years(graph: Graph) -> dict[str, int | None]:
    """Concept name -> first-seen year, for the gap-validity newer-than check."""
    years: dict[str, int | None] = {}
    for _, data in graph.nodes(data=True):
        if data.get("type") == "Concept" and data.get("name"):
            years[str(data["name"])] = data.get("first_seen_year")
    return years


def _check_top_gaps(
    graph: Graph,
    settings: Settings,
    held_out: Sequence[Paper],
    max_gaps: int,
) -> list[GapVerdict]:
    """Check the structural gaps against the held-out set.

    Only structural gaps are testable, and the reason is structural rather than
    incidental: a structural gap is "this concept is old and thinly connected", so
    it names a concept that can be looked for in later papers. A ranked stated gap
    is a theme synthesised from limitations prose -- a phrase, not a concept -- so
    matching it against titles is not the same test and is not attempted.

    Stated gaps are not silently dropped, though: `reported_but_unchecked` records
    how many were left out so the report can say so.
    """
    store = ExtractionStore(settings.extractions_path)
    store.load()
    gap_report: GapReport = build_gap_report(store.all(), graph)

    years = _concept_years(graph)
    verdicts: list[GapVerdict] = []
    for gap in gap_report.structural[:max_gaps]:
        if gap.name not in years:
            continue
        verdicts.append(check_gap(gap.name, held_out, years.get(gap.name) or gap.year))
    return verdicts


def _limitations(report: EvalReport, held_out: Sequence[Paper]) -> list[str]:
    """What this run could not do, stated in the report and not buried."""
    items: list[str] = []
    if not report.extraction_scores.measured:
        items.append(
            "Node/edge precision and recall are NOT reported. The reference set is "
            "not hand-labelled, so a number computed against it would measure the "
            "generator against itself. See the reference-set section."
        )
    else:
        items.append(
            f"Reference set covers {report.reference.papers} paper(s) against a "
            "target of 20, so recall rests on few items."
        )
    if report.judge_kind is JudgeKind.HEURISTIC:
        items.append(
            "No LLM judge ran: the Gemini free tier is a per-model daily cap and it is "
            "spent. Correctness and completeness are therefore not scored at all. The "
            "citation numbers are mechanical and are labelled as such; they are not "
            "substitutes for a judge's opinion."
        )
    if report.held_out_papers == 0:
        items.append(
            "There are no held-out papers, so gap validity could not be checked."
        )
    if not report.overlap or not any(report.overlap.values()):
        items.append(
            "The two arms never surfaced the same paper for any question. That is a "
            "finding about the two retrieval strategies, not a quality result."
        )
    items.append(
        "The baseline is retrieval-only. It retrieves and shows abstracts; it does not "
        "generate an answer, because generating one needs the same LLM budget that is "
        "unavailable. The graph arm is likewise given its subgraph as text. This is a "
        "comparison of retrieved evidence, not of answer quality."
    )
    return items


# -- rendering -----------------------------------------------------------------


def render_table(report: EvalReport) -> str:
    """The comparison table, as plain text, for the terminal.

    Unfavourable deltas are not hidden, sorted away, or footnoted: the graph arm's
    losses are printed in the same column layout as its wins.
    """
    width = 74
    out: list[str] = []
    out.append("=" * width)
    out.append("rla eval - graph vs RAG-over-abstracts")
    out.append("=" * width)
    out.append(
        f"corpus {report.corpus_papers} papers | extracted {report.extracted_papers} "
        f"| held out {report.held_out_papers}"
    )
    out.append(
        f"graph {report.graph_nodes} nodes / {report.graph_edges} edges | "
        f"{report.question_count} questions | judge: {report.judge_kind}"
    )
    out.append("")

    out.append("Retrieved-evidence comparison (mean over questions)")
    out.append("-" * width)
    header = f"{'dimension':<20}{'graph':>8}{'rag':>8}{'delta':>8}  favours"
    out.append(header)
    for row in report.comparisons:
        graph_v = "-" if row.graph_value is None else f"{row.graph_value:.3f}"
        rag_v = "-" if row.rag_value is None else f"{row.rag_value:.3f}"
        delta = "-" if row.delta is None else f"{row.delta:+.3f}"
        mark = "" if row.mechanical else " (judged)"
        out.append(
            f"{row.dimension:<20}{graph_v:>8}{rag_v:>8}{delta:>8}  {row.favours}{mark}"
        )
    out.append("")

    out.append("Gap validity against held-out papers")
    out.append("-" * width)
    if not report.gap_verdicts:
        out.append("no gaps were available to check")
    else:
        summary = summarise(report.gap_verdicts)
        out.append(
            f"{summary['gaps']} gap(s): {summary['refuted']} refuted, "
            f"{summary['confirmed']} confirmed, {summary['no_signal']} no signal, "
            f"{summary['not_testable']} not testable"
        )
        rate = summary.get("refuted_rate")
        if rate is not None:
            out.append(
                f"refuted rate over testable gaps: {rate:.0%} "
                "(higher means the gap analysis is doing worse)"
            )
        out.append("")
        # Refutations first: a finding that counts against the system should not be
        # below the fold behind the ones that flatter it.
        ordered = sorted(
            report.gap_verdicts,
            key=lambda v: (v.verdict is not Verdict.REFUTED, v.concept),
        )
        for verdict in ordered:
            out.append(f"  [{verdict.verdict}] {verdict.concept}")
            for match in verdict.matches[:3]:
                out.append(f"      {match.year}  {match.title[:60]}  ({match.score:.1f})")
    out.append("")

    out.append("Extraction accuracy")
    out.append("-" * width)
    if not report.extraction_scores.measured:
        out.append("  NOT MEASURED")
        for blocker in assessment_blockers(report):
            out.append(f"  - {blocker}")
    else:
        for score in (
            report.extraction_scores.nodes,
            report.extraction_scores.concept_edges,
            report.extraction_scores.paper_concept_edges,
        ):
            out.append(f"  {score.name}: {score.to_dict()}")
    out.append("")

    out.append("Limitations of this run")
    out.append("-" * width)
    for item in report.limitations:
        out.append(f"  - {item}")
    out.append("=" * width)
    return "\n".join(out)


def assessment_blockers(report: EvalReport) -> list[str]:
    return [
        f"reference set '{report.reference.set_name}' has "
        f"{report.reference.hand_labelled_fraction:.0%} hand-labelled items"
    ]


def render_markdown(report: EvalReport) -> str:
    """`eval/report.md`."""
    out: list[str] = []
    out.append("# P8 evaluation")
    out.append("")
    out.append(f"Generated {report.generated_at}.")
    out.append("")
    out.append("## Setup")
    out.append("")
    out.append(f"- Corpus: **{report.corpus_papers}** papers acquired")
    out.append(
        f"- Extracted into the graph: **{report.extracted_papers}** "
        "(the bounded set; re-extraction is not run because the Gemini free tier is a "
        "per-model daily cap and it is spent)"
    )
    out.append(
        f"- Held out of extraction, used as the gap-validity set: **{report.held_out_papers}**"
    )
    out.append(f"- Graph: **{report.graph_nodes}** nodes, **{report.graph_edges}** edges")
    out.append(f"- Questions: **{report.question_count}**")
    out.append(f"- Judge: **{report.judge_kind}**")
    out.append("")

    out.append("## Graph vs RAG-over-abstracts")
    out.append("")
    if report.comparisons:
        out.append("| dimension | graph | rag | delta | favours | kind | coverage (graph/rag) |")
        out.append("|---|---|---|---|---|---|---|")
        for row in report.comparisons:
            graph_v = "-" if row.graph_value is None else f"{row.graph_value:.3f}"
            rag_v = "-" if row.rag_value is None else f"{row.rag_value:.3f}"
            delta = "-" if row.delta is None else f"{row.delta:+.3f}"
            kind = "mechanical" if row.mechanical else f"{report.judge_kind}"
            out.append(
                f"| {row.dimension} | {graph_v} | {rag_v} | {delta} | {row.favours} "
                f"| {kind} | {row.graph_coverage:.0%} / {row.rag_coverage:.0%} |"
            )
    else:
        out.append("_No comparable dimensions: nothing was scored for either arm._")
    out.append("")

    out.append("### Reading this table")
    out.append("")
    out.append(
        "The delta column is `graph - rag`. A **negative** delta means the baseline "
        "did better on that dimension, and those rows are left in place deliberately: "
        "a comparison that only shows wins is not a comparison."
    )
    out.append(
        "The `kind` column says how each number was produced. `mechanical` means a "
        "deterministic check; anything else was a judge's opinion. Coverage states how "
        "many of the questions produced a number at all, because a mean over a subset "
        "is not the same measurement as a mean over all of them."
    )
    out.append("")

    out.append("## Gap validity against held-out papers")
    out.append("")
    if report.gap_verdicts:
        summary = summarise(report.gap_verdicts)
        out.append(
            f"{summary['gaps']} gap(s) checked: **{summary['refuted']} refuted**, "
            f"{summary['confirmed']} confirmed, {summary['no_signal']} no signal, "
            f"{summary['not_testable']} not testable."
        )
        rate = summary.get("refuted_rate")
        if rate is not None:
            out.append("")
            out.append(
                f"**Refuted rate: {rate:.0%}** of testable gaps. A high refuted rate "
                "means the gap analysis is flagging concepts that later work already "
                "addressed, which is a result against it."
            )
        out.append("")
        out.append("| concept | verdict | held-out papers engaging it |")
        out.append("|---|---|---|")
        ordered = sorted(
            report.gap_verdicts,
            key=lambda v: (v.verdict is not Verdict.REFUTED, v.concept),
        )
        for verdict in ordered:
            titles = "; ".join(
                f"{m.year} {m.title[:40]} ({m.score:.1f})" for m in verdict.matches[:2]
            )
            out.append(f"| {verdict.concept} | {verdict.verdict} | {titles or '-'} |")
        out.append("")
        for verdict in ordered:
            out.append(f"- **{verdict.concept}** ({verdict.verdict}): {verdict.note}")
        out.append("")
    else:
        out.append("_No gaps were available to check._")
        out.append("")

    out.append("## Extraction accuracy")
    out.append("")
    if report.extraction_scores.measured:
        out.append("| set | tp | fp | fn | precision | recall | f1 |")
        out.append("|---|---|---|---|---|---|---|")
        for score in (
            report.extraction_scores.nodes,
            report.extraction_scores.concept_edges,
            report.extraction_scores.paper_concept_edges,
        ):
            d = score.to_dict()
            p = "-" if d["precision"] is None else f"{d['precision']:.3f}"
            r = "-" if d["recall"] is None else f"{d['recall']:.3f}"
            f = "-" if d["f1"] is None else f"{d['f1']:.3f}"
            out.append(
                f"| {d['name']} | {d['true_positives']} | {d['false_positives']} "
                f"| {d['false_negatives']} | {p} | {r} | {f} |"
            )
    else:
        out.append("**Not measured.**")
        out.append("")
        out.append(f"> {report.extraction_scores.not_scored_reason}")
        out.append("")
        out.append(
            "To measure this, fill in `eval/ground_truth.json` by reading the abstracts "
            "and recording the concepts each paper is about and the relations between "
            "them. `rla eval --init-ground-truth` writes a blank form."
        )
    out.append("")

    out.append("## Reference set")
    out.append("")
    out.append(f"- Set: `{report.reference.set_name}`")
    out.append(
        f"- Hand-labelled items: **{report.reference.hand_labelled_fraction:.0%}** "
        f"({report.reference.nodes} nodes, {report.reference.edges} edges)"
    )
    out.append(f"- Papers labelled: **{report.reference.papers}**")
    for blocker in report.reference.blockers:
        out.append(f"- **Blocker:** {blocker}")
    for warning in report.reference.warnings:
        out.append(f"- Warning: {warning}")
    out.append("")

    out.append("## Limitations of this run")
    out.append("")
    for item in report.limitations:
        out.append(f"- {item}")
    out.append("")

    out.append("## What a follow-up run should change")
    out.append("")
    out.append(
        "1. Hand-label 20 papers, then re-run for real node/edge precision and recall."
    )
    out.append(
        "2. Give both arms an LLM -- the same model, the same evidence, the same "
        "rubric -- so correctness and completeness can be scored as judgements "
        "rather than as citation support."
    )
    out.append(
        "3. Compare generated answers, not retrieved evidence, once 2 is possible."
    )
    return "\n".join(out) + "\n"


def write_report(report: EvalReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def write_json(report: EvalReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def init_ground_truth(path: Path) -> Path:
    """Write a blank hand-labelling form, refusing to overwrite real work."""
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text("utf-8"))
        existing = data.get("nodes") or data.get("edges")
        if existing:
            raise ValueError(
                f"{path} already contains {len(data.get('nodes') or [])} node(s) and "
                f"{len(data.get('edges') or [])} edge(s). Refusing to overwrite "
                "hand-labelling work in progress."
            )
    render_template(empty_template(), path)
    return path
