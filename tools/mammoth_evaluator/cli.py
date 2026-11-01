"""CLI for the Mammoth-1 evaluation sidecar."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# ensure repo root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except Exception:  # pragma: no cover
    pass

from tools.mammoth_evaluator.artifacts import (  # noqa: E402
    make_eval_dir,
    new_eval_id,
    write_csv,
    write_json,
    write_jsonl,
)
from tools.mammoth_evaluator.batching import build_batches  # noqa: E402
from tools.mammoth_evaluator.client import MODEL_ID, OpenRouterDecisionClient  # noqa: E402
from tools.mammoth_evaluator.comparison import compare_universe  # noqa: E402
from tools.mammoth_evaluator.dataset import load_dataset  # noqa: E402
from tools.mammoth_evaluator.decision_schema import (  # noqa: E402
    build_questions,
)
from tools.mammoth_evaluator.ranking import rank_candidates  # noqa: E402
from tools.mammoth_evaluator.scoring import apply_decision, make_candidate_decision  # noqa: E402


def cmd_preflight(args: argparse.Namespace) -> int:
    async def run():
        client = OpenRouterDecisionClient()
        entry = await client.catalog_check()
        print("CATALOG_OK")
        print("model_id:", entry.get("id"))
        print("context_length:", entry.get("context_length"))
        print("pricing:", entry.get("pricing"))
        print("output_modalities:", entry.get("architecture", {}).get("output_modalities"))
        # probe
        probe = await client.probe()
        print("PROBE_OK")
        print("status:", probe.get("_status_code"))
        print("latency_ms:", probe.get("_latency_ms"))
        print("answers:", list(probe.get("answers", {}).keys()))
        print("model:", probe.get("model"))
        print("usage:", probe.get("usage"))

    asyncio.run(run())
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    candidates, dataset_sha = load_dataset(input_path)
    eval_id = args.eval_id or new_eval_id()
    base = Path(args.output_dir)
    base.mkdir(parents=True, exist_ok=True)
    eval_dir = make_eval_dir(base, eval_id)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set; cannot run live evaluation")

    questions = build_questions()
    qmap = {k: v for k, v in questions.items()}

    # group candidates by query
    by_query: dict[str, list] = {}
    for c in candidates:
        by_query.setdefault(c.query_id, []).append(c)

    all_decisions: list[dict] = []
    per_query_summary: dict[str, Any] = {} if False else {}
    per_query_summary = {}
    fods_comparison: dict[str, Any] = {}

    async def run():
        nonlocal per_query_summary, fods_comparison
        progress_path = eval_dir / "progress.jsonl"
        progress_path.touch()
        async with OpenRouterDecisionClient(api_key=api_key) as client:
            # catalog check
            await client.catalog_check()
            # probe
            await client.probe()

            for qid in sorted(by_query):
                cands = by_query[qid]
                batches = build_batches(cands)
                decisions = []
                for b in batches:
                    cand = next(c for c in cands if c.candidate_id == b.candidate_ids[0])
                    cd = make_candidate_decision(cand, qid)
                    try:
                        resp, meta = await client.decide(
                            b.state_text, {k: v.to_request() for k, v in qmap.items()}
                        )
                        apply_decision(cd, resp, meta["latency_ms"], meta)
                    except Exception as exc:
                        cd.status = "failed"
                        cd.error = str(exc)
                    cd.batch_id = b.batch_id
                    cd.paper_id = cand.paper_id
                    cd.doi = cand.doi
                    decisions.append(cd)

                ranked, unassessable, failed = rank_candidates(decisions)
                for i, d in enumerate(ranked, start=1):
                    d.rank = i
                for d in decisions:
                    dd = _decision_to_dict(d)
                    all_decisions.append(dd)
                    # incremental progress
                    with progress_path.open("a", encoding="utf-8") as pf:
                        pf.write(json.dumps(dd, ensure_ascii=False, default=str) + "\n")
                        pf.flush()

                ranked, unassessable, failed = rank_candidates(decisions)
                # assign ranks
                for i, d in enumerate(ranked, start=1):
                    d.rank = i

                # FODS comparison: build fods ranked keys from pooled csv ranks
                # Quick common universe: candidates with in_quick=yes
                [
                    d.paper_key
                    for d in ranked
                    if d.paper_key in {c.paper_key for c in cands if c.in_quick == "yes"}
                ]
                # Actually need fods rank order: use deep_rank/quick_rank
                fods_quick_keys = sorted(
                    [c.paper_key for c in cands if c.in_quick == "yes"],
                    key=lambda pk: int(
                        next(c.quick_rank for c in cands if c.paper_key == pk) or 999
                    ),
                )
                fods_deep_keys = sorted(
                    [c.paper_key for c in cands],
                    key=lambda pk: int(
                        next(c.deep_rank for c in cands if c.paper_key == pk) or 999
                    ),
                )
                mammoth_keys = [d.paper_key for d in ranked]
                cmp_quick = compare_universe(
                    [k for k in mammoth_keys if k in set(fods_quick_keys)],
                    fods_quick_keys,
                )
                cmp_deep = compare_universe(mammoth_keys, fods_deep_keys)
                fods_comparison[qid] = {
                    "quick": {"comparison_universe": "common (quick candidates only)", **cmp_quick},
                    "deep": {"comparison_universe": "deep candidate set", **cmp_deep},
                }

                # per-query summary
                exps = [d.expected_relevance for d in ranked if d.expected_relevance is not None]
                per_query_summary[qid] = {
                    "candidate_count": len(cands),
                    "assessable_count": len(ranked),
                    "unassessable_count": len(unassessable),
                    "failed_count": len(failed),
                    "mean_expected_relevance": (sum(exps) / len(exps)) if exps else None,
                    "median_expected_relevance": (sorted(exps)[len(exps) // 2] if exps else None),
                    "mean_p_relevant_or_highly": (
                        sum(
                            d.p_relevant_or_highly
                            for d in ranked
                            if d.p_relevant_or_highly is not None
                        )
                        / len(ranked)
                        if ranked
                        else None
                    ),
                    "top5": [d.paper_key for d in ranked[:5]],
                    "top10": [d.paper_key for d in ranked[:10]],
                }

                # ranked csv rows
                ranked_rows = []
                for d in ranked:
                    ranked_rows.append(_decision_row(d, qid, "ranked"))
                for d in unassessable:
                    ranked_rows.append(_decision_row(d, qid, "unassessable"))
                for d in failed:
                    ranked_rows.append(_decision_row(d, qid, "failed"))

                # write per-query ranked csv (append to global later)
                # store in all_decisions already

            # write artifacts
            manifest = {
                "eval_id": eval_id,
                "dataset_path": str(input_path),
                "dataset_sha256": dataset_sha,
                "dataset_rows": len(candidates),
                "query_count": len(by_query),
                "model": MODEL_ID,
                "provider": "openrouter",
                "endpoint": "https://openrouter.ai/api/alpha/decisions",
                "rubric_version": "mammoth1_v1",
                "status": "complete",
            }
            write_json(eval_dir / "evaluation_manifest.json", manifest)

            # candidate_decisions.jsonl
            write_jsonl(eval_dir / "candidate_decisions.jsonl", all_decisions)

            # ranked_candidates.csv (global)
            fieldnames = [
                "query_id",
                "paper_key",
                "paper_id",
                "title",
                "year",
                "doi",
                "status",
                "assessability",
                "expected_relevance",
                "p_relevant_or_highly",
                "relevance_score_raw",
                "rank",
                "request_id",
                "batch_id",
                "latency_ms",
                "input_tokens",
                "cost",
            ]
            csv_rows = []
            for d in all_decisions:
                csv_rows.append(
                    {
                        "query_id": d["query_id"],
                        "paper_key": d["paper_key"],
                        "paper_id": d["paper_id"],
                        "title": d["title"],
                        "year": d["year"],
                        "doi": d["doi"],
                        "status": d["status"],
                        "assessability": d["assessability"],
                        "expected_relevance": d["expected_relevance"],
                        "p_relevant_or_highly": d["p_relevant_or_highly"],
                        "relevance_score_raw": d["relevance_score_raw"],
                        "rank": d.get("rank"),
                        "request_id": d["request_id"],
                        "batch_id": d["batch_id"],
                        "latency_ms": d["latency_ms"],
                        "input_tokens": d["input_tokens"],
                        "cost": d["cost"],
                    }
                )
            write_csv(eval_dir / "ranked_candidates.csv", csv_rows, fieldnames)

            write_json(eval_dir / "per_query_summary.json", per_query_summary)
            # run summary
            latencies = [d["latency_ms"] for d in all_decisions if d["latency_ms"] is not None]
            run_summary = {
                "eval_id": eval_id,
                "total_candidates": len(all_decisions),
                "total_requests": len(all_decisions),
                "successful": sum(
                    1 for d in all_decisions if d["status"] in ("ok", "unassessable")
                ),
                "failed": sum(1 for d in all_decisions if d["status"] == "failed"),
                "unassessable": sum(1 for d in all_decisions if d["status"] == "unassessable"),
                "total_input_tokens": sum(d["input_tokens"] or 0 for d in all_decisions),
                "total_cost": sum(d["cost"] or 0 for d in all_decisions),
                "median_latency_ms": (
                    sorted(latencies)[len(latencies) // 2] if latencies else None
                ),
                "model": MODEL_ID,
            }
            write_json(eval_dir / "run_summary.json", run_summary)
            write_json(eval_dir / "fods_comparison.json", fods_comparison)

            # human confirmation sheet (top 10 per query)
            hc_rows = []
            for qid in sorted(by_query):
                ranked_qs = [
                    d for d in all_decisions if d["query_id"] == qid and d["status"] == "ok"
                ]
                ranked_qs.sort(key=lambda d: (-(d["expected_relevance"] or 0), d["paper_key"]))
                for d in ranked_qs[:10]:
                    hc_rows.append(
                        {
                            "query_id": qid,
                            "paper_key": d["paper_key"],
                            "title": d["title"],
                            "year": d["year"],
                            "mammoth_rank": d.get("rank"),
                            "expected_relevance": d["expected_relevance"],
                            "p_relevant_or_highly": d["p_relevant_or_highly"],
                            "human_verdict": "pending",
                            "human_notes": "",
                            "confirmed_rank": "",
                        }
                    )
            # add unassessable/failed separately
            for qid in sorted(by_query):
                for d in all_decisions:
                    if d["query_id"] == qid and d["status"] in ("unassessable", "failed"):
                        hc_rows.append(
                            {
                                "query_id": qid,
                                "paper_key": d["paper_key"],
                                "title": d["title"],
                                "year": d["year"],
                                "mammoth_rank": "",
                                "expected_relevance": d["expected_relevance"],
                                "p_relevant_or_highly": d["p_relevant_or_highly"],
                                "human_verdict": "pending",
                                "human_notes": "",
                                "confirmed_rank": "",
                            }
                        )
            hc_fields = [
                "query_id",
                "paper_key",
                "title",
                "year",
                "mammoth_rank",
                "expected_relevance",
                "p_relevant_or_highly",
                "human_verdict",
                "human_notes",
                "confirmed_rank",
            ]
            write_csv(eval_dir / "human_confirmation.csv", hc_rows, hc_fields)

            print(f"Evaluation complete: {eval_dir}")
            n = len(all_decisions)
            f = run_summary["failed"]
            u = run_summary["unassessable"]
            print(f"Candidates: {n}, failed: {f}, unassessable: {u}")

    asyncio.run(run())
    return 0


def _decision_to_dict(cd) -> dict:
    return {
        "query_id": cd.query_id,
        "candidate_id": cd.candidate_id,
        "paper_key": cd.paper_key,
        "paper_id": cd.paper_id if hasattr(cd, "paper_id") else "",
        "title": cd.title,
        "year": cd.year,
        "doi": cd.doi if hasattr(cd, "doi") else "",
        "abstract_completeness": None,
        "status": cd.status,
        "assessability": cd.assessability,
        "assessability_probabilities": cd.assessability_probabilities,
        "assessability_confidence": cd.assessability_confidence,
        "relevance_score_raw": cd.relevance_score_raw,
        "relevance_probabilities": cd.relevance_probabilities,
        "relevance_confidence": cd.relevance_confidence,
        "relevance_legend": cd.relevance_legend,
        "expected_relevance": cd.expected_relevance,
        "p_relevant_or_highly": cd.p_relevant_or_highly,
        "error": cd.error,
        "request_id": cd.request_id,
        "batch_id": cd.batch_id,
        "latency_ms": cd.latency_ms,
        "input_tokens": cd.input_tokens,
        "cost": cd.cost,
        "raw_response": cd.raw_response,
    }


# patch CandidateDecision to carry extra fields


def _decision_row(cd, qid, group):
    return {
        "query_id": qid,
        "paper_key": cd.paper_key,
        "status": group,
        "expected_relevance": cd.expected_relevance,
    }


def cmd_status(args: argparse.Namespace) -> int:
    base = Path(args.output_dir)
    if not base.exists():
        print("no evaluations yet")
        return 0
    dirs = sorted(base.iterdir(), reverse=True)
    for d in dirs[:3]:
        prog = d / "progress.jsonl"
        n = 0
        if prog.exists():
            n = sum(1 for _ in prog.open(encoding="utf-8"))
        total = 450
        print(f"{d.name}: progress={n}/{total}")
        # show last line summary if exists
        if prog.exists() and n > 0:
            last = prog.read_text(encoding="utf-8").strip().splitlines()[-1]
            try:
                obj = json.loads(last)
                q = obj.get("query_id")
                pk = obj.get("paper_key")
                st = obj.get("status")
                er = obj.get("expected_relevance")
                print(f"  last: {q} {pk} status={st} exp_rel={er}")
            except Exception:
                pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="mammoth_evaluator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pref = sub.add_parser("preflight")
    p_pref.set_defaults(func=cmd_preflight)
    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--input", required=True)
    p_eval.add_argument("--output-dir", default="data/fods/evaluations/mammoth1")
    p_eval.add_argument("--eval-id", default=None)
    p_eval.add_argument("--model", default="baseten/mammoth-1")
    p_eval.set_defaults(func=cmd_evaluate)

    p_status = sub.add_parser("status")
    p_status.add_argument("--output-dir", default="data/fods/evaluations/mammoth1")
    p_status.set_defaults(func=cmd_status)
    args = parser.parse_args()
    # inject model into module global (already fixed)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
