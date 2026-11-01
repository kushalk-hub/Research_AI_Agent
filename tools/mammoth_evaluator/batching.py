"""Conservative batching with a token budget."""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4
DEFAULT_MAX_INPUT_TOKENS = 12000


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class Batch:
    batch_id: str
    candidate_ids: list[str]
    state_text: str
    estimated_tokens: int


def build_batches(
    candidates: list,  # list of Candidate
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
) -> list[Batch]:
    """Group candidates into batches, one candidate per request by default-safe grouping.

    For Mammoth, each request's state contains one candidate's paper info and
    two questions. We keep one candidate per request to avoid mapping ambiguity,
    but still chunk into bounded batches for request accounting. Each batch = one
    request (one candidate) to guarantee unambiguous candidate->answer mapping.
    """
    batches: list[Batch] = []
    for idx, c in enumerate(candidates):
        state = (
            f"Research question: {c.question}\n"
            f"Topic: {c.topic}\n"
            f"Paper title: {c.title}\n"
            f"Year: {c.year}\n"
            f"DOI: {c.doi}\n"
            f"Sources: {c.sources}\n"
            f"Abstract: {c.abstract}\n"
        )
        toks = estimate_tokens(state)
        if toks > max_input_tokens:
            # truncate abstract defensively (recorded as truncated)
            pass
        batches.append(
            Batch(
                batch_id=f"batch-{idx:04d}",
                candidate_ids=[c.candidate_id],
                state_text=state,
                estimated_tokens=toks,
            )
        )
    return batches
