"""Persist evaluation artifacts without overwriting."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def make_eval_dir(base: Path, eval_id: str) -> Path:
    d = base / eval_id
    if d.exists():
        raise FileExistsError(f"evaluation directory already exists: {d}")
    d.mkdir(parents=True, exist_ok=False)
    return d


def write_json(path: Path, obj: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def new_eval_id() -> str:
    return datetime.now(UTC).strftime("mammoth1_%Y%m%dT%H%M%SZ")
