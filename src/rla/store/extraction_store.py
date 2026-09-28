"""Append-only store for per-paper extractions (P2).

Two properties matter here:

- **Append-only JSONL.** Each extraction is written the moment it succeeds, so
  a run killed halfway leaves a valid, usable prefix behind instead of a
  half-written file.
- **Keyed by paper content hash, not paper id.** A paper whose abstract is
  corrected or enriched by a better source produces a different hash, so its
  stale extraction is simply not found and gets redone. Keying on id alone would
  keep the outdated answer forever.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from rla.models import Extraction


class ExtractionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._by_hash: dict[str, Extraction] = {}
        self.load()

    def load(self) -> None:
        """Read every persisted extraction; a corrupt line is skipped, not fatal."""
        self._by_hash.clear()
        if not self.path.exists():
            return
        for line in self.path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                extraction = Extraction.model_validate_json(line)
            except (ValidationError, json.JSONDecodeError):
                continue
            if extraction.paper_hash:
                self._by_hash[extraction.paper_hash] = extraction

    def get(self, paper_hash: str) -> Extraction | None:
        return self._by_hash.get(paper_hash)

    def add(self, extraction: Extraction) -> None:
        """Record an extraction and flush it to disk immediately."""
        key = extraction.paper_hash
        if not key:
            raise ValueError("cannot store an extraction without a paper_hash")
        self._by_hash[key] = extraction
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(extraction.model_dump_json() + "\n")

    def all(self) -> list[Extraction]:
        return list(self._by_hash.values())

    def __len__(self) -> int:
        return len(self._by_hash)
