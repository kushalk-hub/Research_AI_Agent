"""Kiro-style Textual app (P7).

The gate has two halves and they are verified differently. "Shows all phases live
with running graph counters" is `tui/state.py`, tested as a pure reducer. This
module is the view over it: widgets only, no pipeline logic, so there is nothing
here worth unit-testing beyond the tree builder.

The one real risk the gate names is the UI freezing. That is handled by running
the pipeline in a Textual worker on the event loop and only ever calling
`call_from_thread`-free, non-blocking widget updates, so a slow network stage can
never hold the render loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from rich.tree import Tree as RichTree
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from rla.events import Event, Phase
from rla.tui.state import PipelineState, TreeNode

#: How often the elapsed-time counter refreshes, in seconds. Fast enough to look
#: live, slow enough that it is not the reason the UI drops frames.
TICK_SECONDS = 0.5


class _StateView(Static):
    """A `Static` that renders a slice of `PipelineState`.

    Each view keeps its own plain-text copy so tests can assert what the user
    sees without reaching into Textual's private `Static.__content`, and so a
    failed render is still readable.
    """

    def __init__(self, state: PipelineState, widget_id: str) -> None:
        super().__init__(id=widget_id)
        self._state = state
        self.text = ""

    def _show(self, body: Text) -> None:
        self.text = body.plain
        self.update(body)

    def refresh_state(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def on_resize(self) -> None:
        """Re-render at the new width.

        The bar is width-aware, but it is first rendered before layout, when the
        width is still 0. Waiting for the app's own resize is not enough: the app
        is sized before its children are, so it would re-ask while the widget
        still reported zero columns and keep the overflowing layout.
        """
        if self.size.width:
            self.refresh_state()


class StatusBar(_StateView):
    """Phase strip plus counters. The single line that answers "where am I"."""

    def __init__(self, state: PipelineState) -> None:
        super().__init__(state, "status")

    def refresh_state(self) -> None:
        # The widget knows its own width; the reducer does not.
        self._show(Text(self._state.status_line(self.size.width or None)))


class AnswerPanel(_StateView):
    """Streamed answer text, growing as deltas arrive."""

    def __init__(self, state: PipelineState) -> None:
        super().__init__(state, "answer")

    def refresh_state(self) -> None:
        if not self._state.answer:
            self._show(Text("No answer yet.", style="dim"))
            return
        body = Text(self._state.answer)
        if not self._state.answer_complete:
            body.append("  …", style="dim")
        if self._state.citations:
            body.append(
                f"\n\ncited: {', '.join(self._state.citations)}", style="dim italic"
            )
        self._show(body)


class GraphCounters(_StateView):
    """Running graph counters, so the size of the graph is visible while it builds."""

    def __init__(self, state: PipelineState) -> None:
        super().__init__(state, "counters")

    def refresh_state(self) -> None:
        self._show(Text(self._state.counter_line(self.size.width or None), style="dim"))


#: Shortcut help, shown only while `?` is held open. Plain text on purpose: it
#: names keys and panels, and routing state never belongs here -- the selector
#: panel that will show configured/override/resolved needs Agent B's
#: interfaces (`set_override`, `role_models`/`resolved_role`, `on_fallback`)
#: and is deliberately not built yet.
HELP_TEXT = (
    "keys: q quit · c clear log · ? this help\n"
    "panels: status (phase + clock) · counters · log (wraps, no deltas)"
    " · tree · answer (deltas + citations)\n"
    "same event stream as `rla run`; needs Windows Terminal, not conhost"
)


class HelpPanel(Static):
    """Shortcut help overlay, hidden until `?` toggles it."""

    def __init__(self) -> None:
        super().__init__(HELP_TEXT, id="help")
        self.text = HELP_TEXT
        self.help_visible = False
        self.display = False

    def toggle(self) -> None:
        self.help_visible = not self.help_visible
        self.display = self.help_visible


def build_tree(node: TreeNode | None) -> RichTree:
    """Turn the reducer's `TreeNode` into the `rich.tree.Tree` the gate names."""
    if node is None:
        return RichTree(Text("no traversal yet", style="dim"))
    return _add(RichTree(Text(node.name, style="bold")), node)


def _add(parent: RichTree, node: TreeNode) -> RichTree:
    for child in node.children:
        style = "cyan" if child.type == "concept" else "white"
        label = Text(f"{child.label} ", style="bold")
        name = child.name or child.label
        if child.year:
            name = f"{name} ({child.year})"
        label.append(name, style=style)
        _add(parent.add(label), child)
    return parent


class RlaApp(App[None]):
    """Live pipeline view: status strip, event log, traversal tree, answer."""

    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; background: $panel; color: $text; }
    #counters { height: 1; color: $text-muted; }
    #help { height: auto; max-height: 5; border: round $primary; }
    #body { height: 1fr; }
    /* The log carries the run's narrative, so it gets the larger share; 3fr/2fr
       left the log at 23 columns on an 80-column terminal, which truncated every
       message to an unreadable stub. */
    #log { width: 1fr; height: 1fr; border: round $primary; }
    #side { width: 1fr; }
    #tree { height: 1fr; border: round $primary; overflow-y: auto; }
    #answer { height: 1fr; border: round $success; overflow-y: auto; padding: 0 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "clear", "Clear log"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    def __init__(self, state: PipelineState, events: Any = None) -> None:
        super().__init__()
        self.state = state
        #: Async iterator of pipeline events, or None when replaying a fixed list.
        self._stream = events
        self.status_bar: StatusBar | None = None
        self.counters: GraphCounters | None = None
        self.help_view: HelpPanel | None = None
        #: Named `log_view` because `App.log` is a Textual property; assigning to
        #: it raises, which is the sort of thing worth catching at import time.
        self.log_view: RichLog | None = None
        self.tree_view: Static | None = None
        self.answer_panel: AnswerPanel | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        self.status_bar = StatusBar(self.state)
        yield self.status_bar
        self.counters = GraphCounters(self.state)
        yield self.counters
        self.help_view = HelpPanel()
        yield self.help_view
        with Horizontal(id="body"):
            # `min_width` defaults to 78, wider than this panel, so the log was
            # rendered at 78 columns and then hard-cut by the border -- messages
            # lost their tails instead of wrapping. A low floor lets it shrink and
            # wrap, which is the only way a narrow panel stays readable.
            self.log_view = RichLog(
                id="log", wrap=True, markup=False, highlight=False, min_width=20
            )
            yield self.log_view
            with Vertical(id="side"):
                self.tree_view = Static(id="tree")
                yield self.tree_view
                self.answer_panel = AnswerPanel(self.state)
                yield self.answer_panel
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_all()
        if self._stream is not None:
            self.run_worker(self._consume(), name="pipeline", exclusive=True, group="pipeline")
        self.set_interval(TICK_SECONDS, self._tick)

    def on_resize(self) -> None:
        """Re-render when the terminal changes size.

        The bars are width-aware, and the first layout pass can happen before the
        widgets know their width, so a resize has to re-ask for the text. Without
        this, a terminal narrowed after startup keeps the layout that no longer
        fits and clips the status strip.
        """
        self._refresh_all()

    # -- the worker ---------------------------------------------------------

    async def _consume(self) -> None:
        """Drain the pipeline's event stream on the event loop.

        Each event is a cheap `update()` on already-mounted widgets, so the
        pipeline's own awaiting is what yields; the render loop is never blocked
        on network I/O.
        """
        assert self._stream is not None
        try:
            async for evt in self._stream:
                self.state.apply(evt)
                self._push(evt)
                self._refresh_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a crashed stage must not take the UI down
            self.state.apply(
                Event(Phase.ERROR, str(exc), kind="error")
            )
            self._refresh_all()

    def _push(self, evt: Event) -> None:
        if self.log_view is None:
            return
        if evt.kind == "delta" or Phase(evt.phase) is Phase.DONE:
            return  # answer text lives in its own panel
        style = {
            "ok": "green",
            "warn": "yellow",
            "error": "bold red",
            "pending": "dim",
        }.get(evt.kind, "white")
        self.log_view.write(Text(f"{str(evt.phase):<9} {evt.message}", style=style))

    # -- refreshing ---------------------------------------------------------

    def _refresh_all(self) -> None:
        if self.status_bar is not None:
            self.status_bar.refresh_state()
        if self.counters is not None:
            self.counters.refresh_state()
        if self.answer_panel is not None:
            self.answer_panel.refresh_state()
        if self.tree_view is not None:
            self.tree_view.update(build_tree(self.state.tree()))

    def _tick(self) -> None:
        """Refresh the elapsed clock only; the heavy views update per event."""
        if self.status_bar is not None and not self.state.finished:
            self.status_bar.refresh_state()

    def _log(self, message: str, style: str = "white") -> None:
        if self.log_view is not None:
            self.log_view.write(Text(message, style=style))

    # -- actions ------------------------------------------------------------

    def action_clear(self) -> None:
        if self.log_view is not None:
            self.log_view.clear()

    def action_toggle_help(self) -> None:
        if self.help_view is not None:
            self.help_view.toggle()