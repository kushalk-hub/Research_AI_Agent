"""Load and validate the pooled review dataset."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Candidate:
    query_id: str
    topic: str
    question: str
    paper_key: str
    paper_id: str
    title: str
    year: str
    doi: str
    abstract: str
    sources: str
    quick_rank: str
    deep_rank: str
    in_quick: str
    in_deep: str

    @property
    def candidate_id(self) -> str:
        return f"{self.query_id}::{self.paper_key}"


def load_dataset(path: Path) -> tuple[list[Candidate], str]:
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("dataset is empty")
    required = {"query_id", "topic", "question", "paper_key", "title", "abstract"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"dataset missing columns: {sorted(missing)}")
    cands: list[Candidate] = []
    seen: set[str] = set()
    for r in rows:
        cid = f"{r['query_id']}::{r['paper_key']}"
        if cid in seen:
            raise ValueError(f"duplicate candidate id: {cid}")
        seen.add(cid)
        cands.append(
            Candidate(
                query_id=r["query_id"],
                topic=r.get("topic", ""),
                question=r.get("question", ""),
                paper_key=r["paper_key"],
                paper_id=r.get("paper_id", ""),
                title=r.get("title", ""),
                year=r.get("year", ""),
                doi=r.get("doi", ""),
                abstract=r.get("abstract", ""),
                sources=r.get("sources", ""),
                quick_rank=r.get("quick_rank", ""),
                deep_rank=r.get("deep_rank", ""),
                in_quick=r.get("in_quick", ""),
                in_deep=r.get("in_deep", ""),
            )
        )
    # validate query count
    qids = sorted(set(c.query_id for c in cands))
    if len(qids) != 10:
        raise ValueError(f"expected 10 queries, found {len(qids)}")
    # validate 45 per query
    from collections import Counter

    counts = Counter(c.query_id for c in cands)
    for q, n in counts.items():
        if n != 45:
            raise ValueError(f"query {q} has {n} candidates, expected 45")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return cands, sha
