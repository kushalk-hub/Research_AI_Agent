# FODS Research Studio — Design Acceptance Criteria

**Status:** The owner approved the design direction on 2026-11-01. These remain production acceptance gates; checked boxes must be supported by implementation/test evidence.  
**Design:** [`fods_research_studio_redesign.md`](fods_research_studio_redesign.md)  
**Prototype:** [`design/prototypes/fods-research-studio/index.html`](../../design/prototypes/fods-research-studio/index.html)

## Gate 0 — Owner approval

- [x] Owner approved production implementation of the Research Studio in the existing application on 2026-11-01.
- [ ] Compare the production implementation with the approved Research, completed brief, Trace, FODS Lab and Library direction.
- [ ] Design retains benchmark review as pending/unpassed; synthetic fixtures are never used as retrieval-quality evidence.
- [ ] Supplied screenshot set is reviewed when accessible; image-specific findings are reconciled against source-based findings.

**Evidence:** recorded design approval/comments and a screenshot comparison set, if screenshots are supplied.

## Gate 1 — Navigation and run identity

- [ ] Primary navigation is exactly Research, Trace, FODS Lab and Library; creation action is New investigation.
- [ ] UI uses investigation/run terminology. No Chat/session/thread wording implies persistence unsupported by backend.
- [ ] New-investigation draft is visibly separate from selected investigation's submitted question/result.
- [ ] For one selected `run_id`, question, actual mode, replay source, answer, citation status, brief, evidence and trace all resolve to that same run or a recorded linked source run.
- [ ] Changing draft mode/topic/question never changes selected-run metadata.
- [ ] Replay is launched from a saved investigation; a replay is labeled REPLAY and never appears as new live retrieval.
- [ ] Follow-up action states whether it creates a linked new run and whether it reuses context or refreshes sources.

**Evidence:** browser tests that switch between a draft, two saved investigations with different questions/modes, and replay; assert IDs and content in each view.

## Gate 2 — Research lifecycle

- [ ] Empty state centers “What do you want to investigate?”, with question, optional topic, distinct real-research and synthetic-demo choices, and Start investigation.
- [ ] Technical options are under Advanced execution settings and do not require model/provider choices for the normal path.
- [ ] Replay is absent from new-run execution choices.
- [ ] Active run shows submitted question, run ID, actual execution mode, task progress and waiting/failure states.
- [ ] Plan → Retrieve → Merge → Select evidence → Draft → Validate → Brief stages map to events or are explicitly labeled as coarse stage projections.
- [ ] Source/model identity is shown only when recorded as actually used; configured/unknown models are not presented as completed calls.
- [ ] Completed brief renders stored answer/sections without inventing a summary or key findings.
- [ ] Citation-ID validation is named separately from semantic support; no semantic claim is made without separate review evidence.
- [ ] Evidence inspector shows exact stored metadata and excerpt. Missing text renders “No excerpt recorded”; it is not generated.
- [ ] Saved-brief success appears only after persisted save and valid citation gate.

**Evidence:** automated state tests for empty, active, partial/failure, completed valid-citation, invalid-citation, missing excerpt and no-model-attribution cases; one real deterministic browser walkthrough.

## Gate 3 — Trace

- [ ] Lanes cover Run/planning, FODS tasks, Sources, Tools, Models, Context/evidence, Answer/output.
- [ ] Event table and timeline are derived from the same persisted event sequence; selected item includes its exact sequence number.
- [ ] Event type/lane, status, task, model/provider and text filters work and can be combined.
- [ ] Live updates can be paused for inspection and resumed without event loss or order changes.
- [ ] Start/end/duration render only when paired lifecycle events or supported duration fields establish them.
- [ ] Grouped/nested spans require recorded task/activity/parent/correlation information; otherwise items are marked uncorrelated.
- [ ] Retry, failure, attempt and recovery decision remain visible and filterable.
- [ ] Readable event details are primary; raw JSON is collapsed and uses the original payload.
- [ ] Replay origin and replay provenance are distinguishable from fresh execution.

**Evidence:** event-log fixtures with correlated and uncorrelated events, retries, failure, missing end events and replay; assert no invented spans/durations.

## Gate 4 — FODS Lab and event cursor

- [ ] DAG uses validated plan topology; fan-out/fan-in edges, role, state, readiness and selection are distinguishable.
- [ ] Task selection synchronizes DAG, scheduler, task-state map, stack and trace to the selected task/cursor.
- [ ] FIFO shows FRONT/REAR and recorded enqueue/dequeue operations; unavailable state is distinct from empty state.
- [ ] Priority view reports actual dequeue order and priority/tie information from events.
- [ ] A binary heap is labeled conceptual unless insertion/dequeue/priority/tie evidence reconstructs the exact heap at each cursor position.
- [ ] Concurrent intervals are called “Concurrent execution lanes (inferred)” while worker identifiers are absent; no worker number or assignment is implied.
- [ ] Task-state map is a task ID → state dictionary display with no fabricated buckets/collisions.
- [ ] Per-task stacks use LIFO orientation and TOP marker; only stored push/pop operations are shown, and incomplete history is labeled.
- [ ] Play, pause, step forward/back, reset, speed and follow-live controls drive one shared event cursor.
- [ ] Backward stepping is labeled view history/projection and never implies runtime rollback.
- [ ] Completed runs distinguish a proven empty queue from queue state not recorded.
- [ ] If opening at the terminal event, a clear terminal state appears and a shortcut jumps to an informative scheduler/task event without changing selected-run identity.
- [ ] Six guided synthetic lessons cover DAG readiness, FIFO/priority, bounded concurrency, task states, stack operations and failure/retry/recovery. Each names concept, causal event and observation.

**Evidence:** deterministic event fixtures at initial, enqueue, dequeue, concurrent, retry, stack, failure and terminal cursors; visual review and keyboard interaction checks.

## Gate 5 — Library

- [ ] Investigations and saved contexts are separately searchable/filterable where API data permits.
- [ ] Investigation rows show question/title, run ID, actual mode/status and only available artifacts/links.
- [ ] Saved context identity/version/freshness is shown only when recorded.
- [ ] Replay is sourced from an existing saved run and makes no source/model calls.
- [ ] Missing relationships are shown as unknown rather than inferred from topic similarity.
- [ ] Empty, loading, error, stale, missing-log and no-context states are designed.

**Evidence:** API contract tests and fixtures for no history, multiple modes, missing fields and corrupted/missing event logs.

## Gate 6 — Accessibility, responsiveness, safety and compatibility

- [ ] All navigation, selection, filters, cursor/playback, dialogs and drawers are keyboard accessible with visible focus and useful accessible names.
- [ ] State is not conveyed by color alone; contrast and reduced-motion behavior meet project accessibility policy.
- [ ] Desktop, tablet and narrow mobile layouts preserve run provenance and event sequence; timelines have accessible alternatives.
- [ ] Raw payloads and model/tool fields are redacted consistently with backend policy; no credential reaches browser responses.
- [ ] Existing CLI, JSONL, API/SSE, replay, brief and classic workbench remain compatible until explicit acceptance replaces the fallback.
- [ ] No semantic graph relations or quality metrics are invented. No external API call is triggered by opening the prototype or demo scenario.

**Evidence:** automated accessibility/component checks, API/security regression suite, viewport checks, and classic-fallback smoke test.

## Gate 7 — Release evidence

- [ ] Full focused frontend/API suite passes, full project suite is run and reported accurately, Ruff passes, and compilation passes.
- [ ] At least one live browser capture shows the actual implementation; screenshots are genuine and tied to the tested run/mode.
- [ ] Manual live retrieval is either demonstrated with recorded provider attribution or marked environment-blocked.
- [ ] Automated API/SSE evidence, browser evidence, replay evidence and human review evidence are reported separately.
- [ ] Owner explicitly approves the design/prototype before production rewrite starts.

**Evidence:** commands, pass/fail/skip totals, duration, browser screenshots, run ID/trace/brief, and owner approval. No screenshot or pass claim is fabricated when the environment blocks capture.
