# Knowledge Graph Stabilization Report

Status: **PARTIALLY COMPLETE** (2026-10-31). This work modifies the existing
FODS graph implementation only. No conversational synthesis or frontend work
was added.

## Changes made

- `src/fods/knowledge_graph.py`: schema version advanced from 1 to 2. Indexing
  now validates each item's segment ID list, same-paper segment ownership via
  the paper's abstract segment map, and reconstructed excerpt before creating
  any extracted entity edge. Invalid items are individually rejected and
  returned in update diagnostics; valid items from the same paper remain.
  Evidence nodes and structural evidence edges carry the enrichment
  fingerprint from the graph manifest. Pydantic validation alone is not treated
  as evidence validation.
- `src/fods/cli.py`: graph build and update entry points now hold a
  cross-process, per-topic file lock across their full read/modify/publish
  operation. Windows uses `msvcrt.locking`; POSIX uses `flock`. Different topic
  keys use different lock files. Existing schema-v1 snapshots are rejected by
  the v2 schema check; no existing snapshot was rewritten automatically.
- `tests/test_fods_knowledge_graph.py`: existing production-function and
  persisted-snapshot coverage now includes evidence rejection and item-level
  eligibility behavior. Nine tests pass.

## Blocker status

### Evidence validity — implementation complete, coverage partial

Entity edges are now emitted only after valid evidence. Rejection reasons
include missing/malformed/duplicate IDs, unknown/foreign IDs, missing excerpts,
and excerpt mismatch. The update reports rejected item details. Query results
therefore cannot traverse to an extracted entity from a rejected item. The
schema bump prevents old snapshots from being silently read as evidence-v2.
Regression tests passed for valid evidence, unknown IDs, and persisted
publication failure. Dedicated tests for every rejection reason and mixed
valid/invalid facts still need expansion.

### Concurrent update protection — code implemented, multiprocessing test pending

Build and update acquire the same topic-specific OS lock before reading inputs
or snapshots and retain it through report/publish completion. This serializes
cross-process writers on supported Windows and POSIX platforms. No process-level
race test was completed in this run; lock behavior under abrupt process death
and unrelated topics remains to be demonstrated by tests.

### Raw eligibility classification — incomplete

The existing `load_inputs` still filters hash-mismatched and schema-invalid
records before the eligibility report sees them. The previous independent scan
found 32 matching artifacts and 13 missing for the Graph attention networks
context, but does not establish the new exhaustive outcomes required by the
stabilization task. This blocker remains open; do not treat the prior 0-invalid
counts as validated evidence status.

## Verification

- `.venv\Scripts\python.exe -m pytest tests/test_fods_knowledge_graph.py -q --basetemp=.pytest-tmp/stab-pass` — **9 passed**.
- `.venv\Scripts\ruff.exe check src/ tests/` — **All checks passed**, exit code 0.
- `.venv\Scripts\python.exe -m compileall src/fods` — completed, exit code 0.
- No full suite, P4 suite, or multiprocess concurrency test was completed in this stabilization pass. Earlier P4 run stalled in Windows asyncio Proactor loop setup; see `docs/knowledge_graph_engineering_audit.md`.
- No existing enrichment artifacts, saved research contexts, or published graph snapshots were changed. No commits were created.

## Remaining risks and gates

Before conversational integration, implement raw artifact audit/selection as a
single source of truth, add targeted malformed/foreign/mixed evidence tests,
add a multi-process writer test (including independent topics), and rerun the
P4 and full project test suites. Schema-v1 snapshots require an explicit
rebuild command; they are not auto-migrated.


## Completion pass — 2026-10-31

Status: **PARTIALLY COMPLETE**. This dated continuation preserves the earlier findings above.

### Raw eligibility recheck

The production `classify_inputs` scan examined 45 context records and 15 topic-relevant artifact files. It selected 29 papers. The paper-level machine-readable report is [`.pytest-tmp/graph-eligibility-45-stabilization.json`](.pytest-tmp/graph-eligibility-45-stabilization.json); it contains per-paper reasons and artifact fingerprints without excerpt text.

| Outcome | Papers |
|---|---:|
| `ELIGIBLE` | 29 |
| `PARTIALLY_ELIGIBLE` | 0 |
| `MISSING_ENRICHMENT` | 13 |
| `HASH_MISMATCH` | 0 |
| `INVALID_SCHEMA` | 0 |
| `INVALID_EVIDENCE` | 0 |
| `DUPLICATE_OR_AMBIGUOUS` | 3 |
| **Total** | **45** |

For this corpus: **29 eligible**, **0 partially eligible**, **13 missing**, **0 hash mismatch**, **0 invalid schema**, **0 invalid evidence**, and **3 ambiguous/duplicate**. Valid/invalid extracted items: 298/0. Conflicting same-paper enrichment artifacts are reported as ambiguous and excluded from indexing; missing papers are not fabricated as empty enrichments.

### Evidence and locking regression results

Evidence rejection now has focused production-function cases for missing/malformed/empty IDs, duplicate IDs, unknown IDs, missing excerpts, and excerpt mismatch. Mixed-validity input preserves supported graph edges and excludes the invalid item; reopened snapshots retain evidence fingerprint provenance. The source contract has application-owned `PaperEnrichment.paper_id` and `paper_hash`, but nested evidence facts contain only paper-local `S###` IDs and excerpts; segment records contain ID, character offsets, and text, with no independent paper identity. The graph verifies the parent paper/hash and reconstructs the excerpt from that paper's abstract. It rejects unknown local IDs and excerpt mismatches, but cannot detect a cross-paper reference when the other paper has the same local ID and matching text. A future schema would need paper-bound segment IDs or nested paper/hash provenance to prove ownership independently; no migration was made in this verification pass.

A real Windows `spawn` process test initially found that reading the byte-range-locked file could raise `PermissionError`. Lock initialization now appends a sentinel without reading, locks byte zero, and only unlocks after successful acquisition. The process test verifies same-file contention, independent topic locks, release after exceptions, and release after process termination. A two-process persisted-snapshot test runs the production `update_snapshot`, publication, and topic lock paths; both additions survive and the reopened graph validates. The competing processes use the same complete context snapshot, matching the CLI update model. This test calls the production update/publish functions inside the production lock, while the CLI mutation decorator itself is separately exercised by the persisted CLI test below.

### Persisted production CLI update measurements

An isolated pytest fixture invoked the real Typer `graph build` and `graph update` commands against persisted context and enrichment JSON inside `.pytest-tmp/cli-persisted-final/`; no original context, enrichment, or graph was touched. Timings are milliseconds from that single synthetic fixture run, with update elapsed time shown separately from atomic publish time.

| Scenario | Update/indexing elapsed | Publish | Total | Outcome |
|---|---:|---:|---:|---|
| Initial build | 1.187 | 3.326 | 4.513 | 1 paper; 4,901-byte snapshot |
| No-change update | 0.124 | 3.396 | 3.520 | 0 reprocessed |
| Add one paper | 0.281 | 3.533 | 3.814 | 1 new |
| Add five papers | 0.595 | 4.559 | 5.154 | 5 new |
| Change one enrichment | 0.591 | 3.705 | 4.296 | 1 changed |
| Repeat unchanged update | 0.430 | 4.195 | 4.625 | 0 reprocessed |
| Reject one invalid evidence item | 0.485 | 3.887 | 4.372 | 1 changed; 1 item rejected, other valid items retained |

The stale context-hash case was rejected before publication and left the prior bytes unchanged. A simulated publish failure also left the last-known-good snapshot queryable and valid. The command test verifies all values are captured from the persisted CLI performance report. These are synthetic-fixture timings, not timings on the Graph attention networks corpus. The older in-memory and actual-corpus initial-build measurements above remain separate historical runs.

### Test verification and remaining gates

- `.venv\Scripts\python.exe -m pytest tests/test_fods_knowledge_graph.py tests/test_fods_graph_cli.py tests/test_p0_graph.py -q --basetemp=.pytest-tmp/final-proof` — **44 passed in 4.99 s**.
- `.venv\Scripts\python.exe -m pytest tests/test_p4_graph_build.py -q -k "not persists_both_files_and_reports and not refuses_to_build_without_resolved_concepts and not surviving_temporal_violation_is_reported_as_an_error and not graph_runs_after_resolve_and_lands_in_the_result and not graph_stage_refuses_to_write_from_a_store_of_another_corpus and not graph_stage_still_writes_when_only_coverage_is_incomplete" --basetemp=.pytest-tmp/p4-sync-only` — **22 passed, 6 async tests deselected**.
- Full P4 attempt: `.venv\Scripts\python.exe -m pytest tests/test_p4_graph_build.py -q -o faulthandler_timeout=20 --basetemp=.pytest-tmp/p4-close-gates`; it stalled after 22 tests. The synchronous subset command above gives 22 passed and 6 deselected. Latest full project collection: **768 tests**. Full execution command: `.venv\Scripts\python.exe -m pytest tests/ -q -o faulthandler_timeout=12 --basetemp=.pytest-tmp/full-final-current`; it printed 5 passes, then stalled during asyncio runner setup and was interrupted after about 23 seconds. No test failure was reported before the stall. The faulthandler stack ends at Python 3.12 Windows `socket.accept` in `_fallback_socketpair` called by `asyncio` loop `_make_self_pipe`, before test code. Forcing `WindowsSelectorEventLoopPolicy` reproduces the same socketpair stall. This is environment/test-runner setup evidence, not a graph-stage failure; P4 async and full suite remain unverified.
- Ruff changed-file and full `src/ tests/` checks — **exit 0**. `compileall src/fods` — **exit 0**.

The isolated persisted CLI scenario matrix is complete for build, update, evidence/hash rejection, idempotency, and publication rollback. A runtime fail-on-call spy regression was added, but its individual execution stalls while `asyncio.run` creates a Windows loop at the same socketpair setup point; runtime isolation therefore remains unverified by that spy in this environment. Remaining gates are an actual simultaneous CLI subprocess merge test, an uninterrupted P4 async run, and the full suite. This milestone is not marked complete. Schema-v1 published graphs still require an explicit rebuild to adopt schema v2. No existing enrichment artifacts, saved research contexts, or published graph snapshots were rewritten in this pass. No commit was created.


## Final verification — 2026-11-01

Status: **PARTIALLY COMPLETE**. The graph-specific implementation and new CLI concurrency gates pass. P4 async tests, the full suite, and the runtime isolation spy remain blocked by a reproduced Windows loopback socket restriction.

### Asyncio diagnosis

Fresh child-process probes identified the root cause outside pytest. Windows permits binding/listening on `127.0.0.1`, but rejects loopback `connect` with `PermissionError` / Winsock `WSAEACCES` / WinError 10013. `socket.socketpair()` on the available Windows runtimes uses loopback TCP and times out; asyncio loop setup then stalls in `_fallback_socketpair` while constructing its self-pipe. The same behavior occurs on Python 3.11.7, 3.12.8, and 3.13.7. Minimal async pytest cases fail with plugin autoload enabled and with pytest-asyncio loaded explicitly. A plain synchronous pytest test with plugin autoload disabled passes. The test session fixture does not create sockets. Proactor and Selector policies both stall.

This classifies the cause as an operating-system/socket-access restriction rather than a repository fixture, pytest configuration, or Python-version-specific defect. The exact policy or security product enforcing WinError 10013 is unknown. No firewall, antivirus, or system security settings were changed. Windows CIM inspection and WSL distro inspection returned Access Denied, so there was no alternate Linux environment to run the suite in. Detailed probes and traces are preserved under [asyncio-final-diagnostics](../.pytest-tmp/asyncio-final-diagnostics/), including `diagnostic-summary.md`, `diagnostic-summary.json`, `p4-pytest-trace.log`, and `full-pytest-trace.log`.

### P4 and full-suite outcomes

- P4 contains **28 tests**. `.venv\Scripts\python.exe -m pytest tests/test_p4_graph_build.py -q -o faulthandler_timeout=4 --basetemp=.pytest-tmp/p4-final-diagnostic` printed **22 passes**, then stalled before the first async test body. The diagnostic harness killed the pytest process after 10.015 seconds; pytest did not return an exit code. The synchronous-only run remains **22 passed, 6 deselected**, and is not represented as a complete P4 pass.
- Latest full collection: **770 tests** (`.venv\Scripts\python.exe -m pytest tests/ --collect-only -q --basetemp=.pytest-tmp/final-closure-count`). The full run printed **5 passes**, then stalled at the same loop-creation stack. The diagnostic harness killed it after 10.016 seconds; pytest did not return an exit code. No test failure was reported before either stall. The trace is in `.pytest-tmp/asyncio-final-diagnostics/full-pytest-trace.log`.
- Runtime isolation spy: `tests/test_fods_runtime.py::test_normal_research_runtime_never_calls_graph_mutations` was attempted with a faulthandler timeout and stalls in `asyncio.run` loop creation before the runtime body executes. Its behavioral result is **unverified**. Static inspection still shows `fods.runtime` does not import or invoke graph mutation code; that inspection is not counted as behavioral proof.

### Actual CLI subprocess concurrency

Added `tests/test_fods_graph_cli_concurrency.py`. It launches two independent `python -m fods.cli graph update` processes against one persisted graph and the same topic. Process A pauses immediately before atomic publication while holding the production topic lock; process B signals that it reached the same lock boundary. B cannot reach publication until A publishes. Their distinct persisted contexts update different existing papers; both commands exit 0, report one changed paper each, and the final reopened snapshot validates with both updated relationships.

The test also runs a deterministic no-lock control using the same fixture and publish gates. In that control, B publishes both changes first and A publishes its stale snapshot last; B's update is lost. This demonstrates that the fixture would detect the lost-update race if the lock were absent. The subprocess regression passed **1 test in 6.21 s**. Existing process tests also verify that independent topic locks do not block each other.

### Evidence ownership boundary

The source schema has application-owned `PaperEnrichment.paper_id` and `paper_hash`. A nested `EvidenceFact` contains only local segment IDs and an excerpt; `segment_text` returns segment ID, character offsets, and text, without an independent paper ID/hash. The CLI classifier verifies the parent record ID/hash against the context paper. The graph resolves each ID against that paper's abstract and checks the reconstructed excerpt. These checks establish that the evidence text exists in the context paper under its parent enrichment identity.

They cannot distinguish a segment copied from another paper when both papers use the same local ID (such as `S001`) and have the same excerpt text. A regression test demonstrates this representable boundary. The rejection reason was narrowed from `unknown_or_foreign_segment_id` to `unknown_segment_id` to avoid claiming detection the schema cannot provide. Independently provable segment ownership would require a future evidence-schema change (for example paper-bound segment IDs or nested paper/hash provenance); no migration was introduced here.

### Current eligibility and metrics

The authoritative raw result remains **45 context records**, **15 topic-relevant artifact files**, **29 eligible**, **13 missing**, **3 ambiguous/conflicting**, and **298 valid / 0 invalid extracted items among resolved candidates**. The earlier 32-paper counts are explicitly historical filtered-loader results in the performance report and JSON. Synthetic persisted CLI timings remain separated from the in-memory benchmark and the real-context initial-build measurement.

### Final commands

- `.venv\Scripts\python.exe -m pytest tests/test_fods_knowledge_graph.py tests/test_fods_graph_cli.py tests/test_fods_graph_cli_concurrency.py tests/test_p0_graph.py -q --basetemp=.pytest-tmp/final-closure-focused` — **46 passed in 11.18 s**.
- `.venv\Scripts\python.exe -m pytest tests/test_fods_graph_cli_concurrency.py -q --basetemp=.pytest-tmp/cli-process-proof-final` — **1 passed in 6.21 s**; both lock-enabled and deterministic no-lock control scenarios ran.
- `.venv\Scripts\python.exe -m pytest tests/test_fods_runtime.py::test_normal_research_runtime_never_calls_graph_mutations -q -o faulthandler_timeout=8 --basetemp=.pytest-tmp/runtime-diagnostic` — stalled before the test body at `asyncio.run` loop creation; no behavioral result.
- `.venv\Scripts\ruff.exe check src/fods/knowledge_graph.py src/fods/cli.py tests/test_fods_knowledge_graph.py tests/test_fods_graph_cli.py tests/test_fods_graph_cli_concurrency.py tests/test_fods_runtime.py` — **exit 0**.
- `.venv\Scripts\ruff.exe check src/ tests/` — **exit 0**.
- `.venv\Scripts\python.exe -m compileall src/fods` — **exit 0**.
- P4 and full-suite commands and outcomes are recorded above; neither completed.

The final status is **PARTIALLY COMPLETE**. Normal research remains graph-independent by architecture, but its behavioral spy could not execute here. No original context, enrichment artifact, or published graph snapshot was overwritten. All test fixtures, CLI snapshots, and diagnostics were kept inside `.pytest-tmp/`. Pre-existing working-tree changes were preserved. No commit or push was made.
