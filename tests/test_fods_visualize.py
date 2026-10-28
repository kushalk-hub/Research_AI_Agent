from fods.visualize import write_run_html


def test_run_visualization_shows_readiness_and_timed_task_lanes(tmp_path):
    events = [
        {
            "seq": 1,
            "kind": "plan_received",
            "message": "plan",
            "payload": {
                "mode": "simulate",
                "tasks": [
                    {"id": "source_a", "tool": "search_a", "priority": 10, "depends_on": []},
                    {"id": "source_b", "tool": "search_b", "priority": 20, "depends_on": []},
                ],
            },
            "timestamp": 1.0,
        },
        {
            "seq": 2,
            "kind": "plan_validated",
            "message": "valid",
            "payload": {"schedule": "fifo", "levels": [["source_a", "source_b"]]},
            "timestamp": 1.1,
        },
        {
            "seq": 3,
            "kind": "task_started",
            "message": "start",
            "payload": {"task_id": "source_a"},
            "timestamp": 2.0,
        },
        {
            "seq": 4,
            "kind": "task_started",
            "message": "start",
            "payload": {"task_id": "source_b"},
            "timestamp": 2.1,
        },
        {
            "seq": 5,
            "kind": "task_completed",
            "message": "done",
            "payload": {"task_id": "source_a"},
            "timestamp": 3.0,
        },
        {
            "seq": 6,
            "kind": "task_completed",
            "message": "done",
            "payload": {"task_id": "source_b"},
            "timestamp": 3.1,
        },
        {
            "seq": 7,
            "kind": "run_finished",
            "message": "run completed",
            "payload": {"succeeded": True},
            "timestamp": 3.2,
        },
    ]

    report = write_run_html(events, tmp_path / "run.html")
    rendered = report.read_text(encoding="utf-8")

    assert "Task DAG by readiness level" in rendered
    assert "source_a" in rendered and "source_b" in rendered
    assert "Overlapping bars show concurrent tasks" in rendered
    assert 'class="bar completed"' in rendered
