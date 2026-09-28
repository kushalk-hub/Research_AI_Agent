"""P0 gate: events, models, cache, dedup keys, CLI-visible config."""

from __future__ import annotations

import json

from rla.events import PIPELINE_PHASES, Phase
from rla.llm.prompts.templates import prompt_hash
from rla.models import Concept, Corpus, Extraction, Paper, content_hash
from rla.sources.base import dedup_keys, make_paper_id, normalise_doi, title_key
from rla.store.cache import CostTracker, RateLimiter, cache_key


def test_phase_order_is_stable():
    assert list(PIPELINE_PHASES) == [
        Phase.SEARCH,
        Phase.FETCH,
        Phase.SCORE,
        Phase.FULLTEXT,
        Phase.EXTRACT,
        Phase.RESOLVE,
        Phase.GRAPH,
        Phase.TRAVERSE,
        Phase.ANSWER,
        Phase.DONE,
    ]


def test_event_serialises_to_json():
    payload = {
        "phase": "graph",
        "message": "added edge",
        "kind": "info",
        "payload": {"n": 1},
        "timestamp": 1.0,
    }
    assert json.loads(json.dumps(payload)) == payload


def test_content_hash_is_order_and_whitespace_stable():
    assert content_hash("a", 1) == content_hash("a", 1)
    assert content_hash("a", 1) != content_hash("a", 2)


def test_paper_hash_is_content_addressed(papers):
    first, second = papers[0], papers[0].model_copy()
    assert first.ensure_hash() == second.ensure_hash()
    assert first.ensure_hash() != papers[1].ensure_hash()


def test_extraction_hash_changes_with_content(papers):
    base = Extraction(paper_id="p1", summary="a")
    changed = Extraction(paper_id="p1", summary="b")
    assert base.ensure_hash() != changed.ensure_hash()


def test_concept_slug_is_stable():
    assert Concept.slug("Graph Attention Networks!") == Concept.slug("  graph attention networks ")
    assert Concept.slug("A -- B") == "concept:a-b"


def test_corpus_stats_and_citation_labels(papers):
    corpus = Corpus(title="t", papers=papers)
    stats = corpus.stats()
    assert stats["papers"] == 3
    assert stats["with_abstract"] == 0
    assert corpus.cited_ids()["p1"] == 1


def test_cache_roundtrip_and_hit_accounting(cache):
    assert cache.get_json("missing") is None
    cache.set_json("k", {"a": [1, 2]})
    assert cache.get_json("k") == {"a": [1, 2]}
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1


def test_cache_kinds_are_namespaced(cache):
    cache.set("same", "http-body", kind="http")
    cache.set("same", "llm-body", kind="llm")
    assert cache.get("same", kind="http") == "http-body"
    assert cache.get("same", kind="llm") == "llm-body"


def test_cache_key_ignores_param_order():
    assert cache_key("p", "http://x", {"a": 1, "b": 2}) == cache_key(
        "p", "http://x", {"b": 2, "a": 1}
    )
    assert cache_key("p", "http://x", {"a": 1}) != cache_key("p", "http://x", {"a": 2})


def test_cost_tracker_totals_and_stage_breakdown():
    tracker = CostTracker()
    tracker.record("extract", 100, 20)
    tracker.record("answer", 50, 30)
    report = tracker.to_dict("gemini-2.5-flash")
    assert report["calls"] == 2
    assert report["input_tokens"] == 150
    assert report["by_stage"]["extract"]["output"] == 20
    assert report["estimated_usd"] > 0


def test_cost_estimate_is_unknown_not_zero_for_unpriced_model():
    """An unpriced model must report "unknown", never a confident $0.00.

    A zero here is indistinguishable from a model that genuinely costs nothing,
    so a model whose price this build does not know would silently understate
    spend. `None` plus `unpriced_model` is the honest answer.
    """
    tracker = CostTracker()
    tracker.record("extract", 1_000_000, 1_000_000)
    assert tracker.estimate_usd("some-unknown-model") is None
    report = tracker.to_dict("some-unknown-model")
    assert report["estimated_usd"] is None
    assert report["cost_status"] == "unpriced_model"
    assert report["model_priced"] is False


def test_cost_estimate_survives_a_provider_prefix():
    """A `provider/model` routing string must price as the bare model id.

    LiteLLM routes on `gemini/gemini-2.5-flash`; the direct backend uses
    `gemini-2.5-flash`. Both mean the same model and must not differ in price.
    """
    tracker = CostTracker()
    tracker.record("extract", 1_000_000, 0)
    assert tracker.estimate_usd("gemini/gemini-2.5-flash") == tracker.estimate_usd(
        "gemini-2.5-flash"
    )


def test_flash_lite_is_not_priced_as_flash():
    """Regression: substring pricing matched 'flash' inside 'flash-lite'.

    The old lookup iterated the pricing table in insertion order and used
    `key in model`, so the cheap model inherited the full model's rate -- a 3x
    overcharge on input, on the model that does most of the work.
    """
    from rla.store.cache import price_for

    assert price_for("gemini-2.5-flash-lite") == (0.10, 0.40)
    assert price_for("gemini-2.5-flash") == (0.30, 2.50)
    assert price_for("gemini-2.5-flash-lite") != price_for("gemini-2.5-flash")


def test_unknown_usage_is_reported_as_unknown_not_zero():
    """A provider that omits usage must not make the run look free.

    One unmeasurable call poisons the aggregate, because the true total is
    genuinely not knowable. Reporting 0 instead would make a provider swap that
    broke usage parsing look like a cost *reduction*.
    """
    tracker = CostTracker()
    tracker.record("extract", 100, 20)
    tracker.record("extract", None, None)
    report = tracker.to_dict("gemini-2.5-flash")
    assert report["input_tokens"] is None
    assert report["estimated_usd"] is None
    assert report["cost_status"] == "unknown_usage"
    assert report["unknown_usage_calls"] == 1
    assert report["calls"] == 2  # both calls still counted


async def test_rate_limiter_serialises_calls():
    import time

    limiter = RateLimiter(0.05)
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # Two gaps of 50ms. The window is deliberately far larger than the Windows
    # 15.6ms timer quantum: the previous 10ms setting asked for a 19ms floor,
    # which is inside the scheduler's own slack and failed roughly 40% of runs on
    # this machine -- a flaky assertion that says nothing about the limiter.
    assert elapsed >= 0.09, f"limiter only enforced {elapsed:.4f}s"


def test_prompt_hash_tracks_prompt_text():
    assert prompt_hash("a") == prompt_hash("a")
    assert prompt_hash("a") != prompt_hash("b")


def test_serpapi_is_disabled_without_key(settings):
    assert "serpapi" not in settings.enabled_sources()


def test_serpapi_enables_with_key(settings):
    settings.serpapi_api_key = "x"
    assert "serpapi" in settings.enabled_sources()


# -- dedup keys (P0 groundwork, fully exercised in P1) -----------------------


def test_doi_normalisation():
    assert normalise_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalise_doi("doi:10.1234/abc") == "10.1234/abc"
    assert normalise_doi("not-a-doi") == ""


def test_title_key_ignores_punctuation_and_stopwords():
    assert title_key("The Graph-of-Agents: A Survey!") == title_key("graph of agents a survey")


def test_dedup_keys_prefer_doi():
    paper = Paper(id="p", title="Some Title", doi="https://doi.org/10.1/x", arxiv_id="2401.00001")
    keys = dedup_keys(paper)
    assert keys[0] == "doi:10.1/x"
    assert "arxiv:2401.00001" in keys


def test_paper_id_prefers_doi_then_arxiv_then_title():
    assert make_paper_id(Paper(id="x", title="T", doi="10.1/a")) == "doi:10.1/a"
    assert make_paper_id(Paper(id="x", title="T", arxiv_id="2401.1")) == "arxiv:2401.1"
    assert make_paper_id(Paper(id="x", title="T")).startswith("t:")
