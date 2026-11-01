"""Deterministic ranking of Mammoth candidate decisions."""

from __future__ import annotations


def rank_candidates(decisions: list) -> tuple[list, list, list]:
    """Return (ranked, unassessable, failed) lists.

    ranked sorted by expected_relevance desc, then paper_key asc.
    """
    ranked = [d for d in decisions if d.status == "ok" and d.expected_relevance is not None]
    unassessable = [d for d in decisions if d.status == "unassessable"]
    failed = [d for d in decisions if d.status == "failed"]
    ranked.sort(key=lambda d: (-d.expected_relevance, d.paper_key))
    for i, d in enumerate(ranked, start=1):
        d.rank = i  # type: ignore[attr-defined]
    return ranked, unassessable, failed
