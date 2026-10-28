"""Create a self-contained visual run report from the runtime event stream."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _duration(events: list[dict[str, Any]], task_id: str) -> tuple[float, float] | None:
    started = next(
        (
            event["timestamp"]
            for event in events
            if event["kind"] == "task_started" and event["payload"].get("task_id") == task_id
        ),
        None,
    )
    ended = next(
        (
            event["timestamp"]
            for event in events
            if event["kind"] in {"task_completed", "task_failed", "task_blocked"}
            and event["payload"].get("task_id") == task_id
        ),
        None,
    )
    if started is None:
        return None
    return float(started), float(ended if ended is not None else started)


def write_run_html(events: list[dict[str, Any]], path: Path) -> Path:
    """Write an offline DAG, task-state, and measured concurrency visualization."""
    received = next((event for event in events if event["kind"] == "plan_received"), {})
    repaired = next((event for event in events if event["kind"] == "plan_repaired"), {})
    validated = next((event for event in events if event["kind"] == "plan_validated"), {})
    tasks = repaired.get("payload", {}).get("tasks") or received.get("payload", {}).get("tasks", [])
    levels = validated.get("payload", {}).get("levels", [])
    if not levels and tasks:
        levels = [[task["id"] for task in tasks]]
    tasks_by_id = {task["id"]: task for task in tasks}
    task_events = {
        event.get("payload", {}).get("task_id"): event
        for event in events
        if event["kind"] in {"task_completed", "task_failed", "task_blocked", "task_cancelled"}
    }
    level_markup = []
    for level_num, ids in enumerate(levels, start=1):
        cards = []
        for task_id in ids:
            task = tasks_by_id.get(task_id, {})
            result_event = task_events.get(task_id, {})
            state = result_event.get("kind", "not started").replace("task_", "")
            deps = ", ".join(task.get("depends_on", [])) or "none"
            cards.append(
                '<article class="node"><b>'
                + _text(task_id)
                + "</b>"
                + "<span>"
                + _text(task.get("tool", ""))
                + "</span>"
                + "<small>state: "
                + _text(state)
                + " · priority: "
                + _text(task.get("priority", 0))
                + "</small>"
                + "<small>depends on: "
                + _text(deps)
                + "</small></article>"
            )
        level_markup.append(
            '<section class="level"><h3>Level '
            + str(level_num)
            + '</h3><div class="nodes">'
            + "".join(cards)
            + "</div></section>"
        )

    starts = [event["timestamp"] for event in events if event["kind"] == "task_started"]
    ends = [
        event["timestamp"]
        for event in events
        if event["kind"] in {"task_completed", "task_failed", "task_blocked", "task_cancelled"}
    ]
    origin = min(starts, default=0.0)
    span = max(ends, default=origin) - origin
    if span <= 0:
        span = 1.0
    lanes = []
    for task_id in tasks_by_id:
        timing = _duration(events, task_id)
        result_event = task_events.get(task_id, {})
        state = result_event.get("kind", "not started").replace("task_", "")
        if timing:
            start, end = timing
            left = max(0.0, (start - origin) / span * 100)
            width = max(0.5, (end - start) / span * 100)
            bar = (
                '<div class="bar '
                + _text(state)
                + '" style="left:'
                + f"{left:.3f}"
                + "%;width:"
                + f"{width:.3f}"
                + '%" title="'
                + _text(f"{(end-start)*1000:.1f} ms")
                + '"></div>'
            )
            label = f"{(end-start)*1000:.1f} ms"
        else:
            bar, label = '<span class="not-run">not run</span>', ""
        lanes.append(
            '<div class="lane"><strong>'
            + _text(task_id)
            + '</strong><div class="track">'
            + bar
            + "</div><small>"
            + _text(state)
            + (" · " + _text(label) if label else "")
            + "</small></div>"
        )

    run_mode = next(
        (
            event.get("payload", {}).get("mode", "unknown")
            for event in events
            if event["kind"] == "plan_received"
        ),
        "unknown",
    )
    cache_mode = received.get("payload", {}).get("source_cache_mode", "configured")
    if run_mode == "live":
        run_mode = (
            f"live · {'fresh source cache' if cache_mode == 'fresh' else 'configured source cache'}"
        )
    schedule = validated.get("payload", {}).get("schedule", "not scheduled")
    finish = next((event for event in events if event["kind"] == "run_finished"), {})
    outcome = finish.get("message", "plan rejected or run incomplete")
    event_rows = "".join(
        "<tr><td>"
        + _text(event.get("seq", ""))
        + "</td><td>"
        + _text(event.get("kind", ""))
        + "</td><td>"
        + _text(event.get("message", ""))
        + "</td></tr>"
        for event in events
    )
    page = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FODS run visualization</title>
<style>
 :root{{color-scheme:light dark;font:15px/1.45 system-ui,Segoe UI,sans-serif}}
 body{{max-width:1180px;margin:32px auto;padding:0 20px;background:#10151d;color:#e8eef5}}
 h1,h2{{margin-bottom:8px}}.muted,small{{color:#a7b5c4}}
 .summary{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}}
 .pill{{border:1px solid #344256;border-radius:9px;padding:10px 14px;background:#192331}}
 .levels{{display:flex;gap:12px;overflow-x:auto;align-items:stretch}}
 .level{{min-width:190px;flex:1}}
 .node{{display:grid;gap:4px;margin:8px 0;padding:12px;border:1px solid #3a4a5e}}
 .node{{border-left:4px solid #51bba3;border-radius:8px;background:#192331}}
 .node span{{color:#70c9e3}}.node small{{font-size:12px}}
 .lane{{display:grid;grid-template-columns:190px 1fr 130px;gap:12px;margin:10px 0}}
 .lane{{align-items:center}}.track{{height:18px;position:relative;background:#202b39}}
 .track{{border-radius:20px;overflow:hidden}}
 .bar{{position:absolute;top:0;height:100%;min-width:4px;border-radius:20px;background:#54c5a4}}
 .bar.failed,.bar.blocked{{background:#ee7272}}.bar.cancelled,.not-run{{color:#d5a34e}}
 table{{border-collapse:collapse;width:100%;margin-top:16px}}
 td,th{{border-bottom:1px solid #344256;padding:8px;text-align:left}}
 details{{margin:18px 0}}
</style>
<body>
<h1>FODS runtime: research to evidence-backed brief</h1>
<p class="muted">This view comes from recorded runtime events. Timing bars show this run.</p>
<div class="summary">
<div class="pill">Evidence mode: <b>{_text(run_mode)}</b></div>
<div class="pill">Scheduler: <b>{_text(schedule)}</b></div>
<div class="pill">Tasks: <b>{len(tasks)}</b></div>
<div class="pill">Outcome: <b>{_text(outcome)}</b></div></div>
<h2>Task DAG by readiness level</h2><div class="levels">{''.join(level_markup)}</div>
<h2>Execution lanes</h2>
<p class="muted">Overlapping bars show concurrent tasks. Replay reproduces the record only.</p>
{''.join(lanes)}
<details><summary>Recorded event sequence ({len(events)} events)</summary>
<table><thead><tr><th>#</th><th>Event</th><th>Details</th></tr></thead>
<tbody>{event_rows}</tbody></table></details>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
