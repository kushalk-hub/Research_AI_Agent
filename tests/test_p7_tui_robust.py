"""Routing-independent TUI robustness (Agent C survey scaffolding).

Covers only what needs no routing interface: narrow-terminal status
degradation, the `?` help overlay, and small-frame composition. The model
selector panel is deliberately absent here: its interfaces
(`ProviderRouter.set_override`, `role_models`/`resolved_role`, `on_fallback`)
do not exist yet, so building it would mean inventing routing.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

pytest.importorskip("textual")

from rla.events import Phase, event  # noqa: E402
from rla.tui.app import HELP_TEXT, RlaApp  # noqa: E402
from rla.tui.state import PipelineState, _abbreviate  # noqa: E402


def _run_events() -> list:
    return [
        event(Phase.SEARCH, "Starting pipeline for 'graph RL'", sources=4),
        event(Phase.FETCH, "Deduplicated to 63 unique papers", kind="ok", unique=63),
        event(Phase.SCORE, "Working corpus ready: 63 papers", kind="ok", papers=63),
        event(Phase.GRAPH, "90 nodes, 35 edges", kind="ok",
              stats={"nodes": 90, "edges": 35}),
        event(Phase.TRAVERSE, "subgraph selected", kind="ok",
              question_type="lineage", nodes=[], edges=[], stats={"nodes": 0, "edges": 0}),
        event(Phase.ANSWER, "GAT ", kind="delta"),
        event(Phase.ANSWER, "Answer complete", kind="ok", citations=["P1"]),
        event(Phase.DONE, "Pipeline finished", kind="ok"),
    ]


async def _stream(events, delay: float = 0.0):
    import asyncio

    for evt in events:
        if delay:
            await asyncio.sleep(delay)
        yield evt


# -- narrow-terminal status ----------------------------------------------------


def test_the_status_line_fits_narrow_terminals():
    """Below ~63 columns the old strip overflowed its single row (58 chars at
    width 20). It must now degrade instead of clipping mid-phase."""
    state = PipelineState().apply_all(_run_events())
    for width in (20, 30, 40, 60):
        line = state.status_line(width)
        assert line, f"{width} columns: nothing to show"
        assert len(line) <= width, f"{width} columns: {line!r}"


def test_the_narrow_status_line_still_names_the_active_phase():
    state = PipelineState().apply_all(_run_events())
    line = state.status_line(30)
    assert _abbreviate("answer") in line, f"active phase lost: {line!r}"


def test_a_tiny_status_line_degrades_to_the_clock_not_silence():
    state = PipelineState().apply_all(_run_events())
    line = state.status_line(10)
    assert line
    assert len(line) <= 10


def test_a_narrow_status_line_with_no_events_stays_bounded():
    line = PipelineState().status_line(20)
    assert line
    assert len(line) <= 20


# -- help overlay --------------------------------------------------------------


def test_help_lists_the_bindings_and_panels():
    assert "q" in HELP_TEXT and "c" in HELP_TEXT and "?" in HELP_TEXT
    for panel in ("status", "counters", "log", "tree", "answer"):
        assert panel in HELP_TEXT


def test_help_is_bound():
    assert any(b.action == "toggle_help" for b in RlaApp.BINDINGS)


async def test_question_mark_toggles_the_help_overlay():
    state = PipelineState()
    app = RlaApp(state, _stream([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.help_view is not None
        assert not app.help_view.help_visible

        await pilot.press("?")
        await pilot.pause()
        assert app.help_view.help_visible
        assert "q" in app.help_view.text

        await pilot.press("?")
        await pilot.pause()
        assert not app.help_view.help_visible


# -- small frames --------------------------------------------------------------


async def _frame(state, events, size) -> str:
    app = RlaApp(state, _stream(events))
    async with app.run_test(size=size) as pilot:
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


async def test_a_sixty_column_frame_still_shows_status_and_answer():
    frame = await _frame(PipelineState(), _run_events(), size=(60, 16))
    assert _abbreviate("answer") in frame
    assert "papers=63" in frame


async def test_a_forty_column_frame_composes_without_clipping_the_row():
    state = PipelineState().apply_all(_run_events())
    line = state.status_line(40)
    assert len(line) <= 40
    frame = await _frame(PipelineState(), _run_events(), size=(40, 12))
    assert _abbreviate("answer") in frame
