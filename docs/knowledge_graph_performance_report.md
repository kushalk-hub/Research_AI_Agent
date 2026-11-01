# FODS knowledge graph performance report

Measured 2026-10-31 against the saved **Graph attention networks** context
(`6027ff84b166b45f6ac9955ba3f58b83`). The benchmark uses local artifacts only;
it does not call a model provider or fetch records. Raw measurements are in
[`knowledge_graph_performance_report.json`](knowledge_graph_performance_report.json).

The initial performance run’s eligibility summary (32 indexed / 13 missing) was produced by the earlier filtered loader and is preserved here as historical, non-exhaustive data. The later shared raw classifier is authoritative for eligibility: 45 context records, 15 topic-relevant artifact files, 29 eligible, 13 missing, and 3 ambiguous/conflicting; the detailed latest report is `.pytest-tmp/graph-eligibility-45-stabilization.json`.
The previous 66.798 ms / 500,455-byte / 906,616-byte figures are the in-memory
benchmark run; 86.857 ms / 480,167-byte / 910,448-byte figures are the real CLI
build and compact published snapshot. They are distinct measurements and JSON
serialization modes.

The persisted CLI matrix was completed on 2026-10-31 with an isolated,
persisted synthetic context through the production Typer CLI. Initial build:
1.187 ms index/update + 3.326 ms publish = 4.513 ms. Update totals were 3.520
ms (no change), 3.814 ms (one new), 5.154 ms (five new), 4.296 ms (one changed
enrichment), 4.625 ms (repeat, no changes), and 4.372 ms (one invalid evidence
item rejected while valid items remain). Stale-hash rejection and simulated
publication failure both preserved the prior snapshot. These measurements are
from a seven-paper isolated fixture, not the real 45-paper corpus; they are
distinct from the in-memory benchmark and real-context build measurements
below. The test artifact is under `.pytest-tmp/cli-persisted-final/`.

## Architecture

The graph is an optional JSON snapshot under
`data/fods/knowledge_graph/<topic-key>/graph.json`. The indexer reads immutable
FODS context snapshots and hash-matched `paper_enrichments` records. It does
not alter enrichment artifacts. IDs derive from node type, conservative
Unicode/case/whitespace normalization, and normalized term. Original term
spellings remain on nodes. Exact normalized terms share a node; semantic
similarity is not used.

Nodes are `PAPER`, `CONCEPT`, `METHOD`, `FINDING`, `LIMITATION`, and
`EVIDENCE_SPAN`. Structural paper-to-entity and entity-to-evidence edges are
marked `STRUCTURAL`. Exact citation IDs are linked only when both source and
target are indexed, and those edges are marked `BIBLIOGRAPHIC`. Unresolved
references remain absent. Evidence spans are linked only if their segment IDs
exist in the source abstract and any supplied excerpt matches the reconstructed
text. Segment IDs are paper-local, so this verifies evidence against the
application-owned parent paper ID/hash and abstract but cannot distinguish a
copied segment when two papers share the same local ID and excerpt. The evidence
ownership limit and schema requirements are detailed in the stabilization
report.

Updates compare a stable paper ID and a SHA-256 fingerprint of the complete
enrichment record. They skip unchanged records, remove and replace one paper's
contributions when its enrichment changes, and require an explicit
`--delete-paper` for removals. The candidate snapshot is validated, written to
a temporary file, flushed, and atomically renamed into place. A rejected update
leaves the previous snapshot untouched.

Queries read the published snapshot only. Adjacency traversal is bounded by
depth, returned nodes, edges, and evidence spans. Query results include paper
IDs, evidence IDs, segment IDs, and excerpt text; a shared concept or extracted
finding is not presented as proof of agreement or a universal claim.

## Measured performance

| Operation | Result |
|---|---:|
| Context records inspected | 45 |
| Eligible enriched papers | 32 |
| Initial graph | 669 nodes, 674 edges, including 12 resolved citation edges |
| Nodes by type | PAPER 32; CONCEPT 195; METHOD 55; FINDING 51; LIMITATION 5; EVIDENCE_SPAN 331 |
| Edges by type | HAS_CONCEPT 212; USES_METHOD 58; REPORTS_FINDING 56; STATES_LIMITATION 5; HAS_SOURCE_EVIDENCE 331; CITES 12 |
| Initial graph JSON size | 480,167 bytes (published snapshot) |
| CLI initial graph-indexing time | 73.903 ms (allocation tracing enabled) |
| Initial atomic publication time | 12.954 ms |
| Initial total graph build and publication | 86.857 ms |
| Peak traced memory | 910,448 bytes |
| Initial indexing in benchmark run | 60.258 ms; normalization 2.702 ms; validation 2.725 ms |
| No-change update | 6.580 ms indexing/validation; 0 papers reprocessed |
| One new paper (in-memory canary) | 6.014 ms; 1 paper reprocessed |
| Five new papers (in-memory canaries) | 8.714 ms; 5 papers reprocessed |
| One changed enrichment (in-memory canary) | 5.931 ms; 1 paper reprocessed |
| Direct concept lookup, 100 repetitions | p50 0.008 ms; p95 0.009 ms |
| Shared concepts for two papers, 100 repetitions | p50 0.089 ms; p95 0.093 ms |
| Methods used by a paper, 100 repetitions | p50 0.017 ms; p95 0.018 ms |
| Bounded depth-three traversal, 100 repetitions | p50 0.017 ms; p95 0.018 ms |
| Evidence lookup for a finding, 100 repetitions | p50 0.008 ms; p95 0.008 ms |

The one/five-paper and changed-enrichment cases use copies of real local records
with isolated in-memory IDs/changes. They are timing fixtures, not persisted
corpus changes. Both build measurements use allocation tracing; their small
spread reflects local run variation. Times are local Windows measurements for
this corpus, not universal targets. Incremental updates still
inspect current record IDs and validate the final snapshot, while only changed
paper representations are reconstructed.

The CLI's persisted `performance.json` also records publication time and the
last update (the latest no-change update took 5.192 ms to index/validate plus
13.116 ms to publish). Query indexes are stored in the snapshot, so lookups do
not scan all edges or run graph-wide validation. Benchmark procedure:

```powershell
.\.venv\Scripts\python.exe tools/benchmark_knowledge_graph.py --topic "Graph attention networks"
.\.venv\Scripts\python.exe -m fods.cli graph update --topic "Graph attention networks"
```

## Isolation from normal research

`fods.knowledge_graph` is imported inside graph CLI handlers only.
`src/fods/runtime.py` has no graph build/update import or call. The graph is not
scheduled by the research plan, no graph operation is a dependency of brief
generation, and graph query performs no writes. A missing, stale, or failed
graph therefore cannot block delivery of a research brief. No live research
run was needed for this check.

## Limitations

- The first milestone indexes only enrichment categories currently present in
  FODS artifacts and citation IDs that already resolve to papers in the graph.
- It does not create `AUTHOR` or `VENUE` nodes, infer semantic relations, merge
  similar terms, or call an LLM.
- The snapshot is a local JSON file. A process crash before atomic replacement
  keeps the prior snapshot; an OS or storage failure can still prevent a new
  publication, which is reported to the invoking command.
- Normalization/indexing time includes Python object and edge assembly; the
  report separately times normalization and validation but does not claim that
  every sub-operation has an independent profiler trace.
