from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fods.tools import segment_text
from rla.models import Paper, content_hash


def _version(paper_id: str, revision: int) -> tuple[dict, dict]:
    abstract = (
        "Graph attention networks improve node classification. "
        f"Revision {revision} provides additional evidence."
    )
    paper = Paper(id=paper_id, title=f"Paper {paper_id}", abstract=abstract)
    paper.ensure_hash()
    first, second = segment_text(abstract)
    enrichment = {
        "paper_id": paper_id,
        "paper_hash": paper.content_hash,
        "concepts": [
            {
                "text": f"concept {paper_id} v{revision}",
                "role": "uses",
                "evidence_segment_ids": [first["segment_id"]],
                "evidence_excerpt": first["text"],
            }
        ],
        "methods": [],
        "findings": [
            {
                "text": f"finding {paper_id} v{revision}",
                "evidence_segment_ids": [second["segment_id"]],
                "evidence_excerpt": second["text"],
            }
        ],
        "limitations": [],
    }
    return paper.model_dump(mode="json"), enrichment


def _save_context(data_dir: Path, topic: str, papers: dict[str, dict]) -> str:
    topic_key = content_hash(topic)[:16]
    context_root = data_dir / "fods" / "topics"
    version_dir = context_root / topic_key
    version_dir.mkdir(parents=True, exist_ok=True)
    context = {"schema_version": 3, "papers": list(papers.values())}
    context_id = content_hash(topic, json.dumps(context, sort_keys=True))
    context["context_hash"] = context_id
    (version_dir / f"{context_id}.json").write_text(json.dumps(context), encoding="utf-8")
    return context_id


def _wait_for(path: Path, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _run_merge(root: Path, *, disable_lock: bool) -> tuple[bool, bool, str, str]:
    root.mkdir(parents=True)
    data_dir = root / "data"
    topic = f"process merge {root.name}"
    topic_key = content_hash(topic)[:16]

    revisions = {
        paper_id: [_version(paper_id, 0), _version(paper_id, 1)] for paper_id in ("A", "B")
    }
    initial_papers = {paper_id: pair[0][0] for paper_id, pair in revisions.items()}
    all_enrichments = [pair[revision][1] for pair in revisions.values() for revision in (0, 1)]
    enrich_dir = data_dir / "fods" / "enrichments"
    enrich_dir.mkdir(parents=True, exist_ok=True)
    (enrich_dir / "all-versions.json").write_text(
        json.dumps({"topic": topic, "paper_enrichments": all_enrichments}), encoding="utf-8"
    )

    initial_id = _save_context(data_dir, topic, initial_papers)
    context_a = {"A": revisions["A"][1][0], "B": revisions["B"][0][0]}
    context_b = {"A": revisions["A"][1][0], "B": revisions["B"][1][0]}
    context_a_id = _save_context(data_dir, topic, context_a)
    context_b_id = _save_context(data_dir, topic, context_b)
    context_root = data_dir / "fods" / "topics"
    (context_root / f"{topic_key}.latest").write_text(initial_id, encoding="utf-8")

    base_env = os.environ.copy()
    base_env["RLA_DATA_DIR"] = str(data_dir)
    command = [sys.executable, "-m", "fods.cli"]
    built = subprocess.run(
        [*command, "graph", "build", "--topic", topic],
        cwd=Path.cwd(),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert built.returncode == 0, (built.stdout, built.stderr)

    hook_dir = root / "hooks"
    hook_dir.mkdir()
    hook_code = """
from contextlib import contextmanager
import os
from pathlib import Path
import time
import fods.knowledge_graph as kg
gate = Path(os.environ["FODS_CLI_GATE_DIR"])
name = os.environ["FODS_CLI_PROCESS"]
real_lock = kg.topic_lock
real_publish = kg.publish
def mark(label):
    (gate / label).write_text("ready", encoding="utf-8")
@contextmanager
def observed_lock(path):
    if name == "B": mark("B_LOCK_ATTEMPT")
    with real_lock(path):
        if name == "A": mark("A_LOCK_HELD")
        yield
if os.environ.get("FODS_CLI_DISABLE_LOCK") == "1":
    @contextmanager
    def observed_lock(path):
        if name == "B": mark("B_LOCK_ATTEMPT")
        if name == "A": mark("A_LOCK_HELD")
        yield
kg.topic_lock = observed_lock
def gated_publish(path, snapshot):
    mark(name + "_PUBLISH_READY")
    release = gate / ("RELEASE_" + name)
    deadline = time.monotonic() + 20
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("parent did not release the test publish gate")
        time.sleep(0.01)
    return real_publish(path, snapshot)
kg.publish = gated_publish
"""
    (hook_dir / "sitecustomize.py").write_text(hook_code, encoding="utf-8")
    gate = root / "gates"
    gate.mkdir()
    env = base_env | {
        "PYTHONPATH": os.pathsep.join(
            [str(hook_dir), str(Path.cwd() / "src"), base_env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
        "FODS_CLI_GATE_DIR": str(gate),
        "FODS_CLI_DISABLE_LOCK": "1" if disable_lock else "0",
    }

    def launch(name: str, context_id: str) -> subprocess.Popen:
        return subprocess.Popen(
            [*command, "graph", "update", "--topic", topic, "--context-id", context_id],
            cwd=Path.cwd(),
            env=env | {"FODS_CLI_PROCESS": name},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    proc_a = launch("A", context_a_id)
    proc_b = None
    try:
        assert _wait_for(gate / "A_LOCK_HELD")
        assert _wait_for(gate / "A_PUBLISH_READY")
        proc_b = launch("B", context_b_id)
        assert _wait_for(gate / "B_LOCK_ATTEMPT")
        if disable_lock:
            assert _wait_for(gate / "B_PUBLISH_READY")
            (gate / "RELEASE_B").write_text("go", encoding="utf-8")
            out_b, err_b = proc_b.communicate(timeout=15)
            assert proc_b.returncode == 0, (out_b, err_b)
            (gate / "RELEASE_A").write_text("go", encoding="utf-8")
            out_a, err_a = proc_a.communicate(timeout=15)
        else:
            # B has reached the real lock boundary while A is paused just before
            # atomic publication. It must not read/publish the stale snapshot yet.
            assert not _wait_for(gate / "B_PUBLISH_READY", timeout=0.3)
            (gate / "RELEASE_A").write_text("go", encoding="utf-8")
            out_a, err_a = proc_a.communicate(timeout=15)
            assert proc_a.returncode == 0, (out_a, err_a)
            assert _wait_for(gate / "B_PUBLISH_READY")
            (gate / "RELEASE_B").write_text("go", encoding="utf-8")
            out_b, err_b = proc_b.communicate(timeout=15)
        assert proc_a.returncode == 0, (out_a, err_a)
        assert proc_b.returncode == 0, (out_b, err_b)
    finally:
        for process in (proc_a, proc_b):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    from fods.knowledge_graph import validate

    graph_path = data_dir / "fods" / "knowledge_graph" / topic_key / "graph.json"
    snapshot = json.loads(graph_path.read_text(encoding="utf-8"))
    validate(snapshot)
    labels = {node["label"] for node in snapshot["nodes"].values()}
    return "finding A v1" in labels, "finding B v1" in labels, out_a, out_b


def test_actual_cli_subprocesses_preserve_distinct_updates_and_control_exposes_race(tmp_path):
    serialized = _run_merge(tmp_path / "serialized", disable_lock=False)
    assert serialized[0] and serialized[1]
    assert "0 new, 1 changed, 0 deleted; 1 reprocessed" in serialized[2]
    assert "0 new, 1 changed, 0 deleted; 1 reprocessed" in serialized[3]

    unprotected = _run_merge(tmp_path / "unprotected", disable_lock=True)
    assert unprotected[0]
    assert not unprotected[1]
    assert "0 new, 2 changed, 0 deleted; 2 reprocessed" in unprotected[3]
