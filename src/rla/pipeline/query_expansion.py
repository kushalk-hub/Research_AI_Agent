"""Title -> search queries (spec section 2, layer 1).

An async generator: yields progress Events and writes the queries into the
caller-owned `into` list, because a generator cannot also return a value.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel, Field

from rla.events import Event, Phase, event
from rla.llm.base import LLMClient, LLMError
from rla.llm.prompts.templates import QUERY_EXPANSION
from rla.models import content_hash

DEFAULT_QUERY_COUNT = 4


def _reason(exc: Exception, limit: int = 140) -> str:
    """Provider errors are multi-kilobyte JSON blobs; keep the log readable."""
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


class QuerySet(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=8)


async def expand_title(
    title: str,
    llm: LLMClient,
    into: list[str],
    count: int = DEFAULT_QUERY_COUNT,
    model: str = "",
) -> AsyncIterator[Event]:
    """Generate 3-5 sub-topic queries, falling back to the raw title on failure.

    The fallback matters: acquisition is keyless-friendly, so a missing or
    rate-limited LLM must degrade to a plain title search rather than abort.
    """
    yield event(
        Phase.SEARCH,
        "Generating search queries from title",
        title=title,
        prompt_hash=content_hash(title)[:12],
    )

    queries: list[str] = []
    try:
        result = await llm.generate_structured(
            QUERY_EXPANSION.format(title=title, n=count),
            QuerySet,
            stage="query_expansion",
            model=model or None,
        )
        queries = [q.strip() for q in result.queries if q and q.strip()]
    except LLMError as exc:
        yield event(
            Phase.SEARCH,
            f"Query expansion failed, falling back to the raw title ({_reason(exc)})",
            kind="warn",
        )

    if not queries:
        queries = [title]

    queries = list(dict.fromkeys(queries))[:count]
    into.extend(queries)
    yield event(Phase.SEARCH, f"Generated {len(queries)} queries", kind="ok", queries=queries)
