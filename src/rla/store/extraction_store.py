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
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from rla.models import Corpus, Extraction


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

    def rewrite(self, extractions: Iterable[Extraction]) -> int:
        """Replace the file's contents, atomically. Returns the row count.

        `add` appends, so pruning has to rewrite. A plain `write_text` is not
        enough: an interrupted prune would leave a half-deleted store, which is
        worse than not pruning at all because it is silent. Write beside the
        target and `os.replace`, which is atomic on Windows and POSIX.
        """
        kept = list(extractions)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for extraction in kept:
                handle.write(extraction.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        self._by_hash = {e.paper_hash: e for e in kept}
        return len(kept)


@dataclass(slots=True)
class Reconciliation:
    """How the stored extractions relate to the current corpus.

    Two failure classes, deliberately kept apart because they deserve different
    responses:

    * **integrity** -- `stale` (the entry belongs to a different corpus) and
      `superseded` (the entry's paper is in the corpus but its content has since
      changed). Both mean the graph would be built from extractions that do not
      describe this corpus, so the graph stage refuses rather than warns.
    * **coverage** -- `missing`. An ordinary incomplete run. Warn, then proceed.

    `matched` counts PAPERS whose current content hash is stored, never rows.
    """

    stale: list[Extraction] = field(default_factory=list)
    superseded: list[Extraction] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    matched: int = 0

    @property
    def intact(self) -> bool:
        """Nothing in the store contradicts the corpus."""
        return not self.stale and not self.superseded

    @property
    def healthy(self) -> bool:
        """Intact AND fully covered. The committed-data invariant."""
        return self.intact and not self.missing

    @property
    def advice(self) -> str:
        parts: list[str] = []
        if self.stale:
            parts.append(
                f"delete {len(self.stale)} extraction(s) for papers that are not in the corpus"
            )
        if self.superseded:
            parts.append(
                f"delete {len(self.superseded)} extraction(s) whose paper content has "
                f"changed since extraction"
            )
        if self.missing:
            parts.append(
                f"extract {len(self.missing)} corpus paper(s) that have no current extraction"
            )
        if not parts:
            return "the extraction store and the corpus agree"
        suffix = ""
        if self.stale or self.superseded:
            suffix = " - run `rla status --prune` then `rla run`"
        elif self.missing:
            suffix = " - run `rla run` to extract the missing papers"
        return "; ".join(parts) + suffix


def reconcile(corpus: Corpus, store: ExtractionStore) -> Reconciliation:
    """Compare the store against the corpus, hash-keyed, in both directions."""
    papers = list(corpus.papers)
    wanted_ids = {paper.id for paper in papers}
    current_hash = {paper.id: paper.ensure_hash() for paper in papers}
    stored_keys = {entry.paper_hash for entry in store.all()}

    report = Reconciliation(
        stale=[e for e in store.all() if e.paper_id not in wanted_ids],
        superseded=[
            e
            for e in store.all()
            if e.paper_id in wanted_ids and e.paper_hash != current_hash[e.paper_id]
        ],
        missing=[p.id for p in papers if current_hash[p.id] not in stored_keys],
    )
    report.matched = sum(1 for p in papers if current_hash[p.id] in stored_keys)
    return report


def reconcile_extractions(corpus: Corpus, extractions: Iterable[Extraction]) -> Reconciliation:
    """`reconcile` for callers that hold a list rather than a store."""

    class _View:
        def __init__(self, items: list[Extraction]) -> None:
            self._items = list(items)

        def all(self) -> list[Extraction]:
            return self._items

    return reconcile(corpus, _View(extractions))  # type: ignore[arg-type]


def prune_stale(corpus: Corpus, store: ExtractionStore) -> list[str]:
    """Delete entries that do not describe the current corpus.

    Removes both `stale` and `superseded` entries. Returns human-readable labels
    so the operator can see what went: a paper id for staleness, `id@<hash>` for
    superseded content.
    """
    report = reconcile(corpus, store)
    doomed = {e.paper_hash for e in report.stale}
    doomed |= {e.paper_hash for e in report.superseded}
    labels = [e.paper_id for e in report.stale]
    labels += [f"{e.paper_id}@{e.paper_hash[:8]}" for e in report.superseded]

    store.rewrite([e for e in store.all() if e.paper_hash not in doomed])
    return sorted(labels)
