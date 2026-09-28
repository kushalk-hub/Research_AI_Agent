"""The LLM spend allowance is scoped to a run.

`get_spender` is a process-wide singleton keyed by budget and event loop. That is
right for sharing one allowance across the stages of a single run, and wrong
across runs: the second run in the same event loop would start already charged
for the first one's requests, and could refuse work it had budget for.
"""

from __future__ import annotations

import pytest

from rla.config import Settings
from rla.llm.retry import Spender, get_spender, reset_spender
from rla.pipeline.orchestrator import Pipeline


@pytest.fixture
def settings(tmp_path):
    return Settings(
        gemini_api_key="",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        figures_dir=tmp_path / "figures",
        cache_db=tmp_path / "cache.db",
    )


async def _drain(pipeline, title):
    return [evt async for evt in pipeline.run(title, "")]


async def test_a_run_starts_with_a_fresh_allowance(settings):
    reset_spender()
    pipeline = Pipeline(settings, llm=None, cache=None, tracker=None)

    # Burn the allowance before the run, as an earlier run in this loop would.
    burned = get_spender(1)
    await burned.acquire("extract")

    await _drain(pipeline, "first")

    spender = get_spender(1)
    assert spender.spent == 0, "the run inherited the previous spend"


async def test_two_runs_do_not_share_an_allowance(settings):
    reset_spender()
    pipeline = Pipeline(settings, llm=None, cache=None, tracker=None)

    await _drain(pipeline, "first")
    after_first = get_spender(1).spent
    await _drain(pipeline, "second")
    after_second = get_spender(1).spent

    assert after_first == after_second, "the second run was charged for the first"


async def test_the_allowance_is_not_reset_between_stages_of_one_run(settings):
    """A run shares one allowance across its stages, so it can still stop."""
    reset_spender()
    pipeline = Pipeline(settings, llm=None, cache=None, tracker=None)

    await _drain(pipeline, "first")
    spender = get_spender(1)
    await spender.acquire("extract")
    assert spender.spent == 1
    assert get_spender(1) is spender, "the spender is shared within a run"


def test_the_spender_is_rebuilt_when_the_budget_changes():
    reset_spender()
    assert get_spender(3).budget == 3
    assert get_spender(5).budget == 5
    assert get_spender(5) is get_spender(5)
    reset_spender()


async def test_an_unlimited_spender_still_counts():
    spender = Spender(0)
    await spender.acquire("extract")
    await spender.acquire("resolve")
    assert spender.spent == 2, "unlimited means no ceiling, not no accounting"
