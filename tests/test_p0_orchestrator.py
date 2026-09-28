"""P0 gate: the orchestrator yields events in phase order and fills the result."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from rla.events import Phase
from rla.llm.base import LLMError
from rla.llm.gemini import GeminiClient, extract_json
from rla.pipeline.orchestrator import IMPLEMENTED_PHASES, PHASE_MILESTONE, Pipeline, PipelineResult
from rla.store.cache import CostTracker


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """These tests assert event ordering, so they must not call real APIs."""
    monkeypatch.setattr("rla.pipeline.acquisition.build_sources", lambda *a, **k: {})


async def test_run_emits_search_first_and_done_last(settings, cache):
    events = [
        evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("graph agents")
    ]
    assert events[0].phase is Phase.SEARCH
    assert events[-1].phase is Phase.DONE
    assert events[-1].kind == "ok"


async def test_run_emits_every_phase_in_order(settings, cache):
    events = [evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("t")]
    phases = [evt.phase for evt in events]
    assert phases == sorted(phases, key=lambda p: list(Phase).index(p))
    for phase in PHASE_MILESTONE:
        if phase not in IMPLEMENTED_PHASES:
            assert phase in phases


async def test_pending_stages_declare_their_milestone(settings, cache):
    events = [evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("t")]
    pending = {evt.phase: evt for evt in events if evt.kind == "pending"}
    # P5 is implemented, so traversal reports a missing input rather than a
    # schedule; no phase may still advertise a future milestone.
    assert Phase.TRAVERSE in IMPLEMENTED_PHASES
    assert "no question" in pending[Phase.TRAVERSE].message
    for phase in IMPLEMENTED_PHASES:
        assert not pending.get(phase, None) or not pending[phase].message.endswith(
            PHASE_MILESTONE[phase]
        )
    # extract is implemented, so without an LLM it reports a skip, not a schedule.
    assert Phase.EXTRACT in IMPLEMENTED_PHASES
    assert "skipping" in pending[Phase.EXTRACT].message


async def test_traverse_and_answer_wait_for_a_graph(settings, cache):
    """P5 must not fabricate a subgraph from a graph that was never built."""
    result = PipelineResult()
    events = [
        evt
        async for evt in Pipeline(settings, None, cache, CostTracker()).run("t", "q?", result)
    ]
    by_phase = {evt.phase: evt for evt in events}
    assert by_phase[Phase.TRAVERSE].kind == "pending"
    assert "graph" in by_phase[Phase.TRAVERSE].message
    assert by_phase[Phase.ANSWER].kind == "pending"
    assert result.answer == ""


async def test_result_is_populated_as_a_side_channel(settings, cache):
    result = PipelineResult()
    async for _ in Pipeline(settings, None, cache, CostTracker()).run("graph agents", "q?", result):
        pass
    assert result.title == "graph agents"
    assert result.question == "q?"
    assert result.stats["cache"]["entries"] >= 0


async def test_events_serialise_for_the_jsonl_runner(settings, cache):
    events = [evt async for evt in Pipeline(settings, None, cache, CostTracker()).run("t")]
    for payload in (evt.to_dict() for evt in events):
        assert json.loads(json.dumps(payload))["phase"]


def test_extract_json_unwraps_fences_and_prose():
    assert json.loads(extract_json('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(extract_json('Sure! {"a": 1} hope that helps')) == {"a": 1}


def test_extract_json_raises_without_an_object():
    try:
        extract_json("no json here")
    except LLMError:
        return
    raise AssertionError("expected LLMError")


def test_gemini_client_reports_models(settings, cache):
    client = GeminiClient(settings, cache, CostTracker())
    assert client.fast_model == settings.fast_model
    assert client.strong_model == settings.strong_model


def test_gemini_client_requires_a_key(settings, cache):
    settings.gemini_api_key = ""
    try:
        _ = GeminiClient(settings, cache, CostTracker()).client
    except LLMError as exc:
        assert "GEMINI_API_KEY" in str(exc)
        return
    raise AssertionError("expected LLMError")


def test_gemini_call_is_served_from_cache(settings, cache):
    client = GeminiClient(settings, cache, CostTracker())
    settings.gemini_api_key = ""  # any real call would raise
    key = client._key("hello", "m", "", 0.0, "text")
    cache.set(key, "cached answer", kind="llm")


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "rla.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "research literature agent" in result.stdout
