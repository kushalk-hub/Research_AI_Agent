"""Readable, actionable failure reporting in the answer stage.

`rla ask` is the one command a human reads at a terminal, so it is the one place
an untruncated multi-kilobyte provider blob is most damaging. These tests pin
both halves: the blob is cut, and the guidance survives the cut.
"""

from __future__ import annotations

from rla.llm.errors import (
    ErrorCategory,
    ProviderAuthFailed,
    ProviderError,
    ProviderServerError,
)
from rla.pipeline.answer import _CATEGORY_GUIDANCE, _ERROR_LIMIT, _reason

#: A realistic Gemini 429 body: long, multi-line, and JSON-ish. Exactly the shape
#: that used to be printed verbatim.
GEMINI_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota, please check your plan and billing details. For more information "
    "on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To "
    "monitor your current usage, head to: https://ai.dev/rate-limit. \\n* Quota "
    "exceeded for metric: generativelanguage.googleapis.com/generate_content_free_"
    "tier_requests, limit: 20, model: gemini-2.5-flash\\nPlease retry in 1.357883222s.', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more "
    "about Gemini API quotas'}]}]}}"
)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def test_a_provider_blob_is_truncated():
    out = _reason(ProviderError(GEMINI_429, category=ErrorCategory.QUOTA_EXHAUSTED))
    assert len(out) <= _ERROR_LIMIT + 1
    assert out.endswith("…")


def test_a_short_error_is_not_truncated():
    out = _reason(ProviderError("Read timed out", category=ErrorCategory.TIMEOUT))
    assert out == "timeout: Read timed out"


def test_an_untyped_exception_is_still_truncated_not_crashed():
    """A backend that raises a bare Exception must not break error reporting."""
    out = _reason(Exception(GEMINI_429))
    assert len(out) <= _ERROR_LIMIT + 1


def test_a_short_untyped_exception_passes_through():
    assert _reason(Exception("boom")) == "boom"


# ---------------------------------------------------------------------------
# Actionability -- the part that is easy to lose to truncation
# ---------------------------------------------------------------------------


def test_the_category_is_the_headline():
    out = _reason(ProviderError(GEMINI_429, category=ErrorCategory.QUOTA_EXHAUSTED))
    assert out.startswith("quota exhausted:")


def test_quota_guidance_survives_truncation():
    """The instruction must not be the thing that gets cut.

    An earlier version appended the guidance after the provider text, so on any
    real-sized error the guidance was truncated away entirely and the user saw the
    same useless blob with extra words.
    """
    out = _reason(ProviderError(GEMINI_429, category=ErrorCategory.QUOTA_EXHAUSTED))
    assert "daily" in out
    assert "RLA_FALLBACK_ON_QUOTA" in out


def test_auth_guidance_names_the_key_and_the_401_cause():
    out = _reason(ProviderAuthFailed("401 UNAUTHENTICATED"))
    assert "GEMINI_API_KEY" in out
    assert "OAuth" in out


def test_a_transient_error_gets_no_guidance():
    """Timeouts and 5xx already retried themselves; a hint would be noise."""
    out = _reason(ProviderServerError("503 overloaded"))
    assert out == "server error: 503 overloaded"


def test_every_guidance_key_is_a_real_category():
    """A typo in a key silently disables that guidance.

    This happened on the first attempt: the keys were written with a space
    (`"quota exhausted"`) while `str(ErrorCategory.QUOTA_EXHAUSTED)` is
    `"quota_exhausted"`, so every lookup missed.
    """
    for key in _CATEGORY_GUIDANCE:
        assert key in {str(c) for c in ErrorCategory}, key


# ---------------------------------------------------------------------------
# End to end through the answer stage
# ---------------------------------------------------------------------------


async def test_a_failed_answer_reports_the_category_not_a_raw_blob():
    from rla.models import Concept, EdgeType, Paper, Relation
    from rla.pipeline.answer import answer_question
    from rla.store.graph_store import build_graph

    class OutOfQuota:
        async def stream_text(self, prompt, *, model=None, temperature=0.0, stage="llm"):
            raise ProviderError(GEMINI_429, category=ErrorCategory.QUOTA_EXHAUSTED)
            yield ""

    paper = Paper(id="p1", title="Graph Attention Networks", year=2018)
    relation = Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES)
    graph, _, _ = build_graph(
        [paper],
        [Concept(id="c:gat", name="graph attention networks", first_seen_year=2018)],
        [relation],
    )

    events = [
        e async for e in answer_question(graph, "how did GAT evolve?", OutOfQuota())
    ]
    errors = [e for e in events if e.kind == "error"]

    assert errors, "an out-of-quota answer must surface as an error event"
    message = errors[0].message
    assert message.startswith("answer generation failed")
    assert "quota exhausted" in message
    assert "RLA_FALLBACK_ON_QUOTA" in message
    assert len(message) < 400, f"error line still too long: {len(message)}"
    # The raw JSON must not be dumped wholesale.
    assert "'details'" not in message


async def test_a_quota_failure_still_yields_the_traversal_first():
    """The subgraph is free and deterministic, so it should not be lost.

    A reader can still see what the system found even when it cannot narrate it,
    which is what makes the failure diagnosable.
    """
    from rla.models import Concept, EdgeType, Paper, Relation
    from rla.pipeline.answer import answer_question
    from rla.store.graph_store import build_graph

    class OutOfQuota:
        async def stream_text(self, prompt, *, model=None, temperature=0.0, stage="llm"):
            raise ProviderError(GEMINI_429, category=ErrorCategory.QUOTA_EXHAUSTED)
            yield ""

    paper = Paper(id="p1", title="Graph Attention Networks", year=2018)
    relation = Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES)
    graph, _, _ = build_graph(
        [paper],
        [Concept(id="c:gat", name="graph attention networks", first_seen_year=2018)],
        [relation],
    )

    events = [
        e async for e in answer_question(graph, "how did GAT evolve?", OutOfQuota())
    ]
    phases = [e.phase for e in events]
    assert "traverse" in [str(p) for p in phases]
    assert phases.index([p for p in phases if str(p) == "traverse"][0]) < len(phases) - 1
