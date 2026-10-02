"""P12: transient model selection and routing visibility in the TUI.

The selector introduces no TUI-specific execution path: it mutates the same
`PipelineState` the reducer already owns and reads through the same
`ProviderRouter`, preserving the one-event-stream invariant.

Router interaction is coded strictly to the locked Agent B interface names
(`set_override` / `clear_overrides` / `on_fallback`, roles `structured` and
`answer`). Those live on Agent B's branch, not here, so every router in this
module is a fake. Selections are session-scoped and never touch `.env`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rla.events import Phase  # noqa: E402
from rla.tui.app import (  # noqa: E402
    RlaApp,
    SelectorPanel,
    connect_router,
    routing_text,
    selector_lines,
)
from rla.tui.state import PipelineState  # noqa: E402

STRUCTURED = "ollama/qwen3:4b"
ANSWER = "gemini/gemini-2.5-flash"


def state(**kw) -> PipelineState:
    return PipelineState(
        title="t",
        role_models={"structured": STRUCTURED, "answer": ANSWER},
        **kw,
    )


class FakeRouter:
    """Stands in for Agent B's `ProviderRouter` (locked names only)."""

    def __init__(self) -> None:
        self.overrides: dict[str, str] = {}
        self.on_fallback = None
        self.cleared = 0

    def set_override(self, role: str, model: str | None) -> None:
        if model is None:
            self.overrides.pop(role, None)
        else:
            self.overrides[role] = model

    def clear_overrides(self) -> None:
        self.overrides.clear()
        self.cleared += 1

    def emit_fallback(self, stage: str, src: str, dst: str, reason: str) -> None:
        assert self.on_fallback is not None, "observer not registered"
        self.on_fallback(stage, src, dst, reason)


# -- the PipelineState routing extensions (plan Task 6, step 1) ----------------


def test_the_three_states_are_distinguishable():
    s = state()
    line = s.routing_line()
    assert "structured" in line
    assert STRUCTURED in line


def test_a_selection_shows_as_an_override_not_as_configuration():
    s = state()
    s.select_model("structured", ANSWER)

    assert s.role_models["structured"] == STRUCTURED, "configuration is untouched"
    assert s.overrides["structured"] == ANSWER
    assert s.resolved_role("extraction") == ANSWER


def test_clearing_a_selection_restores_the_configured_model():
    s = state()
    s.select_model("structured", ANSWER)
    s.select_model("structured", None)
    assert s.resolved_role("extraction") == STRUCTURED


def test_a_selection_does_not_leak_to_the_answer_role():
    s = state()
    s.select_model("structured", ANSWER)
    assert s.resolved_role("answer") == ANSWER


def test_a_fallback_is_recorded_for_display():
    s = state()
    s.record_fallback("extraction", STRUCTURED, ANSWER, "server_error")

    assert s.fallbacks
    assert "extraction" in s.fallbacks[-1]
    assert ANSWER in s.routing_line()


def test_the_router_line_survives_an_empty_state():
    s = PipelineState(title="t")
    assert isinstance(s.routing_line(), str)
    assert s.resolved_role("extraction") == ""


def test_unmapped_stages_read_no_override():
    """Roles are `structured` and `answer` only; anything else reads nothing."""
    s = state()
    s.select_model("structured", ANSWER)
    for stage in ("fetch", "fulltext", "graph", "traverse", "done", "bogus"):
        assert s.resolved_role(stage) == "", f"{stage} must read no override"


def test_resolved_role_accepts_phase_values():
    s = state()
    assert s.resolved_role(Phase.EXTRACT) == STRUCTURED
    assert s.resolved_role(Phase.ANSWER) == ANSWER
    assert s.resolved_role(Phase.FETCH) == ""


# -- router interaction goes through the locked names only ---------------------


def test_select_calls_set_override_and_mirrors_state():
    s = state()
    router = FakeRouter()
    panel = SelectorPanel(s, router=router)
    panel.select("structured", ANSWER)
    assert router.overrides == {"structured": ANSWER}
    assert s.overrides == {"structured": ANSWER}


def test_clear_calls_set_override_with_none():
    s = state()
    router = FakeRouter()
    panel = SelectorPanel(s, router=router)
    panel.select("structured", ANSWER)
    panel.clear("structured")
    assert router.overrides == {}
    assert s.resolved_role("extraction") == STRUCTURED


def test_clear_all_calls_clear_overrides():
    s = state()
    router = FakeRouter()
    panel = SelectorPanel(s, router=router)
    panel.select("structured", ANSWER)
    panel.select("answer", STRUCTURED)
    panel.clear_all()
    assert router.cleared == 1
    assert s.overrides == {}


def test_the_fallback_observer_receives_four_positional_args():
    s = state()
    router = FakeRouter()
    connect_router(s, router)
    router.emit_fallback("extraction", STRUCTURED, ANSWER, "server_error")
    assert s.fallbacks == [("extraction", STRUCTURED, ANSWER, "server_error")]
    assert ANSWER in s.routing_line()


def test_cycle_steps_through_the_available_models_then_clears():
    s = state()
    router = FakeRouter()
    panel = SelectorPanel(s, available_models=[ANSWER], router=router)
    panel.cycle("structured")
    assert s.resolved_role("extraction") == ANSWER
    panel.cycle("structured")
    assert s.resolved_role("extraction") == STRUCTURED
    assert router.overrides == {}


def test_cycle_with_no_available_models_is_a_noop():
    s = state()
    panel = SelectorPanel(s)
    panel.cycle("structured")
    assert s.overrides == {}


def test_selections_are_session_scoped():
    """A demonstration choice must not become permanent configuration."""
    import os

    s = state()
    before = dict(os.environ)
    panel = SelectorPanel(s, router=FakeRouter())
    panel.select("structured", ANSWER)
    panel.clear_all()
    assert s.role_models == {"structured": STRUCTURED, "answer": ANSWER}
    assert dict(os.environ) == before


# -- configured / override / resolved display ----------------------------------


def test_the_selector_shows_all_three_states_per_role():
    lines = selector_lines(state())
    text = "\n".join(lines).lower()
    assert "configured" in text and "override" in text and "resolved" in text
    assert STRUCTURED in "\n".join(lines) and ANSWER in "\n".join(lines)


def test_the_selector_marks_selections_as_session_only():
    lines = selector_lines(state())
    assert any("session" in line for line in lines)
    assert not any(".env" in line and "writ" in line for line in lines)


def test_the_selector_names_the_override_after_a_selection():
    s = state()
    s.select_model("structured", ANSWER)
    text = "\n".join(selector_lines(s))
    assert f"override: {ANSWER}" in text.lower().replace("  ", " ") or ANSWER in text
    assert "override" in text.lower()


# -- small terminals ------------------------------------------------------------


def test_the_routing_line_fits_narrow_terminals():
    s = state()
    s.select_model("structured", ANSWER)
    s.record_fallback("extraction", STRUCTURED, ANSWER, "server_error")
    for width in (20, 30, 40, 60):
        line = routing_text(s, width)
        assert line, f"{width} columns: nothing to show"
        assert len(line) <= width, f"{width} columns: {line!r}"


def test_the_selector_fits_narrow_terminals():
    s = state()
    s.select_model("structured", ANSWER)
    for width in (30, 40, 60):
        lines = selector_lines(s, width)
        assert lines
        for line in lines:
            assert len(line) <= width, f"{width} columns: {line!r}"


# -- keyboard + composition (headless Textual driver) ----------------------------


async def _stream(events):
    for evt in events:
        yield evt


async def test_m_toggles_the_selector_panel():
    app = RlaApp(state(), _stream([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selector_panel is not None
        assert not app.selector_panel.display

        await pilot.press("m")
        await pilot.pause()
        assert app.selector_panel.display

        await pilot.press("m")
        await pilot.pause()
        assert not app.selector_panel.display


async def test_e_cycles_the_structured_override():
    s = state()
    router = FakeRouter()
    app = RlaApp(s, _stream([]), available_models=[ANSWER], router=router)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert s.resolved_role("extraction") == ANSWER
        assert router.overrides == {"structured": ANSWER}

        await pilot.press("e")
        await pilot.pause()
        assert s.resolved_role("extraction") == STRUCTURED


async def test_x_clears_every_override():
    s = state()
    router = FakeRouter()
    app = RlaApp(s, _stream([]), available_models=[ANSWER], router=router)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert s.overrides

        await pilot.press("x")
        await pilot.pause()
        assert s.overrides == {}
        assert router.overrides == {}


async def test_the_routing_bar_is_visible_in_a_full_frame():
    import io

    from rich.console import Console

    s = state()
    app = RlaApp(s, _stream([]))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        console = Console(file=io.StringIO(), width=80, no_color=True,
                          legacy_windows=False)
        console.print(app.screen._compositor)
        frame = console.file.getvalue()
    assert STRUCTURED in frame
