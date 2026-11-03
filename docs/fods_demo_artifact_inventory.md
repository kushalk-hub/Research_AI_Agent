# FODS Demonstration Artifact Inventory

These artifacts represent separate demonstration runs and datasets. Do not present them as one continuous run.

| Artifact | What it demonstrates | Origin and provenance | Reproducible? | Faculty use |
|---|---|---|---|---|
| CI brief: `data/fods/briefs/mvp-final-demo.md` | Answer to “How did graph attention use local neighborhoods?” with source list. | CI run `a358ed9efa63`, fixture simulation, fixture planner; workflow `41296050154`, commit `f533ae1`. CI validator checked requested question, topic, source heading, citation-to-paper mapping, selected titles, and saved/validated output. File is in remote Actions artifact `fods-mvp-acceptance`; absent from this local checkout because `data/fods/` is ignored. | Yes: rerun the accepted deterministic command in CI or a working local environment. | Yes, when obtained from the named workflow artifact; label as fixture-based. |
| CI trace: `data/fods/runs/a358ed9efa63.jsonl` | Ordered runtime events for 8 completed tasks, task dependencies, evidence selection, citation check and output write. | Same CI fixture run; 4 context papers, 4 selected evidence cards, validated citation IDs P1/P2/P3, zero failed task attempts. Remote artifact only; content not in this checkout. | Yes, with the same fixture command (run ID can differ). | Yes, as event provenance; it does not demonstrate live retrieval. |
| CI HTML: `data/fods/runs/a358ed9efa63.html` | Browser-readable visualization of the CI event trace. | Same CI fixture run and validator. Remote artifact only. | Yes, generated from a persisted run trace. | Yes, if downloaded from the Actions bundle. |
| Local brief: `data/fods/briefs/5f0bf2d0b68d.md` | Fixture answer and source list for “What evidence is available for graph attention networks?” | Run `5f0bf2d0b68d`; trace records `mode=simulate`, `planner=fixture`, topic `FODS ready-queue comparison`, and priority schedule. It is a different historical fixture run than the CI acceptance run. | Yes, by rerunning the corresponding fixture scenario; resulting run ID may differ. | Yes, with the fixture provenance stated. Contains example.org fixture URLs. |
| Local trace: `data/fods/runs/5f0bf2d0b68d.jsonl` | 113 sequenced runtime events: plan, readiness, queue, task/stack transitions, evidence and output. | Same local historical fixture run. No `model*` events were present when the trace was inspected. | Yes, by rerunning the fixture scenario. | Yes, useful for explaining runtime structures; not live concurrency evidence. |
| Local HTML: `data/fods/runs/5f0bf2d0b68d.html` | Rendered view of the historical local event log. | Same local historical fixture run. | Yes: `python -m fods.cli replay <trace.jsonl>` renders adjacent HTML. A copy was replayed successfully under `.pytest-tmp/docs-demo-replay/`. | Yes; say “replay,” not live execution. |
| Replay verification copy: `.pytest-tmp/docs-demo-replay/5f0bf2d0b68d.html` and `replay-output.txt` | Confirms current CLI replay generates HTML and prints `REPLAY ONLY`. | Produced by replaying a copy of the historical trace; original artifact untouched. Temporary verification artifact. | Yes. | Not ideal as the main display; use the matching original brief/trace/HTML. |
| Isolated graph snapshot: `.pytest-tmp/mvp-existing-context-demo-99861ac9/data/fods/knowledge_graph/887437c0b2403e8b/graph.json` | Current schema-v2 graph and supported deterministic follow-ups. | Built by production graph CLI from a copied saved Graph Attention Networks context (`6027ff84b166b45f6ac9955ba3f58b83`) and matching enrichment artifacts. 45 records inspected; 29 eligible papers; 605 nodes, 607 edges, 298 evidence spans, 11 bibliographic `CITES` edges; recorded build time 77.2 ms. Separate from both brief fixture runs. | Yes, from the same saved source artifacts using the documented graph build command in the isolated root. | Yes, if clearly described as a separate graph index built from saved enrichment. |
| Isolated graph report: `.pytest-tmp/mvp-existing-context-demo-99861ac9/data/fods/knowledge_graph/887437c0b2403e8b/performance.json` | Graph eligibility and build measurements for the isolated snapshot. | Same graph build as above. | Yes, when rebuilt against the same copied inputs; timing is machine/run-specific. | Supporting evidence, not a research answer. |
| Paired review pack: `benchmarks/paired_review_20261031.csv` | Candidate/review rows for the Quick/Deep retrieval comparison. | 650 rows; zero non-empty reviewer labels at inspection. | Review completion requires human work. | Do not present as a completed quality benchmark. |
| Pooled review pack: `benchmarks/pooled_review_20261031.csv` | Pooled unique paper candidates across benchmark queries. | 450 rows; zero non-empty reviewer labels at inspection. | Review completion requires human work. | Do not claim precision/recall or human relevance quality from it. |

## Accepted CI run reference

- Branch: `codex/fods-mvp-acceptance`
- Commit: `f533ae1`
- Workflow run: [41296050154](https://github.com/kushalk-hub/Research_AI_Agent/actions/runs/41296050154)
- Acceptance: 797 full-suite tests passed; 28 P4 tests passed; Ruff and compileall passed; deterministic fixture run and artifact validator succeeded.
- Run: `a358ed9efa63`, 8/8 tasks, 4 papers, 4 selected evidence cards, citation IDs P1/P2/P3.
- Artifact bundle: `fods-mvp-acceptance` in the workflow run. The individual CI artifact bytes were not present in the local checkout when this inventory was written; download them from GitHub Actions before relying on local copies.

## Verified isolated graph follow-ups

All commands ran against the isolated data root, not the original graph:

| Question | Result |
|---|---|
| `Which papers use GAT?` | 2 method records: `W3171970564` (segment `S001`) and `doi:10.3390/electronics13214208` (segment `S004`). |
| `What findings are reported for graph attention networks?` | 5 evidence-backed records, including `W3146788459` reporting 47% relative improvement and `W3171970564` reporting GATv2 outperforms GAT across 11 benchmarks. |
| `What limitations are mentioned for graph attention networks?` | 1 record: `W3171970564`, static attention limitation, segment `S005`. |
| `Which papers cite W2766453196?` | 7 bibliographic citation records, including `W2906413107`, `W2911286998`, `W3035529900`, `W3146788459`, `W3153880451`, `W3163629447`, and `W3171970564`. |

These are graph-supported retrievals over saved records, not model-generated semantic conclusions. Shared concept labels mean vocabulary overlap. The current browser workbench does not expose graph follow-up; it is a CLI capability. The original checkout graph is schema v1 and was not overwritten.
