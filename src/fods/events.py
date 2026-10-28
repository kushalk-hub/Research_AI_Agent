"""Single event contract shared by live execution, simulation, and replay."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fods.safety import safe_value


@dataclass(slots=True)
class RuntimeEvent:
    seq: int
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventLog:
    def __init__(
        self,
        path: Path | None = None,
        sink: Callable[[RuntimeEvent], None] | None = None,
    ) -> None:
        self.path = path
        self.sink = sink
        self.events: list[RuntimeEvent] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, kind: str, message: str, **payload: Any) -> RuntimeEvent:
        event = RuntimeEvent(
            len(self.events) + 1,
            kind,
            safe_value(message),
            safe_value(payload),
        )
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        if self.sink is not None:
            self.sink(event)
        return event


def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid event JSON on line {line_number}: {exc}") from exc
    return events
