"""Rank-agreement diagnostics between Mammoth and FODS rankings."""

from __future__ import annotations

from typing import Any


def _ranks_by_key(pairs: list[tuple[str, int]]) -> dict[str, int]:
    return {k: r for k, r in pairs}


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None

    # rank-based
    def rank(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        for pos, i in enumerate(order):
            r[i] = float(pos + 1)
        return r

    rx = rank(xs)
    ry = rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = (sum((v - mx) ** 2 for v in rx)) ** 0.5
    dy = (sum((v - my) ** 2 for v in ry)) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def kendall(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    conc = 0
    disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = (xs[i] - xs[j]) * (ys[i] - ys[j])
            if a > 0:
                conc += 1
            elif a < 0:
                disc += 1
    denom = n * (n - 1) / 2
    if denom == 0:
        return None
    return (conc - disc) / denom


def top_overlap(mammoth_keys: list[str], fods_keys: list[str], k: int) -> int:
    return len(set(mammoth_keys[:k]) & set(fods_keys[:k]))


def compare_universe(
    mammoth_ranked_keys: list[str],
    fods_ranked_keys: list[str],
) -> dict[str, Any]:
    common = [k for k in mammoth_ranked_keys if k in set(fods_ranked_keys)]
    # build aligned rank arrays on common set
    m_rank = {k: i + 1 for i, k in enumerate(mammoth_ranked_keys)}
    f_rank = {k: i + 1 for i, k in enumerate(fods_ranked_keys)}
    common_sorted = sorted(common)
    xs = [float(m_rank[k]) for k in common_sorted]
    ys = [float(f_rank[k]) for k in common_sorted]
    return {
        "common_count": len(common),
        "spearman": spearman(xs, ys),
        "kendall": kendall(xs, ys),
        "top5_overlap": top_overlap(mammoth_ranked_keys, fods_ranked_keys, 5),
        "top10_overlap": top_overlap(mammoth_ranked_keys, fods_ranked_keys, 10),
    }
