"""The event reducer behind the TUI (P7).

The gate says the TUI must show all phases live, with running counters and no
freeze. The widgets are untestable without a terminal, so the behaviour under
test lives in `PipelineState`, which is pure. These tests fold real-shaped event
streams through it and assert what the UI would render.

The cases that matter are the ones where a plausible implementation is quietly
wrong: a counter that increments per log line, an event arriving out of phase
order, a traversal tree that drops papers.
"""

from __future__ import annotations

from rla.events import PIPELINE_PHASES, Event, Phase, event
from rla.tui.state import MAX_LOG_LINES, STATUS_PHASES, PipelineState, _abbreviate

# -- a realistic stream --------------------------------------------------------

GRAPH_STATS = {"nodes": 90, "edges": 35, "nodes_Paper": 63, "nodes_Concept": 27}

SUBGRAPH = {
    "question": "how did GAT evolve?",
    "question_type": "lineage",
    "nodes": [
        {"id": "c:gat", "label": "C1", "type": "concept", "name": "GAT", "year": 2018},
        {"id": "c:agent", "label": "C2", "type": "concept", "name": "agent graphs", "year": 2024},
        {"id": "p1", "label": "P1", "type": "paper", "name": "GAT paper", "year": 2018},
        {"id": "p2", "label": "P2", "type": "paper", "name": "Graph-of-Agents", "year": 2024},
    ],
    # `EXTENDS` runs parent -> child, and the parent must be the older concept:
    # GAT (2018) is the ancestor of agent graphs (2024), not the other way round.
    "edges": [
        {"source": "c:gat", "target": "p1", "type": "USES"},
        {"source": "c:gat", "target": "c:agent", "type": "EXTENDS"},
        {"source": "c:agent", "target": "p2", "type": "USES"},
    ],
    "notes": [],
    "seeds": ["c:gat"],
    "stats": {"nodes": 4, "edges": 3, "papers": 2, "concepts": 2, "EXTENDS": 1},
}


def full_stream() -> list[Event]:
    """One event of every kind the TUI has to survive, in phase order."""
    return [
        event(Phase.SEARCH, "Starting pipeline for 'graph RL'", sources=4),
        event(Phase.FETCH, "arxiv: 40 papers for 'graph RL'", source="arxiv"),
        event(Phase.FETCH, "Deduplicated to 63 unique papers", kind="ok", unique=63),
        event(Phase.SCORE, "Working corpus ready: 63 papers", kind="ok",
              papers=63, with_abstract=61),
        event(Phase.FULLTEXT, "fulltext stage pending", kind="pending"),
        event(Phase.EXTRACT, "Extracting 20 papers (6 already extracted)", pending=20, reused=6),
        event(Phase.EXTRACT, "1/20 arxiv:1234.5678: 4 concepts", kind="ok",
              concepts=4, limitations=1),
        event(Phase.EXTRACT, "2/20 arxiv:2234.5678: 3 concepts", kind="ok",
              concepts=3, limitations=0),
        event(Phase.EXTRACT, "Extracted 20/20 papers", kind="ok",
              extracted=20, total=20, concepts=19, limitations=7),
        event(Phase.RESOLVE, "27 concepts after resolution", kind="ok",
              concept_nodes=[{"id": f"c:{i}"} for i in range(27)], decisions=[{"a": 1}]),
        event(Phase.GRAPH, "90 nodes (63 papers, 27 concepts), 35 edges", kind="ok",
              stats=GRAPH_STATS),
        event(Phase.TRAVERSE, "subgraph selected: 4 nodes, 3 edges", kind="ok", **SUBGRAPH),
        event(Phase.ANSWER, "GAT ", kind="delta"),
        event(Phase.ANSWER, "became ", kind="delta"),
        event(Phase.ANSWER, "the basis for agent graphs [P1][C2].", kind="delta"),
        event(Phase.ANSWER, "Answer complete: 2 of 4 subgraph nodes cited", kind="ok",
              question_type="lineage", citations=["P1", "C2"], uncited=["C1", "P2"]),
        event(Phase.DONE, "Pipeline finished", kind="ok", cache={"hits": 12}),
    ]


# -- phase tracking ------------------------------------------------------------


def test_every_phase_in_the_status_bar_is_visited():
    state = PipelineState().apply_all(full_stream())
    seen = {p for p, _ in state.phase_states() if _ != "pending"}
    assert seen >= set(STATUS_PHASES) - {Phase.DONE}


def test_the_status_bar_covers_every_phase_the_pipeline_announces():
    """The gate says 'all phases live', and `rla events` lists the order.

    The bar must show every stage the orchestrator emits, so the two lists cannot
    quietly drift. ERROR is the one exclusion: it is an outcome, not a stage.
    """
    assert STATUS_PHASES == tuple(p for p in PIPELINE_PHASES if p is not Phase.ERROR)
    assert Phase.FULLTEXT in STATUS_PHASES, "the orchestrator announces it"
    assert Phase.ERROR not in STATUS_PHASES


def test_the_active_phase_advances_through_the_run():
    state = PipelineState()
    phases = []
    for evt in full_stream():
        state.apply(evt)
        if state.phase is not None:
            phases.append(state.phase)
    assert phases[0] is Phase.SEARCH
    assert phases[-1] is Phase.ANSWER


def test_done_ends_the_run_and_stops_moving_the_cursor():
    state = PipelineState().apply_all(full_stream())
    assert state.finished
    assert state.finished_at is not None
    # DONE is terminal: the cursor stays on the last real stage.
    assert state.phase is not Phase.DONE


def test_the_status_line_shows_every_phase():
    line = PipelineState().apply_all(full_stream()).status_line()
    for phase in STATUS_PHASES:
        assert str(phase) in line


def test_the_status_line_shows_the_markers_not_a_wall_of_names():
    state = PipelineState().apply_all(full_stream())
    line = state.status_line()
    assert ">" in line  # the active stage
    assert "+" in line  # stages already passed
    assert line.count(".") >= 1  # stages still to come


def test_a_run_with_no_events_leaves_the_bar_honest():
    state = PipelineState()
    assert state.phase is None
    assert state.status_line()


def test_an_out_of_order_event_does_not_reorder_history():
    """Events can interleave; the UI must show what arrived, not a fiction."""
    events = [
        event(Phase.SEARCH, "start"),
        event(Phase.GRAPH, "graph built", kind="ok", stats=GRAPH_STATS),
        event(Phase.FETCH, "arxiv: 3 papers"),
    ]
    state = PipelineState().apply_all(events)
    assert state.seen == [Phase.SEARCH, Phase.GRAPH, Phase.FETCH]
    assert state.phase is Phase.FETCH


# -- counters ------------------------------------------------------------------


def test_counters_track_graph_size():
    counters = PipelineState().apply_all(full_stream()).counter_summary()
    assert counters["nodes"] == 90
    assert counters["edges"] == 35
    assert counters["graph_papers"] == 63
    assert counters["graph_concepts"] == 27


def test_counters_track_extraction_progress():
    counters = PipelineState().apply_all(full_stream()).counter_summary()
    assert counters["extracted"] == 20
    assert counters["extract_total"] == 20
    assert counters["limitations"] == 7


def test_counters_track_corpus_size():
    counters = PipelineState().apply_all(full_stream()).counter_summary()
    assert counters["papers"] == 63


def test_counters_track_the_subgraph_not_the_whole_graph():
    counters = PipelineState().apply_all(full_stream()).counter_summary()
    assert counters["subgraph_nodes"] == 4
    assert counters["subgraph_edges"] == 3
    assert counters["nodes"] == 90, "the subgraph must not overwrite the graph size"


def test_a_per_item_event_does_not_increment_the_paper_count():
    """The bug this guards: counting log lines as extracted papers.

    Extraction emits one `ok` event per paper. If the reducer incremented on each
    one, a 20-paper run would report 47 papers extracted.
    """
    events = [event(Phase.EXTRACT, "Extracting 20 papers", pending=20)]
    events += [
        event(Phase.EXTRACT, f"{i}/20 paper: 3 concepts", kind="ok", concepts=3)
        for i in range(1, 21)
    ]
    state = PipelineState().apply_all(events)
    assert "extracted" not in state.counters
    assert state.counters["extract_total"] == 20


def test_a_later_summary_overrides_an_earlier_guess():
    events = [
        event(Phase.EXTRACT, "Extracting 20 papers", pending=20),
        event(Phase.EXTRACT, "Extracted 20/20 papers", kind="ok", extracted=20, total=20),
    ]
    state = PipelineState().apply_all(events)
    assert state.counters["extracted"] == 20


def test_the_done_event_does_not_clobber_known_counters():
    state = PipelineState().apply_all(full_stream())
    assert state.counters["nodes"] == 90


# -- the log -------------------------------------------------------------------


def test_the_log_holds_one_line_per_event():
    state = PipelineState().apply_all(full_stream())
    # Streamed deltas are answer text, not log lines, and DONE belongs to the
    # status bar, so neither is logged.
    assert len(state.log) == len(full_stream()) - 4


def test_streamed_answer_text_is_not_logged():
    state = PipelineState().apply_all(full_stream())
    assert not any("the basis for agent graphs" in line.message for line in state.log)
    assert "the basis for agent graphs" in state.answer


def test_the_log_is_capped_so_a_long_run_stays_responsive():
    state = PipelineState()
    # A 100-paper run emits hundreds of events; the UI shows the recent tail.
    for i in range(MAX_LOG_LINES + 200):
        state.apply(event(Phase.EXTRACT, f"paper {i}", kind="ok"))
    assert len(state.log) == MAX_LOG_LINES
    assert state.log[-1].message == f"paper {MAX_LOG_LINES + 199}"


def test_log_lines_carry_a_colour_per_kind():
    state = PipelineState().apply_all(full_stream())
    styles = {line.kind: line.style for line in state.log}
    assert styles["ok"] == "green"
    assert styles["pending"] == "dim"
    assert styles["info"] == "cyan"


# -- streamed answer -----------------------------------------------------------


def test_the_answer_streams_in_deltas():
    state = PipelineState().apply_all(full_stream())
    assert state.answer == "GAT became the basis for agent graphs [P1][C2]."
    assert state.answer_complete


def test_an_incomplete_answer_is_flagged():
    state = PipelineState()
    state.apply(event(Phase.ANSWER, "partial", kind="delta"))
    assert state.answer == "partial"
    assert not state.answer_complete


def test_the_answer_records_its_citations():
    state = PipelineState().apply_all(full_stream())
    assert state.citations == ["P1", "C2"]


def test_a_failed_answer_surfaces_the_error():
    state = PipelineState()
    state.apply(event(Phase.ANSWER, "the model returned nothing", kind="warn"))
    assert not state.answer_complete


# -- the traversal tree --------------------------------------------------------


def test_the_tree_is_rooted_at_the_ancestor_concept():
    """`C1 --EXTENDS--> C2` nests C2 under C1, so C1 is the only root."""
    tree = PipelineState().apply_all(full_stream()).tree()
    assert tree is not None
    assert [c.label for c in tree.children] == ["C1"]


def test_papers_attach_under_the_concept_they_touch():
    tree = PipelineState().apply_all(full_stream()).tree()
    c1 = tree.children[0]
    by_label = {c.label: c for c in [c1, *c1.children]}
    assert [c.label for c in by_label["C1"].children] == ["C2", "P1"]
    assert [c.label for c in by_label["C2"].children] == ["P2"]


def test_lineage_reads_oldest_concept_first():
    """The tree is a lineage, so the ancestor sits at the root, not the newest."""
    tree = PipelineState().apply_all(full_stream()).tree()
    assert tree.children[0].name == "GAT"
    assert tree.children[0].year == 2018


# -- fitting the terminal ------------------------------------------------------


def test_the_status_line_fits_an_eighty_column_terminal():
    """The default terminal is 80 columns; a longer strip is silently clipped.

    Found by compositing a real frame: `+answer` and `.done` were invisible, so
    the last two phases of the gate could not be read.
    """
    state = PipelineState().apply_all(full_stream())
    for width in (80, 100, 120, 200):
        line = state.status_line(width)
        assert len(line) <= width, f"{width} columns: {line!r}"


def test_the_status_line_still_names_every_phase_when_abbreviated():
    state = PipelineState().apply_all(full_stream())
    line = state.status_line(80)
    assert "answer" not in line, "abbreviated at 80 columns"
    for phase in STATUS_PHASES:
        assert _abbreviate(str(phase)) in line


def test_the_abbreviations_are_distinguishable():
    """`search` and `score` both truncate to `s`, which reads as one phase."""
    codes = [_abbreviate(str(p)) for p in STATUS_PHASES]
    assert len(set(codes)) == len(codes), f"ambiguous codes: {codes}"


def test_the_counter_line_is_bounded_and_prioritised():
    state = PipelineState().apply_all(full_stream())
    line = state.counter_line(80)  # the width the widget passes
    assert len(line) <= 80
    assert "papers=63" in line
    assert "nodes=90" in line
    # Per-stage detail is dropped, and the drop is disclosed rather than hidden.
    assert "extracted_concepts" not in line
    assert "more" in line


def test_a_wide_terminal_shows_every_headline_counter():
    state = PipelineState().apply_all(full_stream())
    line = state.counter_line(200)
    for key in ("papers", "concepts", "nodes", "edges", "subgraph_nodes"):
        assert f"{key}=" in line


def test_an_impossibly_narrow_bar_still_says_something():
    state = PipelineState().apply_all(full_stream())
    line = state.counter_line(4)
    assert line
    assert len(line) <= 40, "a 4-column bar still discloses how much it dropped"


def test_the_counter_line_says_so_when_there_is_nothing_yet():
    assert PipelineState().counter_line() == "no counters yet"


def test_no_node_is_dropped_from_the_tree():
    tree = PipelineState().apply_all(full_stream()).tree()
    seen: list[str] = []

    def walk(node) -> None:
        seen.append(node.label)
        for child in node.children:
            walk(child)

    walk(tree)
    assert {"C1", "C2", "P1", "P2"} <= set(seen)


def test_a_paper_attached_to_no_concept_is_still_listed():
    payload = {
        "question_type": "lineage",
        "nodes": [
            {"id": "c:x", "label": "C1", "type": "concept", "name": "x"},
            {"id": "p9", "label": "P9", "type": "paper", "name": "orphan"},
        ],
        "edges": [],
        "stats": {"nodes": 2, "edges": 0},
    }
    state = PipelineState()
    state.apply(event(Phase.TRAVERSE, "subgraph", kind="ok", **payload))
    tree = state.tree()
    labels = {c.label for c in tree.children}
    assert "P9" in labels


def test_no_traversal_yet_means_no_tree():
    assert PipelineState().tree() is None


def test_a_traversal_with_no_nodes_still_renders():
    state = PipelineState()
    state.apply(event(Phase.TRAVERSE, "empty", kind="warn",
                      nodes=[], edges=[], stats={"nodes": 0, "edges": 0}))
    tree = state.tree()
    assert tree is not None
    assert tree.children == []


# -- the error path ------------------------------------------------------------


def test_an_error_event_is_recorded_and_shown():
    state = PipelineState()
    state.apply(event(Phase.ERROR, "Pipeline aborted during acquisition", kind="error"))
    assert state.error == "Pipeline aborted during acquisition"


def test_a_stage_error_does_not_overwrite_a_pipeline_abort():
    state = PipelineState()
    state.apply(event(Phase.FETCH, "acquisition failed: timeout", kind="error"))
    state.apply(event(Phase.ERROR, "Pipeline aborted", kind="error"))
    assert state.error == "Pipeline aborted"


# -- serialisation -------------------------------------------------------------


def test_state_serialises_for_tests_and_logs():
    payload = PipelineState().apply_all(full_stream()).to_dict()
    assert payload["phase"] == "answer"
    assert payload["answer_complete"] is True
    assert payload["citations"] == ["P1", "C2"]
    assert payload["counters"]["nodes"] == 90
    assert payload["question_type"] == "lineage"
    assert isinstance(payload["elapsed"], float)


def test_elapsed_is_measured_from_the_first_event():
    events = full_stream()
    state = PipelineState().apply_all(events)
    assert state.elapsed >= 0
