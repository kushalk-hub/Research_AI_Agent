"""Textual app smoke tests (P7).

`App.run_test()` drives the real app against Textual's headless driver, so these
cover the parts the gate names that a pure reducer cannot: that the app mounts,
that a live event stream reaches the widgets, and -- the one real risk -- that a
slow stage does not freeze the UI.

The behaviour worth asserting lives in `tui/state.py`; these tests exist to prove
the view is wired to it and does not block.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from rich.console import Console

pytest.importorskip("textual")

from rla.events import Phase, event  # noqa: E402
from rla.tui.app import RlaApp, build_tree  # noqa: E402
from rla.tui.state import STATUS_PHASES, PipelineState, _abbreviate  # noqa: E402

SUBGRAPH = {
    "question_type": "lineage",
    "nodes": [
        {"id": "c:gat", "label": "C1", "type": "concept", "name": "GAT", "year": 2018},
        {"id": "c:agent", "label": "C2", "type": "concept", "name": "agent graphs", "year": 2024},
        {"id": "p1", "label": "P1", "type": "paper", "name": "GAT paper", "year": 2018},
    ],
    "edges": [
        {"source": "c:gat", "target": "c:agent", "type": "EXTENDS"},
        {"source": "c:gat", "target": "p1", "type": "USES"},
    ],
    "notes": [],
    "seeds": ["c:gat"],
    "stats": {"nodes": 3, "edges": 2, "papers": 1, "concepts": 2},
}

GRAPH_STATS = {"nodes": 90, "edges": 35, "nodes_Paper": 63, "nodes_Concept": 27}


async def _stream(events, delay: float = 0.0):
    for evt in events:
        if delay:
            await asyncio.sleep(delay)
        yield evt


def _sample_events() -> list:
    return [
        event(Phase.SEARCH, "Starting pipeline for 'graph RL'", sources=4),
        event(Phase.FETCH, "Deduplicated to 63 unique papers", kind="ok", unique=63),
        event(Phase.SCORE, "Working corpus ready: 63 papers", kind="ok", papers=63),
        event(Phase.EXTRACT, "Extracted 20/20 papers", kind="ok",
              extracted=20, total=20, concepts=19, limitations=7),
        event(Phase.RESOLVE, "27 concepts after resolution", kind="ok",
              concept_nodes=[{"id": f"c:{i}"} for i in range(27)]),
        event(Phase.GRAPH, "90 nodes, 35 edges", kind="ok", stats=GRAPH_STATS),
        event(Phase.TRAVERSE, "subgraph selected: 3 nodes, 2 edges", kind="ok", **SUBGRAPH),
        event(Phase.ANSWER, "GAT ", kind="delta"),
        event(Phase.ANSWER, "led to agent graphs [P1][C2].", kind="delta"),
        event(Phase.ANSWER, "Answer complete", kind="ok",
              question_type="lineage", citations=["P1", "C2"]),
        event(Phase.DONE, "Pipeline finished", kind="ok"),
    ]


# -- the tree builder ----------------------------------------------------------


def test_the_tree_renders_when_there_is_no_traversal():
    assert build_tree(None) is not None


def _render(tree) -> str:
    """Render a rich Tree to text, so the assertions read the real output."""
    console = Console(file=io.StringIO(), width=200, no_color=True, legacy_windows=False)
    console.print(tree)
    return console.file.getvalue()  # type: ignore[union-attr]


def test_the_tree_renders_concepts_and_papers():
    state = PipelineState()
    state.apply(event(Phase.TRAVERSE, "subgraph", kind="ok", **SUBGRAPH))
    rendered = _render(build_tree(state.tree()))
    assert "GAT" in rendered
    assert "agent graphs" in rendered
    assert "GAT paper" in rendered
    assert "2018" in rendered, "the year is shown next to the concept"


# -- the app -------------------------------------------------------------------


async def test_the_app_mounts_and_shows_the_status_bar():
    app = RlaApp(PipelineState(), _stream(_sample_events()))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.status_bar is not None
        assert app.status_bar.text


async def test_a_live_stream_reaches_the_widgets():
    state = PipelineState()
    app = RlaApp(state, _stream(_sample_events()))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert state.answer == "GAT led to agent graphs [P1][C2]."
    assert state.counters["nodes"] == 90
    assert state.finished


async def test_the_counters_reach_the_bar_while_the_run_is_live():
    state = PipelineState()
    events = _sample_events()
    # Stop before DONE so the app is still running when we look.
    app = RlaApp(state, _stream(events[:-1]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = str(app.counters.text)
        assert "nodes=90" in text
        assert "papers=63" in text


async def test_the_status_bar_names_the_active_phase():
    state = PipelineState()
    app = RlaApp(state, _stream(_sample_events()[:-1]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        # Abbreviated at the default 80 columns, so match the code not the word.
        assert "ans" in app.status_bar.text
        assert _abbreviate("answer") == "ans"


async def test_a_slow_stage_does_not_freeze_the_app():
    """The gate's real risk. Each event waits 0.1s, so the run takes ~1s.

    The UI must stay responsive throughout: input handled and workers scheduled
    while the pipeline is still mid-stream. If the pipeline ran on the render
    thread, these pauses would block until it finished.
    """
    state = PipelineState()
    events = _sample_events()
    app = RlaApp(state, _stream(events, delay=0.1))
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.25)  # roughly a quarter of the way in
        assert not state.finished, "the run should still be in progress"

        # Input is processed mid-run, which it would not be on a blocked loop.
        await pilot.press("c")
        await pilot.pause()
        assert not state.finished

        await app.workers.wait_for_complete()
        await pilot.pause()

    assert state.finished
    assert state.answer


async def test_a_crashing_stage_shows_the_error_and_keeps_the_app_alive():
    state = PipelineState()

    async def _boom():
        yield event(Phase.SEARCH, "starting")
        raise RuntimeError("connection reset")

    app = RlaApp(state, _boom())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert "connection reset" in state.error
    # The app is still mounted, so the user can read what happened and quit.
    assert app.status_bar is not None


async def test_a_stream_with_no_events_does_not_crash():
    state = PipelineState()
    app = RlaApp(state, _stream([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert not state.finished
    assert app.status_bar is not None


async def test_quit_is_bound():
    app = RlaApp(PipelineState(), _stream([]))
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()


# -- the 80-column reality -----------------------------------------------------
#
# The default terminal is 80 columns. These assert on the composed frame, because
# every earlier layout bug was invisible in the widget strings and only showed up
# once rendered: the status strip clipped after `+traverse`, and the log was
# squeezed to 23 columns so every message was an unreadable stub.


async def _frame(state, events, size=(80, 24)) -> str:
    app = RlaApp(state, _stream(events))
    async with app.run_test(size=size) as pilot:
        # `wait_for_complete` returns immediately if the worker has not been
        # registered yet, which silently captured the pre-run layout. Poll the
        # state instead, so the frame is of a finished run.
        for _ in range(100):
            await pilot.pause()
            if state.finished:
                break
        await app.workers.wait_for_complete()
        await pilot.pause()
        console = Console(file=io.StringIO(), width=size[0], no_color=True,
                          legacy_windows=False)
        console.print(app.screen._compositor)
        return console.file.getvalue()  # type: ignore[union-attr]


async def test_every_phase_is_visible_at_eighty_columns():
    frame = await _frame(PipelineState(), _sample_events())
    for phase in STATUS_PHASES:
        assert _abbreviate(str(phase)) in frame, f"{phase} is not on screen"


async def test_the_status_strip_is_not_clipped():
    frame = await _frame(PipelineState(), _sample_events())
    strip = next(line for line in frame.splitlines() if "sco" in line)
    assert "don" in strip, f"the last phase is clipped: {strip!r}"


async def test_the_log_panel_is_wide_enough_to_read():
    """23 columns truncated every message mid-word; the log needs real room."""
    frame = await _frame(PipelineState(), _sample_events())
    assert "Deduplicated to 63 unique" in frame
    # RichLog's `min_width` defaults to 78. A narrower panel silently rendered at
    # 78 columns and was then cut by the border, losing message tails.
    assert "papers" in frame


async def test_a_wide_terminal_shows_full_log_messages_on_one_line():
    frame = await _frame(PipelineState(), _sample_events(), size=(200, 40))
    assert "Deduplicated to 63 unique papers" in frame


async def test_the_answer_and_tree_are_both_visible():
    frame = await _frame(PipelineState(), _sample_events())
    assert "GAT" in frame
    assert "led to agent graphs" in frame


async def test_a_wide_terminal_renders_full_phase_names():
    frame = await _frame(PipelineState(), _sample_events(), size=(200, 30))
    assert "+traverse" in frame
    assert ".done" in frame
