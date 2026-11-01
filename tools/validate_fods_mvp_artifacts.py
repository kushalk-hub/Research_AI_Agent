"""Validate the outputs of the deterministic FODS MVP workflow run."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _read_trace(path: Path) -> list[dict[str, Any]]:
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}, line {line_number}: {exc}") from exc
        if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
            raise ValueError(f"invalid event shape in {path}, line {line_number}")
        events.append(event)
    if not events:
        raise ValueError(f"trace is empty: {path}")
    return events


def _event(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("kind") == kind]
    if len(matches) != 1:
        raise ValueError(f"expected one {kind!r} event, found {len(matches)}")
    return matches[0]


def _relative(path: str) -> str:
    return Path(path).as_posix().removeprefix("./")


def validate(brief_path: Path, runs_dir: Path, topic: str, question: str) -> dict[str, Any]:
    brief_path = brief_path.resolve()
    if not brief_path.is_file() or brief_path.stat().st_size == 0:
        raise ValueError(f"brief is missing or empty: {brief_path}")

    brief = brief_path.read_text(encoding="utf-8")
    if not brief.startswith(f"# Evidence-backed brief: {topic}"):
        raise ValueError("brief heading does not match the requested topic")
    if f"**Question:** {question}" not in brief or "## Sources" not in brief:
        raise ValueError("brief is missing the question or source-reference section")

    expected_output = _relative(str(brief_path.relative_to(Path.cwd().resolve())))
    matched: list[tuple[Path, list[dict[str, Any]]]] = []
    for trace_path in sorted(runs_dir.glob("*.jsonl")):
        events = _read_trace(trace_path)
        starts = [event for event in events if event.get("kind") == "run_started"]
        plans = [event for event in events if event.get("kind") == "plan_received"]
        if len(starts) != 1 or len(plans) != 1:
            continue
        start_payload, plan_payload = starts[0]["payload"], plans[0]["payload"]
        if (
            start_payload.get("mode") == "simulate"
            and start_payload.get("planner") == "fixture"
            and start_payload.get("topic") == topic
            and start_payload.get("question") == question
            and _relative(str(plan_payload.get("output_path", ""))) == expected_output
        ):
            matched.append((trace_path, events))

    if len(matched) != 1:
        raise ValueError(
            f"expected one matching fixture trace for {expected_output}, found {len(matched)}"
        )
    trace_path, events = matched[0]
    run_id = _event(events, "run_started")["payload"].get("run_id")
    if not run_id or trace_path.stem != run_id:
        raise ValueError("run ID is missing or does not match the trace filename")

    plan = _event(events, "plan_received")["payload"].get("tasks", [])
    planned_ids = {task.get("id") for task in plan if task.get("id")}
    if not planned_ids:
        raise ValueError("the run plan contains no tasks")
    completed_ids = {
        event["payload"].get("task_id")
        for event in events
        if event.get("kind") == "task_completed" and event["payload"].get("task_id")
    }
    failed = [event for event in events if event.get("kind") == "task_failed"]
    if failed:
        failed_ids = sorted({event["payload"].get("task_id", "unknown") for event in failed})
        raise ValueError(f"the run contains failed task attempts: {failed_ids}")
    if planned_ids != completed_ids:
        raise ValueError(
            "planned task outcomes do not all complete: "
            f"missing={sorted(planned_ids - completed_ids)}, "
            f"unexpected={sorted(completed_ids - planned_ids)}"
        )

    terminal = _event(events, "run_finished")
    if events[-1] is not terminal or terminal["payload"].get("succeeded") is not True:
        raise ValueError("the trace does not end in a successful terminal outcome")
    if any(
        event.get("kind") in {"source_http_attempt", "model_call_started", "model_call_completed"}
        for event in events
    ):
        raise ValueError("the fixture run unexpectedly emitted provider or model-call events")

    context = _event(events, "context_ready")["payload"]
    if int(context.get("retained_paper_count", context.get("paper_count", 0))) < 1:
        raise ValueError("the run did not persist a research context with papers")
    selection = _event(events, "evidence_selected")["payload"]
    evidence = selection.get("evidence", [])
    citation_to_paper = {
        item.get("citation"): item.get("paper", {}).get("id")
        for item in evidence
        if item.get("citation") and item.get("paper", {}).get("id")
    }
    if not citation_to_paper:
        raise ValueError("evidence selection contains no citation-to-paper mappings")

    validation_event = _event(events, "citation_validation")["payload"]
    if validation_event.get("valid") is not True or validation_event.get("unknown"):
        raise ValueError("citation validation did not succeed")
    if not set(validation_event.get("allowed", [])) <= citation_to_paper.keys():
        raise ValueError("citation validation allowed IDs do not resolve to selected papers")
    found = set(validation_event.get("found", []))
    if not found or not found <= citation_to_paper.keys():
        raise ValueError("answer citations do not resolve to selected papers")
    for claim in validation_event.get("claim_evidence_map", []):
        for citation in claim.get("citations", []):
            paper_ids = claim.get("paper_ids", [])
            if citation not in citation_to_paper or citation_to_paper[citation] not in paper_ids:
                raise ValueError(f"claim citation {citation} does not map to its selected paper")

    brief_citations = set(re.findall(r"\[(P\d+)\]", brief))
    if not brief_citations or not brief_citations <= citation_to_paper.keys():
        raise ValueError("brief source citations do not resolve to selected evidence")
    source_section = brief.split("## Sources", maxsplit=1)[1]
    for item in evidence:
        citation = item["citation"]
        title = item["paper"]["title"]
        if f"[{citation}]" not in source_section or title not in source_section:
            raise ValueError(f"brief source list is missing selected paper {citation}: {title}")

    saved = _event(events, "brief_saved")["payload"]
    if saved.get("saved") is not True or saved.get("citations_validated") is not True:
        raise ValueError("brief-saved event does not confirm validated output")
    if Path(str(saved.get("path", ""))).resolve() != brief_path:
        raise ValueError("brief-saved path does not match the requested output path")

    html_path = trace_path.with_suffix(".html")
    if not html_path.is_file() or html_path.stat().st_size == 0:
        raise ValueError(f"run visualization is missing or empty: {html_path}")

    return {
        "run_id": run_id,
        "task_count": len(planned_ids),
        "tasks_completed": len(completed_ids),
        "failed_task_attempts": len(failed),
        "context_papers": int(context.get("retained_paper_count", context.get("paper_count", 0))),
        "evidence_cards": len(evidence),
        "validated_answer_citations": sorted(found),
        "brief_path": str(brief_path),
        "trace_path": str(trace_path.resolve()),
        "html_path": str(html_path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--question", required=True)
    args = parser.parse_args()
    try:
        result = validate(args.brief, args.runs_dir, args.topic, args.question)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FODS acceptance validation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## FODS fixture acceptance",
            "",
            f"- Run ID: `{result['run_id']}`",
            f"- Tasks: {result['tasks_completed']}/{result['task_count']} completed",
            f"- Context papers: {result['context_papers']}",
            f"- Evidence cards: {result['evidence_cards']}",
            f"- Validated answer citations: {', '.join(result['validated_answer_citations'])}",
            f"- Brief: `{result['brief_path']}`",
            f"- Trace: `{result['trace_path']}`",
            f"- Visualization: `{result['html_path']}`",
            "",
        ]
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
