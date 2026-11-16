from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fods_frontend" / "demo_data.json"


def test_frontend_fixture_is_explicitly_synthetic_and_has_known_outcomes():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert data["dataset_label"] == "SYNTHETIC DEMONSTRATION DATA — NOT REAL RESEARCH RESULTS"
    assert {paper["expected_relevance"] for paper in data["papers"]} == {
        "relevant",
        "partially_relevant",
        "not_relevant",
    }
    tasks = {task["id"]: task for task in data["task_plan"]["tasks"]}
    assert tasks["join_context"]["depends_on"] == ["search_alpha", "search_beta", "search_gamma"]
    assert data["task_plan"]["fifo_order"] == ["search_alpha", "search_beta", "search_gamma"]
    assert data["task_plan"]["priority_order"] == ["search_beta", "search_gamma", "search_alpha"]
    assert data["answer_scenarios"]["success"]["valid"] is True
    assert data["answer_scenarios"]["blocked"]["valid"] is False
    provenance = data["illustrative_event_projection"]["provenance"]
    assert provenance.startswith("Synthetic event projection")


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is optional for frontend-core tests"
)
def test_frontend_event_projection_tracks_queue_activity_states_and_citations():
    script = r"""
const core = require('./src/fods/web/shell-core.js');
const data = require('./tests/fixtures/fods_frontend/demo_data.json');
const events = data.illustrative_event_projection.events;
const active = core.deriveSnapshot(events, 8);
const finished = core.deriveSnapshot(events, 16);
const evidence = core.findEvidenceByCitation(finished.evidence, 'P1');
console.log(JSON.stringify({
  activeIds: active.activeTasks.map((task) => task.task_id),
  workerAssignmentsAvailable: active.workerAssignmentsAvailable,
  queueIds: active.readyQueue.map((task) => task.task_id),
  completed: finished.taskStates.search_alpha,
  selectedEvent: finished.selectedEvent.seq,
  answer: finished.answer,
  stack: core.deriveSnapshot(events, 9).stacks.search_alpha,
  evidencePaper: evidence.paper.id,
  liveLabel: core.executionLabel({ run_kind: 'live', mode: 'live' }),
  simulationLabel: core.executionLabel({ run_kind: 'simulate', mode: 'simulate' }),
  replayLabel: core.executionLabel({ run_kind: 'replay', mode: 'simulate' }),
  taskEventIndex: core.eventIndexForTask(events, 'search_alpha'),
  evidenceLane: core.laneForEvent('evidence_selected'),
  next: core.stepCursor(6, 1, events.length),
  previous: core.stepCursor(7, -1, events.length),
  reset: core.clampCursor(0, events.length)
}));
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True
    )
    actual = json.loads(result.stdout)

    assert actual["activeIds"] == ["search_beta", "search_alpha"]
    assert actual["workerAssignmentsAvailable"] is False
    assert actual["queueIds"] == ["search_beta", "search_alpha"]
    assert actual["completed"] == "completed"
    assert actual["selectedEvent"] == 16
    assert actual["answer"] == "Synthetic answer [P1]"
    assert actual["stack"] == ["run:synthetic", "task:search_alpha"]
    assert actual["evidencePaper"] == "SYN-PAPER-01"
    assert actual["liveLabel"] == "LIVE"
    assert actual["simulationLabel"] == "SIMULATION"
    assert actual["replayLabel"] == "REPLAY"
    assert actual["taskEventIndex"] == 10
    assert actual["evidenceLane"] == "Evidence"
    assert (actual["next"], actual["previous"], actual["reset"]) == (7, 6, 0)


def test_frontend_shell_is_a_module_entry_without_the_legacy_classic_script():
    frontend = ROOT / "stitch_aesthetic_markdown_reader"
    page = (frontend / "index.html").read_text(encoding="utf-8")
    app = (frontend / "src" / "main.jsx").read_text(encoding="utf-8")

    assert '<div id="root"></div>' in page
    assert 'src="/src/main.jsx"' in page
    assert 'type="module"' in page
    assert "shell-core.js" not in page
    assert "StoreProvider" in app
    assert "createRoot" in app
    # The served build sends `style-src 'self'`; inline style would be blocked.
    assert "<style" not in page.lower()
    assert not re.search(r"\sstyle=", page)


def test_frontend_source_avoids_csp_unsafe_and_remote_constructs():
    root = ROOT / "stitch_aesthetic_markdown_reader" / "src"
    files = sorted([*(root.rglob("*.js")), *(root.rglob("*.jsx")), *(root.rglob("*.css"))])
    assert files, "frontend sources must exist"

    for path in files:
        content = path.read_text(encoding="utf-8")
        assert "dangerouslySetInnerHTML" not in content, path
        assert 'setAttribute("style"' not in content, path
        assert "setAttribute('style'" not in content, path
        assert "@import url(http" not in content, path
        assert "fonts.googleapis" not in content, path
        assert "fonts.gstatic" not in content, path
        assert "cdn.jsdelivr" not in content, path
        assert "unpkg.com" not in content, path
        if path.suffix in {".js", ".jsx"}:
            # React turns style={{...}} into a style attribute, which the CSP blocks.
            assert not re.search(r"style=\{\{", content), path


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is optional for frontend-core tests"
)
def test_event_projection_distinguishes_unrecorded_queue_from_recorded_empty_queue():
    result = subprocess.run(
        [
            "node",
            "-e",
            "const core=require('./src/fods/web/shell-core.js');"
            "const unknown=core.deriveSnapshot([],0);"
            "const empty=core.deriveSnapshot([{seq:1,kind:'queue_updated',"
            "payload:{operation:'dequeue',ready_queue:[]}}],1);"
            "console.log(JSON.stringify({unknown:unknown.queueRecorded,"
            "empty:empty.queueRecorded,emptyLength:empty.readyQueue.length," 
            "workerIds:empty.workerAssignmentsAvailable}));",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "unknown": False,
        "empty": True,
        "emptyLength": 0,
        "workerIds": False,
    }


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is optional for D3 geometry tests"
)
def test_vendored_d3_generates_curved_svg_dependency_paths():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = {};
for (const file of [
  'src/fods/web/vendor/d3-path-3.1.0.min.js',
  'src/fods/web/vendor/d3-shape-3.2.0.min.js'
]) vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
const path = context.d3.line().x((point) => point.x).y((point) => point.y)
  .curve(context.d3.curveBumpX)([{x: 10, y: 20}, {x: 110, y: 80}]);
console.log(JSON.stringify({
  versionedShape: fs.readFileSync('src/fods/web/vendor/d3-shape-3.2.0.min.js', 'utf8')
    .startsWith('// https://d3js.org/d3-shape/ v3.2.0'),
  path
}));
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True
    )
    actual = json.loads(result.stdout)

    assert actual["versionedShape"] is True
    assert actual["path"].startswith("M10,20C")
    assert actual["path"].endswith("110,80")
