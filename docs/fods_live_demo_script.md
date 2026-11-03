# FODS Research Agent: 8–10 Minute Live Demo Script

## Recommended presentation setup

Use the deterministic fixture scenario in the five-tab browser workbench when the local browser server is reachable. For this Windows environment the server started on `127.0.0.1:18765`, but browser access failed with a loopback socket restriction. Do not change firewall or security settings. If that persists on assessment day, present the already-generated local HTML/JSONL/brief from run `5f0bf2d0b68d`, and use the CI-accepted artifact bundle for the exact Graph Attention Networks fixture run. The local fallback run has a different topic and is clearly identified in the artifact inventory.

Suggested timing: about 9 minutes. The script describes only current controls and records.

| Time | Presenter action | What appears on screen | What to explain | Expected result | FODS / technical concept |
|---|---|---|---|---|---|
| 0:00–0:45 | Introduce the problem and open the workbench or demo artifacts. | Overview tab, or brief and HTML visualization. | “Research agents can hide their task order and decisions. This project makes a bounded research workflow inspectable, so we can see where data structures control execution.” | Audience sees either the actual workbench or a labeled saved artifact. | Project purpose; provenance. |
| 0:45–1:30 | On Overview, enter topic `Graph Attention Networks` and a focused question. Choose Simulation and Fixture; keep a modest concurrency and select FIFO. | Form values, mode note, and configured-model status. | “This path is repeatable. The fixture planner and source records do not make fresh literature searches or call an LLM.” | Form is ready to submit; no claim of live retrieval. | Deterministic simulation vs live execution. |
| 1:30–2:15 | Start the run (or show the accepted CI run summary if browser access is unavailable). | Run status and first plan events; for CI: run `a358ed9efa63`. | “A planner proposes structured tasks. Before any tool runs, runtime checks arguments and dependencies and rejects cycles.” | Plan accepted; 8 tasks in accepted CI fixture run. | Validation; dependency DAG; cycle check. |
| 2:15–3:05 | Open Execution and select plan/ready/task events as they appear. | Chronological events, task timeline, inspector. | “Independent source tasks are ready together. A join task waits until its prerequisites finish. The runtime—not the browser—decides readiness.” | Source tasks progress; downstream tasks become ready after prerequisites. | DAG; topological readiness; event stream. |
| 3:05–3:55 | Open FODS Lab and point to DAG, queue and state map. | Task nodes, enqueue/dequeue rows, task-state records. | “The FIFO policy follows insertion order. The alternate priority heap chooses the highest fixed priority; sequence number breaks ties. The task map is indexed by task ID.” | Recorded queue operations and state transitions are visible. | Queue/heap; map; worker scheduling. |
| 3:55–4:45 | Show the nested stack panel and one failure/recovery demonstration control if rehearsal permits. | Push/pop or recovery records; otherwise use the accepted run’s normal event list. | “Each executing task has its own trace stack. Bounded failure handling is recorded; a failed prerequisite can leave dependent work blocked. This view reads runtime events.” | Stack transitions or a clearly labeled saved recovery scenario. | Stack; state machine; bounded recovery. |
| 4:45–5:40 | Open Evidence & answer after run completion. | Four context papers and four evidence cards for accepted CI run, or local saved run’s content. | “The context is reusable. The answer sees a bounded evidence slice rather than the entire corpus. The saved run records which cards were selected.” | Evidence cards and their paper IDs/citation labels are inspectable. | Context; evidence selection; provenance. |
| 5:40–6:30 | Click a citation marker or inspect citation status/source list. | Selected card, citation mapping and validation state. | “The guard checks whether cited IDs resolve to selected evidence and whether the brief path is allowed. That is a citation-ID check, not proof that the wording is entailed by the source.” | Accepted fixture has P1/P2/P3 as validated IDs; no semantic-validity claim. | Output guard; referential integrity; evidence limits. |
| 6:30–7:15 | Open the brief file or show its rendered section. | Brief text and Sources section. | “The runtime writes only after the citation check. The trace and brief preserve what this run did.” | Brief displays cited answer and source list. | Safe output; persistence. |
| 7:15–8:05 | Open Runs & Replay or run replay on a saved JSONL artifact. | History/replay view or HTML trace; replay badge. | “Replay renders recorded events. It does not repeat source calls or model calls, so it is useful for inspection but not evidence of live concurrency.” | Events appear in sequence; replay is visibly labeled. | Event log; replay provenance. |
| 8:05–8:45 | Briefly show the isolated Graph Attention Networks graph CLI result or inventory summary. | Graph stats/follow-up output if available. | “This is a separate optional index over saved enrichments. The isolated v2 example has 29 eligible papers. Its shared concepts are vocabulary overlap, not semantic agreement.” | Graph operation is distinguished from the paper-to-brief run. | Optional knowledge graph; separation of concerns. |
| 8:45–9:15 | Close with current status. | README/documentation map or final slide-free closing. | “Backend acceptance passed in CI. Retrieval quality still needs human labels, citation checks are not semantic evaluation, and the Chat/Trace/Visualizer redesign is proposed future work.” | Accurate statement of acceptance and remaining gates. | Evaluation honesty; roadmap. |

## Speaking transitions

**Opening:** “I’ll follow one question from submission to evidence-backed output, and point out where the runtime’s data structures make the execution visible.”

**From plan to execution:** “The plan describes prerequisites; the scheduler turns those prerequisites into the set of work that is safe to run next.”

**From runtime to evidence:** “Once retrieval finishes, the question becomes: which saved records are actually selected to support the answer?”

**From answer to replay:** “The final answer is only one artifact. The event log lets us inspect how the runtime reached it, and replay does not rerun the work.”

**Conclusion:** “This demonstrates the implemented FODS runtime and its deterministic acceptance path. It does not claim live retrieval quality. Our next evaluation gate is independent human review of the collected relevance judgments.”

## Graph demonstration commands

The following commands were run successfully against the isolated copied graph; set the data root before use so the original schema-v1 snapshot is not affected:

```powershell
$env:RLA_DATA_DIR = (Resolve-Path ".pytest-tmp\mvp-existing-context-demo-99861ac9\data").Path
.\.venv\Scripts\python.exe -m fods.cli graph stats --topic "Graph attention networks"
.\.venv\Scripts\python.exe -m fods.cli graph follow-up --topic "Graph attention networks" --question "Which papers use GAT?"
.\.venv\Scripts\python.exe -m fods.cli graph follow-up --topic "Graph attention networks" --question "What findings are reported for graph attention networks?"
.\.venv\Scripts\python.exe -m fods.cli graph follow-up --topic "Graph attention networks" --question "What limitations are mentioned for graph attention networks?"
.\.venv\Scripts\python.exe -m fods.cli graph follow-up --topic "Graph attention networks" --question "Which papers cite W2766453196?"
```

The local exact output counts are 2 method records, 5 findings, 1 limitation, and 7 stored citations. See the [artifact inventory](fods_demo_artifact_inventory.md) for IDs and provenance.
