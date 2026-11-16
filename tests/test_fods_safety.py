"""A-11: absolute workspace paths never reach the browser."""

from __future__ import annotations

from fods.safety import relative_path, sanitise_paths

WINDOWS_ROOT = "D:\\Research_AI_Agent-fods"
POSIX_ROOT = "/home/analyst/fods"


def test_a_path_under_a_root_becomes_forward_slash_relative():
    assert (
        relative_path("D:\\Research_AI_Agent-fods\\data\\graph\\graph.json", (WINDOWS_ROOT,))
        == "data/graph/graph.json"
    )
    assert relative_path("/home/analyst/fods/data/x.json", (POSIX_ROOT,)) == "data/x.json"


def test_the_root_itself_becomes_dot_and_unknown_roots_keep_the_basename():
    assert relative_path("D:\\Research_AI_Agent-fods", (WINDOWS_ROOT,)) == "."
    assert (
        relative_path("C:\\Somewhere Else\\secret\\graph.json", (WINDOWS_ROOT,))
        == "…/graph.json"
    )


def test_roots_match_case_insensitively_on_windows_paths():
    assert (
        relative_path("d:\\research_ai_agent-fods\\data\\x.json", (WINDOWS_ROOT,))
        == "data/x.json"
    )


def test_sanitise_paths_rewrites_nested_payloads_and_leaves_other_text_alone():
    roots = (WINDOWS_ROOT,)
    value = {
        "path": "D:\\Research_AI_Agent-fods\\data\\graph\\graph.json",
        "nested": [
            {"extraction_store": "D:\\Research_AI_Agent-fods\\data\\extractions.jsonl"},
            "graph built at D:\\Research_AI_Agent-fods\\data\\graph",
        ],
        "message": "graph built",
        "count": 3,
        "none": None,
    }

    cleaned = sanitise_paths(value, roots)

    assert cleaned["path"] == "data/graph/graph.json"
    assert cleaned["nested"][0]["extraction_store"] == "data/extractions.jsonl"
    assert cleaned["nested"][1] == "graph built at data/graph"
    assert cleaned["message"] == "graph built"
    assert cleaned["count"] == 3
    assert cleaned["none"] is None


def test_urls_and_plain_text_are_not_touched():
    roots = (WINDOWS_ROOT,)
    for text in (
        "https://example.com/papers/123",
        "http://127.0.0.1:8765/api/runs/0123456789ab",
        "no path here at all",
        "C# citations",
    ):
        assert sanitise_paths(text, roots) == text


def test_an_unrecognised_absolute_path_is_trimmed_rather_than_leaked():
    # The workspace root is not known here (a different checkout), so the
    # directory structure must still not be published.
    assert (
        sanitise_paths("saved to C:\\Other Checkout\\data\\briefs\\x.md", (WINDOWS_ROOT,))
        == "saved to …/x.md"
    )
