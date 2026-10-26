# Prior art scan — external approaches adopted into the design

Collected 26 October 2026. These are independent of `docs/research.md` (which cites
the LLM-agent frameworks). This file records the *scheduler/execution-engine* side:
patterns we deliberately borrow, and what we explicitly do not take.

## Adopted patterns

1. **Event-driven executor with ready-set + in-flight map** — a task starts the moment
   its last dependency completes, not in fixed rounds.
   Source: open-multi-agent task-scheduling docs
   (https://github.com/open-multi-agent/open-multi-agent/blob/main/docs/task-scheduling.md).
   Our `TaskGraph` keeps in-degree counters; the executor loop re-sweeps readiness on
   every completion. This is exactly Kahn's algorithm used as a live scheduler.

2. **Static plan validation *before* compilation/executable execution** — rejection of
   structurally invalid plans (missing nodes, dangling dependencies, duplicates,
   cycles) with a typed diagnostic before any work runs. Source: "PlanCompiler: A
   Deterministic Compilation Architecture for Structured Multi-Step LLM Pipelines"
   (https://arxiv.org/pdf/2604.13092).
   Our `plan/validate.py` runs the full checklist first; a rejected plan never
   instantiates a tool.

3. **Cycle detection with path reporting** — not just "cycle detected" but the actual
   offending path (a → b → c → a). Standard in community DAG schedulers, e.g. the
   pure-Python task-scheduler repo (https://github.com/makx518-ui/task-scheduler),
   whose feature list (dependency resolution, priority queue, bounded retries, cycle
   tests incl. self-loops) is nearly the same matrix as our validator test plan.

4. **Failure → downstream blocked → bounded replan** — on failure, downstream tasks are
   marked blocked *immediately*, then recovery chooses retry / substitute / restructure
   the remaining subgraph, always within an attempt budget with a visible termination
   reason. Sources: EngineersOfAI agent-planning discussion
   (https://engineersofai.com/playground/agent-planning) and the 10x execution-engine
   breakdown (https://medium.com/@shramanpadhalni/the-10x-agent-part-3-the-execution-engine-dag-scheduling-8-execution-strategies-and-why-7d8030fd2a13).

5. **Topological levels = natural parallel rounds** — level 0 = all roots, level N =
   tasks whose deps are all in N−1. Source: same 10x breakdown. We keep levels as a
   *reporting view* over the event stream (rounds display) while execution itself is
   event-driven — the two views must agree, which is our scenarios 1–2 evidence.

6. **Event-sourced, append-only run ledger with replay** — every run stores its graph,
   tasks, attempts, events; a UI reconstructs from the ledger. Sources: LightDAG
   (https://github.com/wanxingai/LightAgent/blob/main/docs/lightdag.md) and DeepSeek
   Harness (already cited in research.md). Our JSONL run log is this, scoped small.

7. **Retry with explicit policies and cancellation discipline** — per-task max attempts,
   budget enforcement mid-execution, one-line abort. Sources: Temporal retry docs
   (https://docs.temporal.io/tasks), taskpipe (https://pypi.org/project/taskpipe/)
   — its YAML-facing surface also reminded us to keep *default* budgets in config, not code.

## Consulted and deliberately *not* adopted

- **Cascade scheduling / LLM-as-scheduler gating** (ACL 2026 llm-as-scheduler paper):
  academic-scale dynamic hop selection. Too heavy; our policy is deterministic by design.
- **PLAS-style serving-engine prioritization** (Agentix, NSDI '26): allocation weights
  across concurrent LLM pipelines. Irrelevant at one-orchestrator scale.
- **Temporal/long-lived durable workflows**: operational magnitude far beyond a course
  runtime; we take only the *retry-as-new-attempt-with-history* idea.
- **SQLite per-run persistence for graph/tasks/events** (LightDAG): we keep JSONL as
  the ledger and reserve SQLite solely for the LLM cache — fewer moving parts first;
  SQLite upgrade path remains open for the final version.

## Prior-art sources list

- https://github.com/open-multi-agent/open-multi-agent/blob/main/docs/task-scheduling.md
- https://arxiv.org/pdf/2604.13092 (PlanCompiler)
- https://github.com/makx518-ui/task-scheduler
- https://engineersofai.com/playground/agent-planning
- https://medium.com/@shramanpadhalni/the-10x-agent-part-3-the-execution-engine-dag-scheduling-8-execution-strategies-and-why-the-7d8030fd2a13 (retrieved via shorter URL above)
- https://github.com/wanxingai/LightAgent/blob/main/docs/lightdag.md
- https://docs.temporal.io/tasks
- https://pypi.org/project/taskpipe/
- https://github.com/qpiai/dagent (planner → DAG build → orchestration flow reference)
- Agentic Computation Graphs / scheduler-theoretic survey (https://arxiv.org/html/2604.11378v1) — vocabulary check ("static template vs dynamic runtime graph"), confirms our plan-DAG vs runtime-transition-graph separation is the field's own distinction.
