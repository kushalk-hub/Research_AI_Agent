"""Typed pipeline events (spec section 8).

The pipeline yields Events instead of returning a result, so the headless
runner and the TUI can both subscribe to the same stream.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Phase(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    SCORE = "score"
    FULLTEXT = "fulltext"
    EXTRACT = "extract"
    RESOLVE = "resolve"
    GRAPH = "graph"
    TRAVERSE = "traverse"
    ANSWER = "answer"
    DONE = "done"
    ERROR = "error"


#: Ordered pipeline phases, used by the TUI status bar (spec section 8).
PIPELINE_PHASES: tuple[Phase, ...] = (
    Phase.SEARCH,
    Phase.FETCH,
    Phase.SCORE,
    Phase.FULLTEXT,
    Phase.EXTRACT,
    Phase.RESOLVE,
    Phase.GRAPH,
    Phase.TRAVERSE,
    Phase.ANSWER,
    Phase.DONE,
)


@dataclass(slots=True)
class Event:
    phase: Phase
    message: str
    kind: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": str(self.phase),
            "kind": self.kind,
            "message": self.message,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


def event(
    phase: Phase,
    message: str,
    kind: str = "info",
    **payload: Any,
) -> Event:
    return Event(phase=phase, message=message, kind=kind, payload=payload)


EventStream = AsyncIterator[Event]

#: Stages receive an emitter instead of yielding, so a single code path serves
#: the headless runner, the TUI, and tests. See pipeline/orchestrator.py.
Emitter = Callable[[Event], Awaitable[None]]


async def collect_emit(sink: list[Event]) -> Emitter:
    """Build an emitter that appends to `sink`; used by tests and the headless runner."""

    async def emit(evt: Event) -> None:
        sink.append(evt)

    return emit
