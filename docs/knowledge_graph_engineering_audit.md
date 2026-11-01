# Knowledge Graph Engineering Audit

Audit date: 2026-10-31. Repository: `D:\Research_AI_Agent-fods`, branch
`codex/phase2-1-verification`. This was a read-only engineering audit; no graph
implementation, source enrichment, context snapshot, or published graph was
changed during the audit. Existing unrelated worktree changes remain present.

## A. Executive assessment

The graph is correctly optional in the architecture and provides deterministic
local indexing, persisted snapshots, indexed bounded queries, and useful
provenance fields. It is suitable for continued internal experimentation and
offline evaluation. It is **not ready for conversational graph integration**
yet: evidence validation is not enforced as a corpus eligibility gate, the
paper-level audit manifest currently overstates what it classifies, concurrent
updates can lose one writer's changes, and the prior test run did not complete
the P4 or full suite. The graph can be queried by a future synthesis layer, but
no such layer or answer-level evidence policy has been integrated.

## B. Architecture findings

- `fods.knowledge_graph` is imported inside explicit graph CLI handlers in
  `fods.cli`; `fods.runtime` has no graph import/call. Planning, retrieval,
  enrichment, and brief output therefore have no synchronous graph dependency.
- FODS owns context and enrichment artifacts; the graph is a derived JSON
  snapshot under `data/fods/knowledge_graph/<topic-key>/graph.json`.
- `graph build`, `graph update`, `graph stats`, and `graph query` are separate
  commands. Query reads the snapshot and its precomputed indexes. Querying does
  not rebuild or run full snapshot validation.
- Update clones the full snapshot through JSON, rebuilds all indexes, validates
  every node and edge, and rewrites the entire JSON file. Only paper extraction
  contributions are selectively reconstructed. This is incremental in semantic
  work, but not in total I/O or snapshot-processing cost.
- `os.replace` gives atomic visibility for one writer. There is no lock or
  compare-and-swap around read/modify/publish, so simultaneous writers can each
  publish valid snapshots and the later one can discard the earlier update.

## C. Data model findings

Current node types: `PAPER`, `CONCEPT`, `METHOD`, `FINDING`, `LIMITATION`, and
`EVIDENCE_SPAN`. Current edges: `HAS_CONCEPT`, `USES_METHOD`,
`REPORTS_FINDING`, `STATES_LIMITATION`, `HAS_SOURCE_EVIDENCE`, and `CITES`.
Entity IDs derive from node type and normalized value; evidence IDs derive from
paper, category, item position, segment IDs, and reconstructed excerpt. Edge
IDs derive from endpoints, edge type, and owning paper. Repeated construction
from the same data is deterministic. Distinct concepts are merged only after
conservative normalization (Unicode NFKC, case, whitespace, selected
typographic punctuation).

Edges point from a paper to its extracted entity; evidence edges point from
entity to evidence span; citation edges point from citing paper to cited paper.
Citation edges are restricted to IDs already represented in the indexed
context. Relationship records contain `trust` and `paper_id`, but there is no
explicit schema-version migration mechanism beyond refusing unsupported schema
versions. Orphan entity cleanup is based on edge reachability. Exact duplicate
edge writes collapse by deterministic ID.

## D. Provenance findings

An evidence span stores its paper ID, paper content hash, category, segment IDs,
and reconstructed excerpt. Its evidence edge is owned by that paper and marked
`STRUCTURAL`. Query results can return that span. The manifest stores a
fingerprint of the complete enrichment and references for each paper, but the
fingerprint is not copied onto evidence nodes or edges, and the selected source
artifact path/key is not recorded. Thus provenance can be traced to the paper
and indexed values, but not unambiguously to one immutable enrichment artifact
when multiple artifacts contain the same valid paper/hash pair.

`_valid_evidence` rejects missing/unknown segment IDs or a mismatched supplied
excerpt by returning `None`. `_index_paper` still creates the paper-to-entity
edge when this happens; it simply omits the evidence node/edge. The resulting
graph fact is structurally attributable to a paper's enrichment, but is not
evidence-backed. This is a material semantic limitation for a conversational
answer system. The graph makes no support/contradiction/agreement edges, which
is correct: shared concepts and methods do not establish agreement or equal
performance.

## E. Corpus integrity

The selected context contains 45 unique paper IDs. Independent scanning of
topic-matching immutable enrichment artifacts found 32 papers with a matching
paper hash and 13 with no topic-matching enrichment record. No context ID
duplicates, hash mismatches, or additional matching records were observed in
that scan. The built snapshot contains 32 paper nodes, consistent with this
input selection.

The file `.pytest-tmp/graph-eligibility-45.json` is not a fully authoritative
eligibility manifest: `load_inputs` drops nonmatching enrichments before
`eligibility_manifest` receives them, so “missing enrichment” conflates truly
missing enrichment with a record whose hash does not match. The independent
artifact scan found no mismatches for these 45 records, but the classifier
itself cannot make that distinction generally. `eligibility_manifest` validates
the Pydantic shape only; it does not validate each evidence segment reference
or excerpt. Therefore its zero-invalid count is not evidence that all evidence
is valid.

Observed exhaustive counts for this context: 32 matching enrichment records,
13 no matching topic artifact, 0 duplicate context IDs, 0 mismatching records
observed, 0 matching records rejected by the current Pydantic schema. Evidence
reference validity was not independently aggregated across all 32 records by
the eligibility audit, so that category remains unmeasured rather than zero.

## F. Incremental update findings

The update fingerprint hashes the complete selected enrichment plus sorted
paper references. It detects enrichment/reference changes; stable paper IDs
anchor replacement. A changed paper's owned edges and evidence are removed,
then recreated. Shared canonical entity nodes remain while any edge references
them, and orphan entities are pruned. Explicit deletion is required when a
previously indexed paper disappears from inputs. New eligible targets trigger
rechecking old papers that cite those targets.

Snapshot validation checks endpoints, trust labels, evidence-to-paper links,
and index references. Publication writes and fsyncs a same-directory temporary
file before atomic replacement. This protects readers from partial JSON and
preserves the prior file if replacement fails. It does not serialize competing
writers, preserve last update under concurrency, or fsync the directory entry.
No persisted multi-process concurrency test was recorded.

Prior tests exercised production snapshot functions with temporary persisted
files and publication failure injection. They did not complete the requested
full persisted CLI scenario matrix (five-paper and changed-enrichment CLI
updates remain unverified). Do not interpret the in-memory benchmark cases as
persisted update timings.

## G. Performance and scalability findings

Two distinct initial-build runs were recorded:

| Run | Method | Time | Snapshot bytes | Peak traced memory |
|---|---|---:|---:|---:|
| `2026-10-31-local-inmemory-v1` | In-memory benchmark; JSON size measured with default spacing | 66.798 ms | 500,455 | 906,616 B |
| `2026-10-31-real-context-cli-build-v1` | Real context CLI build and atomic publication; compact JSON file | 86.857 ms | 480,167 | 910,448 B |

They differ in execution path and serialization mode; neither supersedes the
other. The 6.58 ms no-change and 6.014/8.714/5.931 ms update timings in the raw
benchmark JSON are in-memory update measurements, not persisted publication
measurements. A prior real no-change CLI update measured 5.192 ms update
processing plus 13.116 ms publication.

Complexity from code inspection: input artifact loading scans the enrichment
directory and parses topic artifacts; update fingerprinting scans all current
eligible records; snapshot clone, index rebuild, validation, serialization and
publication are O(V+E) each. Query direct lookup is indexed; traversal cost is
bounded by the configured limits and adjacency of visited nodes. Query index
memory is O(V+E), with each edge ID stored at both endpoints. No 100/500/1,000/
5,000-paper benchmark was performed, so large-collection latency and memory
remain unknown. The current 32-paper corpus does not validate large-scale
performance.

## H. Research pipeline isolation

Static inspection confirms `src/fods/runtime.py` does not import or call graph
build/update, and graph imports are local to CLI command bodies. There are no
graph tasks in the research plan and brief generation does not await graph
publication. This supports optionality at the code boundary. A regression test
using spies that fail if research planning, retrieval, enrichment, or brief
generation invokes graph operations was not present, so dynamic isolation is
not fully proven. An unavailable graph can block a graph query command, but
cannot block ordinary research execution.

## I. Query readiness

Supported: concept lookup to papers; method/finding/limitation lookup; paper
neighborhood; shared concepts for two paper IDs; incoming verified citation
lookup; bounded adjacency traversal; evidence spans reachable from concepts or
findings. Results include source paper IDs and evidence segment/excerpt fields.

Limitations: no natural-language query planning, no multi-filter query object,
no aggregation or cross-paper limitation summary, no explicit evidence-only
query mode, and no synthesis/answer verification layer. The query API returns a
subgraph, not a grounded answer. Conversational integration must enforce source
citation and claim qualification itself.

## J. Test coverage

- Knowledge graph + existing graph-store focused run: 28 passed (recorded in
  the preceding verification turn).
- Ruff: graph files and then `src/ tests/` passed with exit code 0 in the latest
  verification turn.
- `compileall src/fods`: completed successfully in the preceding verification.
- P4 graph-stage suite: not completed. Verbose execution passed 22 of 28 tests,
  then stalled at `test_the_stage_persists_both_files_and_reports`. A focused
  run with `faulthandler_timeout=10` showed the main thread blocked creating a
  Windows asyncio Proactor self-pipe in `socket.accept` during pytest-asyncio
  loop fixture setup. This points to a Windows event-loop/platform setup issue,
  not graph-stage application code; the test has not been proven passing.
- Full project suite: not completed; a run was observed at five dots and was not
  allowed to finish. No pass/fail/skip totals can be claimed.
- Persisted CLI incremental scenarios and automated research-path spies:
  incomplete.

## K. Prioritized issue register

### KG-01 — HIGH — Invalid evidence can still create extracted-entity edges

- **Location:** `src/fods/knowledge_graph.py`, `_valid_evidence`, `_index_paper`.
- **Evidence:** Invalid evidence returns `None`, but paper-to-entity edge is
  created before evidence validation.
- **Impact:** A conversational consumer may receive an extracted finding or
  concept without any validated source span.
- **Recommended correction:** Make evidence validity an explicit item status;
  either exclude evidence-required claims from answerable query results or
  clearly label them as ungrounded. Add corrupted/unknown segment tests.

### KG-02 — HIGH — Concurrent updates can lose writes

- **Location:** `src/fods/cli.py`, `graph_update_command`; `publish`.
- **Evidence:** Read/modify/publish has no per-topic lock or generation check.
- **Impact:** Two valid concurrent updates can overwrite one another.
- **Recommended correction:** Serialize per-topic update commands or add a
  manifest generation compare-and-swap before replacement.

### KG-03 — MEDIUM — Eligibility report filters before classifying

- **Location:** `src/fods/knowledge_graph.py`, `load_inputs` and
  `eligibility_manifest`.
- **Evidence:** Hash-mismatched artifacts are discarded by `load_inputs`; the
  classifier receives only selected matches and cannot distinguish mismatch
  from absence. Evidence references are not validated by Pydantic schema.
- **Impact:** Future exclusion reports can misstate missing versus stale data.
- **Recommended correction:** Audit raw artifact records first, then select
  only valid matches for graph construction; classify evidence references.

### KG-04 — MEDIUM — Incremental updates retain full-snapshot work

- **Location:** `src/fods/knowledge_graph.py`, `update_snapshot` and `publish`.
- **Evidence:** Full JSON clone, index reconstruction, validation, serialization,
  and publication occur even when no papers change.
- **Impact:** Cost grows with the entire graph despite low changed-paper count.
- **Recommended correction:** Measure at larger corpus sizes first; if confirmed
  material, store per-paper contribution deltas or use an indexed local store.

### KG-05 — MEDIUM — Integration isolation lacks dynamic regression tests

- **Location:** graph tests / FODS runtime tests.
- **Evidence:** Isolation is supported by static dependency inspection, but no
  fail-on-call spy tests cover the runtime stages.
- **Impact:** Future changes could introduce graph work into the synchronous
  research path unnoticed.
- **Recommended correction:** Add targeted runtime spies before conversational
  integration.

### KG-06 — MEDIUM — P4 and full test suites remain unverified

- **Location:** Windows test environment / pytest-asyncio Proactor setup.
- **Evidence:** P4 stalls at loop setup; full suite did not finish.
- **Impact:** Existing integration gates are not demonstrated green.
- **Recommended correction:** Resolve or explicitly configure the test event-loop
  policy in a scoped test environment and rerun both suites before integration.

## L. Integration decision

**Ready with specific blocking fixes.** The optional indexing and query boundary
is sound enough to retain, but conversational integration should wait for
KG-01, KG-02, KG-03 and the P4/full-suite gates. The next milestone should add
strict evidence eligibility, per-topic update serialization, exhaustive corpus
classification, and runtime isolation spies, then complete persisted CLI and
test-suite verification. Do not add answer synthesis or frontend integration
until those gates pass.
