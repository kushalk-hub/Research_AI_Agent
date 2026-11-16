"""Single event contract shared by live execution, simulation, and replay."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fods.event_meta import describe
from fods.safety import safe_value, sanitise_paths


@dataclass(slots=True)
class RuntimeEvent:
    seq: int
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    # Optional display enrichment (design §6 row 1). Written for every new event;
    # absent from the 82 logs recorded before it existed, which is why the UI
    # keeps its own `describeEvent()` fallback.
    summary: str | None = None
    phase: str | None = None
    # `class` is a Python keyword, so the attribute is `event_class` and the wire
    # key stays `class` (see `to_dict`).
    event_class: str | None = None
    severity: str | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["class"] = value.pop("event_class")
        return value


class EventLog:
    def __init__(
        self,
        path: Path | None = None,
        sink: Callable[[RuntimeEvent], None] | None = None,
        roots: tuple[str, ...] = (),
    ) -> None:
        self.path = path
        self.sink = sink
        # A-11: when the log feeds a browser, absolute paths are rewritten at
        # emit time. Empty by default, so CLI logs stay as written.
        self.roots = roots
        self.events: list[RuntimeEvent] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, kind: str, message: str, **payload: Any) -> RuntimeEvent:
        safe_message = sanitise_paths(safe_value(message), self.roots)
        safe_payload = sanitise_paths(safe_value(payload), self.roots)
        event = RuntimeEvent(
            len(self.events) + 1,
            kind,
            safe_message,
            safe_payload,
            **describe(kind, safe_message, safe_payload),
        )
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        if self.sink is not None:
            self.sink(event)
        return event


def read_events(
    path: Path, *, strict: bool = True
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], int]:
    """Read a JSONL event log.

    ``strict=True`` keeps the historical contract: a malformed line raises
    ``ValueError``. ``strict=False`` returns ``(events, skipped)`` so a single
    corrupt write cannot hide a run from the history or break a backfill.
    """
    events: list[dict[str, Any]] = []
    skipped = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"invalid event JSON on line {line_number}: {exc}") from exc
            skipped += 1
            continue
        if not isinstance(value, dict):
            if strict:
                raise ValueError(f"invalid event on line {line_number}: expected an object")
            skipped += 1
            continue
        events.append(value)
    if strict:
        return events
    return events, skipped
