"""The composer mirrors `NewRun`'s bounds in JavaScript; this test is the seam.

UI-04's risk note: "Duplicated bounds drift from NewRun. Mitigation: derive the
UI bounds from /api/config and keep one constant table with a test that compares
it to the pydantic model." This is that test. It reads the fallback table out of
`model.js` and compares every bound to the pydantic field, so changing one
without the other fails here rather than in the browser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fods.webapp import NewRun

MODEL_JS = (
    Path(__file__).resolve().parents[1]
    / "stitch_aesthetic_markdown_reader"
    / "src"
    / "composer"
    / "model.js"
)

#: JS limit key -> (pydantic field, metadata attribute)
PAIRS = {
    "topic_min": ("topic", "min_length"),
    "topic_max": ("topic", "max_length"),
    "question_min": ("question", "min_length"),
    "question_max": ("question", "max_length"),
    "paper_limit_min": ("paper_limit", "ge"),
    "paper_limit_max": ("paper_limit", "le"),
    "provider_wait_seconds_min": ("provider_wait_seconds", "ge"),
    "provider_wait_seconds_max": ("provider_wait_seconds", "le"),
    "llm_request_budget_min": ("llm_request_budget", "ge"),
    "llm_request_budget_max": ("llm_request_budget", "le"),
    "concurrency_min": ("concurrency", "ge"),
    "concurrency_max": ("concurrency", "le"),
    "source_limit_min": ("source_limit", "ge"),
    "source_limit_max": ("source_limit", "le"),
    "delay_ms_min": ("delay_ms", "ge"),
    "delay_ms_max": ("delay_ms", "le"),
}


def _js_limits() -> dict[str, float]:
    source = MODEL_JS.read_text(encoding="utf-8")
    match = re.search(r"export const LIMITS = Object\.freeze\(\{(.*?)\}\);", source, re.S)
    assert match, f"LIMITS table not found in {MODEL_JS}"
    found = {
        key: float(value)
        for key, value in re.findall(r"([a-z_]+):\s*([0-9.]+)\s*,", match.group(1))
    }
    assert found, "LIMITS table parsed empty"
    return found


def _pydantic_bound(field: str, attribute: str) -> float:
    metadata = NewRun.model_fields[field].metadata
    for item in metadata:
        value = getattr(item, attribute, None)
        if value is not None:
            return float(value)
    raise AssertionError(f"NewRun.{field} has no {attribute} constraint ({metadata!r})")


def test_composer_limits_match_new_run_bounds():
    limits = _js_limits()
    mismatches = []
    for js_key, (field, attribute) in PAIRS.items():
        expected = _pydantic_bound(field, attribute)
        actual = limits.get(js_key)
        if actual is None:
            mismatches.append(f"{js_key} missing from model.js LIMITS")
        elif actual != expected:
            mismatches.append(f"{js_key}: model.js={actual} NewRun.{field}.{attribute}={expected}")
    assert not mismatches, "\n".join(mismatches)


def test_composer_limits_cover_every_pair():
    assert set(_js_limits()) == set(PAIRS)


@pytest.mark.parametrize("field", ["paper_limit", "llm_request_budget"])
def test_composer_limits_are_bounded_not_open_ended(field):
    """Both fields must have a maximum: an open-ended budget is exactly A-06."""
    assert _pydantic_bound(field, "le") > 0
