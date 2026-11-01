from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tools.mammoth_evaluator.artifacts import make_eval_dir, write_json
from tools.mammoth_evaluator.batching import build_batches
from tools.mammoth_evaluator.client import MODEL_ID, OpenRouterDecisionClient
from tools.mammoth_evaluator.comparison import compare_universe
from tools.mammoth_evaluator.dataset import load_dataset
from tools.mammoth_evaluator.decision_schema import (
    compute_expected_relevance,
    normalize_response,
)
from tools.mammoth_evaluator.ranking import rank_candidates
from tools.mammoth_evaluator.scoring import apply_decision


def test_dataset_loads_and_validates(tmp_path):
    # copy pooled file
    src = Path("benchmarks/pooled_review_20261031.csv")
    if not src.exists():
        pytest.skip("pooled dataset not present")
    cands, sha = load_dataset(src)
    assert len(cands) == 450
    assert len(set(c.query_id for c in cands)) == 10
    assert all(
        len([x for x in cands if x.query_id == q]) == 45 for q in set(c.query_id for c in cands)
    )


def test_normalize_response_and_expected_relevance():
    resp = {
        "answers": {
            "assessability": {
                "type": "choice",
                "choice": "assessable",
                "probabilities": {"assessable": 0.9, "insufficient_evidence": 0.1},
                "confidence": 0.9,
            },
            "relevance": {
                "type": "score",
                "score": 1.5,
                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.2, "3": 0.3, "4": 0.3},
                "confidence": 0.9,
                "legend": {
                    "0": "Not relevant",
                    "1": "Tangential",
                    "2": "Partially relevant",
                    "3": "Relevant",
                    "4": "Highly relevant",
                },
            },
        }
    }
    nds = normalize_response(resp, ["assessability", "relevance"])
    assert nds["assessability"].choice == "assessable"
    exp, p45 = compute_expected_relevance(nds["relevance"])
    # levels 1..5 weighted: indices 0..4 -> levels 1..5
    # probs: 0.1,0.1,0.2,0.3,0.3 -> exp = 1*0.1+2*0.1+3*0.2+4*0.3+5*0.3 = 0.1+0.2+0.6+1.2+1.5=3.6
    assert abs(exp - 3.6) < 1e-9
    assert abs(p45 - 0.6) < 1e-9


def test_insufficient_evidence_sets_unassessable():
    from tools.mammoth_evaluator.decision_schema import CandidateDecision

    cd = CandidateDecision(
        query_id="Q01", candidate_id="c1", paper_key="p1", title="t", year="2020"
    )
    resp = {
        "answers": {
            "assessability": {
                "type": "choice",
                "choice": "insufficient_evidence",
                "probabilities": {"assessable": 0.2, "insufficient_evidence": 0.8},
                "confidence": 0.8,
            },
            "relevance": {
                "type": "score",
                "score": 0.5,
                "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0},
                "confidence": 0.5,
                "legend": {},
            },
        }
    }
    apply_decision(
        cd, resp, 10.0, {"request_id": "r1", "usage": {"input_tokens": 5, "cost": 0.001}}
    )
    assert cd.status == "unassessable"
    assert cd.assessability == "insufficient_evidence"


def test_ranking_tiebreak():
    from tools.mammoth_evaluator.decision_schema import CandidateDecision

    d1 = CandidateDecision(
        query_id="Q01",
        candidate_id="a",
        paper_key="b",
        title="t",
        year="2020",
        expected_relevance=3.0,
        status="ok",
    )
    d2 = CandidateDecision(
        query_id="Q01",
        candidate_id="b",
        paper_key="a",
        title="t",
        year="2020",
        expected_relevance=3.0,
        status="ok",
    )
    ranked, una, fail = rank_candidates([d1, d2])
    assert [d.paper_key for d in ranked] == ["a", "b"]


def test_comparison_metrics():
    a = ["p1", "p2", "p3"]
    b = ["p1", "p3", "p2"]
    res = compare_universe(a, b)
    assert res["common_count"] == 3
    assert res["top5_overlap"] >= 0


def test_batching_one_candidate_per_batch():
    src = Path("benchmarks/pooled_review_20261031.csv")
    if not src.exists():
        pytest.skip("pooled dataset not present")
    from tools.mammoth_evaluator.dataset import load_dataset

    cands, _ = load_dataset(src)
    qs = [c for c in cands if c.query_id == "Q01"]
    batches = build_batches(qs[:5])
    assert len(batches) == 5
    for b in batches:
        assert len(b.candidate_ids) == 1


def test_artifacts_no_overwrite(tmp_path):
    d = make_eval_dir(tmp_path, "eval1")
    write_json(d / "a.json", {"x": 1})
    with pytest.raises(FileExistsError):
        write_json(d / "a.json", {"x": 2})
    make_eval_dir(tmp_path, "eval1") if False else None
    with pytest.raises(FileExistsError):
        make_eval_dir(tmp_path, "eval1")


def test_client_probe_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        OpenRouterDecisionClient()


def test_client_catalog_and_probe_mocked(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": MODEL_ID,
                            "architecture": {"output_modalities": ["decisions"]},
                            "context_length": 16384,
                            "pricing": {"prompt": "0.0000001", "completion": "0"},
                        }
                    ]
                },
            )
        if "alpha/decisions" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "gen-1",
                    "model": MODEL_ID,
                    "provider": "BaseTen",
                    "answers": {"probe": {"type": "noul", "noul": 0.5}},
                    "usage": {"input_tokens": 10, "output_tokens": 0, "cost": 0.000001},
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async def run():
        async with OpenRouterDecisionClient(
            api_key="test-key", client=httpx.AsyncClient(transport=transport)
        ) as c:
            entry = await c.catalog_check()
            assert entry["id"] == MODEL_ID
            probe = await c.probe()
            assert probe["_status_code"] == 200
            assert "probe" in probe["answers"]

    import asyncio

    asyncio.run(run())


def test_cli_preflight_no_network(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    from tools.mammoth_evaluator import client as C

    async def fake_catalog(self):
        return {
            "id": MODEL_ID,
            "context_length": 16384,
            "pricing": {},
            "architecture": {"output_modalities": ["decisions"]},
        }

    async def fake_probe(self, state="probe", question="Is this a probe?"):
        return {
            "_status_code": 200,
            "_latency_ms": 1.0,
            "answers": {"probe": {"type": "noul", "noul": 0.5}},
            "model": MODEL_ID,
            "usage": {},
        }

    monkeypatch.setattr(C.OpenRouterDecisionClient, "catalog_check", fake_catalog)
    monkeypatch.setattr(C.OpenRouterDecisionClient, "probe", fake_probe)
    import argparse

    from tools.mammoth_evaluator.cli import cmd_preflight

    args = argparse.Namespace()
    rc = cmd_preflight(args)
    assert rc == 0
