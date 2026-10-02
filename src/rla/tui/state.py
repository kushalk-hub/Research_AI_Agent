"""Event-stream reducer for the TUI (P7).

The Textual widgets in `app.py` hold no pipeline logic. Everything they display
is derived here from the `Event` stream, as a pure function of the events seen
so far. That split is what makes the UI testable: the interesting behaviour --
which phase is current, what the counters say, what the traversal tree looks
like -- is plain Python, checkable without a terminal, and the widgets are a
thin view over it.

Reducer, not model: `apply` mutates and returns self so a stream can be folded in
a loop, and nothing here awaits or touches the network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rla.events import PIPELINE_PHASES, Event, Phase

#: Every phase the status bar shows. This is `PIPELINE_PHASES` verbatim, minus
#: ERROR: an error is an outcome, not a stage, and giving it a slot would make
#: the strip jump backwards when one arrives. FULLTEXT *is* shown, because the
#: orchestrator announces it as a phase-2 placeholder and `rla events` lists it.
STATUS_PHASES: tuple[Phase, ...] = tuple(p for p in PIPELINE_PHASES if p is not Phase.ERROR)

#: Per-log-line colour, keyed by event kind. `delta` is excluded on purpose:
#: streamed answer text is not a log line, it belongs in the answer panel.
LOG_STYLE = {
    "ok": "green",
    "warn": "yellow",
    "error": "bold red",
    "pending": "dim",
    "info": "cyan",
}

#: Cap on retained log lines. A 60-paper run emits hundreds of events and the
#: point of a live log is the recent tail, not a transcript of the whole run.
MAX_LOG_LINES = 500


@dataclass(slots=True)
class LogLine:
    phase: Phase
    kind: str
    message: str
    timestamp: float
    style: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": str(self.phase),
            "kind": self.kind,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class TreeNode:
    """One node in the traversal tree."""

    label: str
    name: str
    type: str
    year: int | None = None
    children: list[TreeNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "name": self.name,
            "type": self.type,
            "year": self.year,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass(slots=True)
class PipelineState:
    """Everything the TUI shows, derived from events alone."""

    title: str = ""
    question: str = ""
    phase: Phase | None = None
    #: Phases that have emitted at least one event, in order first seen.
    seen: list[Phase] = field(default_factory=list)
    log: list[LogLine] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    #: Latest subgraph payload, for the traversal tree.
    subgraph: dict[str, Any] | None = None
    question_type: str = ""
    #: Streamed answer text, accumulated from `delta` events.
    answer: str = ""
    answer_complete: bool = False
    citations: list[str] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    # -- folding ------------------------------------------------------------

    def apply(self, evt: Event) -> PipelineState:
        """Fold one event in. Returns self so a stream can be piped."""
        phase = Phase(evt.phase) if not isinstance(evt.phase, Phase) else evt.phase
        if phase is not Phase.ERROR and phase not in self.seen:
            self.seen.append(phase)
        if phase is not Phase.DONE:
            self.phase = phase

        if evt.kind == "error" and phase is Phase.ERROR:
            self.error = evt.message
        if evt.kind != "delta" and phase is not Phase.DONE:
            self.log.append(
                LogLine(
                    phase=phase,
                    kind=evt.kind,
                    message=evt.message,
                    timestamp=evt.timestamp,
                    style=LOG_STYLE.get(evt.kind, "white"),
                )
            )
            if len(self.log) > MAX_LOG_LINES:
                del self.log[: len(self.log) - MAX_LOG_LINES]

        self._absorb_counters(phase, evt)
        self._absorb_subgraph(evt)
        self._absorb_answer(phase, evt)

        if phase is Phase.DONE:
            self.finished_at = evt.timestamp
        return self

    def apply_all(self, events: list[Event]) -> PipelineState:
        for evt in events:
            self.apply(evt)
        return self

    # -- counters -----------------------------------------------------------

    def _absorb_counters(self, phase: Phase, evt: Event) -> None:
        """Pull the numbers worth showing out of a payload.

        Counters are only ever set, never incremented from a per-item event: a
        stage that emits one event per paper would otherwise have the UI
        counting its own log lines as papers.
        """
        p = evt.payload
        if phase is Phase.FETCH and isinstance(p.get("unique"), int):
            self.counters["papers"] = p["unique"]
        elif phase is Phase.SCORE and isinstance(p.get("papers"), int):
            self.counters["papers"] = p["papers"]
        elif phase is Phase.EXTRACT:
            if isinstance(p.get("extracted"), int) and isinstance(p.get("total"), int):
                self.counters["extracted"] = p["extracted"]
                self.counters["extract_total"] = p["total"]
            if isinstance(p.get("concepts"), int):
                self.counters["extracted_concepts"] = p["concepts"]
            if isinstance(p.get("limitations"), int):
                self.counters["limitations"] = p["limitations"]
            if isinstance(p.get("pending"), int) and "extract_total" not in self.counters:
                self.counters["extract_total"] = p["pending"]
        elif phase is Phase.RESOLVE:
            if isinstance(p.get("concept_nodes"), list):
                self.counters["concepts"] = len(p["concept_nodes"])
            elif isinstance(p.get("concepts"), int):
                self.counters["concepts"] = p["concepts"]
            if isinstance(p.get("decisions"), list):
                self.counters["merge_decisions"] = len(p["decisions"])
        elif phase is Phase.GRAPH:
            stats = p.get("stats")
            if isinstance(stats, dict):
                for key in ("nodes", "edges", "nodes_Paper", "nodes_Concept"):
                    if isinstance(stats.get(key), int):
                        self.counters[_counter_name(key)] = stats[key]
        elif phase is Phase.TRAVERSE:
            stats = p.get("stats")
            if isinstance(stats, dict) and isinstance(stats.get("nodes"), int):
                self.counters["subgraph_nodes"] = stats["nodes"]
                self.counters["subgraph_edges"] = stats.get("edges", 0)
        elif phase is Phase.DONE:
            graph = p.get("graph")
            if isinstance(graph, dict) and isinstance(graph.get("nodes"), int):
                self.counters.setdefault("nodes", graph["nodes"])
                self.counters.setdefault("edges", graph.get("edges", 0))

    def _absorb_subgraph(self, evt: Event) -> None:
        if evt.phase != Phase.TRAVERSE or "nodes" not in evt.payload:
            return
        payload = evt.payload
        self.subgraph = payload
        self.question_type = str(payload.get("question_type", "") or "")

    def _absorb_answer(self, phase: Phase, evt: Event) -> None:
        if evt.kind == "delta":
            self.answer += evt.message
        elif phase is Phase.ANSWER and evt.kind == "ok":
            self.answer_complete = True
            if isinstance(evt.payload.get("citations"), list):
                self.citations = [str(c) for c in evt.payload["citations"]]
        elif phase is Phase.ANSWER and evt.kind == "error":
            self.error = self.error or evt.message

    # -- derived views ------------------------------------------------------

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at)

    @property
    def current_index(self) -> int:
        """Position of the active phase in the status bar, 0-based."""
        if self.phase is None:
            return 0
        try:
            return STATUS_PHASES.index(self.phase)
        except ValueError:
            return 0

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def phase_states(self) -> list[tuple[Phase, str]]:
        """`(phase, state)` per status slot, where state is one of
        `done` / `active` / `pending` / `skipped`."""
        active = self.current_index
        states: list[tuple[Phase, str]] = []
        for index, phase in enumerate(STATUS_PHASES):
            if self.finished and index < active:
                state = "done"
            elif index < active:
                state = "done"
            elif index == active:
                state = "active"
            else:
                state = "pending"
            states.append((phase, state))
        return states

    def status_line(self, width: int | None = None) -> str:
        """Phase strip plus the clock, for the status bar.

        Counters deliberately do not appear here: they have their own bar, and
        duplicating them overflowed the 80-column strip, pushing the `answer` and
        `done` slots off screen exactly when they matter most.

        `width` is the widget's column count. Full phase names do not fit the
        default 80-column terminal, so the strip abbreviates rather than being
        clipped -- a gate that says "all phases live" cannot be satisfied by a
        strip whose last two phases are invisible.
        """
        states = self.phase_states()
        full = "  ".join(f"{_MARKERS[s]}{p}" for p, s in states)
        compact = "  ".join(f"{_MARKERS[s]}{_abbreviate(str(p))}" for p, s in states)
        clock = f"{self.elapsed:0.0f}s"
        # `width` of 0 means the widget has not been laid out yet, which is not
        # the same as "zero columns available"; fall back to the full strip and
        # let the resize handler ask again.
        if width and len(full) + 5 + len(clock) > width:
            if len(compact) + 2 + len(clock) <= width:
                return f"{compact}  {clock}"
            if len(compact) <= width:
                return compact
            # Very narrow terminal: name the current phase only, so the strip
            # degrades to `>ans  12s` instead of overflowing its single row
            # and clipping mid-phase.
            abbrev = _abbreviate(str(self.phase)) if self.phase is not None else "—"
            minimal = f"{_MARKERS['active']}{abbrev}  {clock}"
            if len(minimal) <= width:
                return minimal
            short = f"{_MARKERS['active']}{abbrev}"
            return short[:width] if len(short) > width else short
        return f"{full}   |   {clock}"

    #: Counters worth the scarce space on one line, most important first. The
    #: rest (per-stage detail like extracted_concepts) stay in the event log.
    #: Without this, 12 counters overflowed the bar and the tail was unreadable.
    HEADLINE_COUNTERS = (
        "papers",
        "concepts",
        "nodes",
        "edges",
        "limitations",
        "subgraph_nodes",
        "subgraph_edges",
    )

    def counter_line(self, width: int | None = None) -> str:
        """The headline counters, in priority order, for the counter bar.

        Counters are dropped from the tail until the line fits `width`, and the
        drop is disclosed with a `(+N more)` marker. Silently clipping the line
        instead would hide the last number, which is the one a reader wants.
        """
        available = [
            (key, self.counters[key])
            for key in self.HEADLINE_COUNTERS
            if key in self.counters
        ]
        if not available:
            return "no counters yet"
        limit = width if width else 10**6

        def render(items: list[tuple[str, int]], dropped: int) -> str:
            line = "   ".join(f"{k}={v}" for k, v in items)
            if dropped:
                suffix = f"(+{dropped} more)"
                line = f"{line}   {suffix}" if line else suffix
            return line

        keep = len(available)
        while keep:
            keep -= 1
            dropped = len(self.counters) - keep
            line = render(available[:keep], dropped)
            if len(line) <= limit:
                return line
        return render([], len(self.counters))

    def counter_summary(self) -> dict[str, int]:
        return dict(self.counters)

    def tree(self) -> TreeNode | None:
        """The traversed subgraph as a tree, rooted at the seed concepts.

        Papers hang off the concepts they touch, which is the shape a reader
        expects: the question was about a concept, and the papers are the
        evidence for it. A paper attached to no concept in the subgraph is
        still listed, under its own root, so no node silently disappears.
        """
        if not self.subgraph:
            return None
        nodes = self.subgraph.get("nodes") or []
        edges = self.subgraph.get("edges") or []
        by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

        root = TreeNode(
            label="subgraph", name=self.question_type or "traversal", type="root"
        )
        nodes_by_id = {
            n["id"]: TreeNode(
                label=str(n.get("label", "")),
                name=str(n.get("name", "")),
                type=str(n.get("type", "")),
                year=n.get("year"),
            )
            for n in nodes
            if isinstance(n, dict) and "id" in n
        }

        #: Concept -> concept edges. `EXTENDS` runs parent -> child, so the
        #: source is the ancestor and the target nests under it.
        nested: set[str] = set()
        attached: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src, dst = edge.get("source"), edge.get("target")
            if src not in by_id or dst not in nodes_by_id:
                continue
            src_type, dst_type = by_id[src].get("type"), by_id[dst].get("type")
            if src_type == "concept" and dst_type == "concept":
                nodes_by_id[src].children.append(nodes_by_id[dst])
                nested.add(dst)
            elif src_type == "concept" and dst_type == "paper":
                nodes_by_id[src].children.append(nodes_by_id[dst])
                attached.add(dst)

        def _sort_key(node: TreeNode) -> tuple[str, int]:
            return (node.label, -(node.year or 0))

        for node in nodes_by_id.values():
            node.children.sort(key=_sort_key)

        # Compared by node id, not label: labels are assigned per subgraph and a
        # paper and a concept can share one in a malformed payload.
        placed = nested | attached
        roots = [nid for nid in nodes_by_id if nid not in placed]
        for node in sorted((nodes_by_id[nid] for nid in roots), key=_sort_key):
            root.children.append(node)
        return root

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": str(self.phase) if self.phase else None,
            "seen": [str(p) for p in self.seen],
            "counters": self.counter_summary(),
            "question_type": self.question_type,
            "answer": self.answer,
            "answer_complete": self.answer_complete,
            "citations": list(self.citations),
            "error": self.error,
            "finished": self.finished,
            "elapsed": round(self.elapsed, 2),
            "log_lines": len(self.log),
            "subgraph_nodes": self.counters.get("subgraph_nodes"),
        }


#: Per-phase strip markers: done, active, pending.
_MARKERS = {"done": "+", "active": ">", "pending": "."}


def _abbreviate(phase: str) -> str:
    """`+fulltext` -> `+ful`.

    Three characters, not two: `search`/`score` and `fetch`/`fulltext` both
    collapse to `s` and `f` at two, which makes the strip unreadable. The ten
    three-letter codes are still distinct and fit an 80-column terminal.
    """
    return phase[:3] if len(phase) > 3 else phase


def _counter_name(key: str) -> str:
    return {
        "nodes_Paper": "graph_papers",
        "nodes_Concept": "graph_concepts",
    }.get(key, key)
