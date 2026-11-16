import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  formatCounts,
  LAB_NODE,
  LAB_PIPELINES,
  labCaption,
  labPipeline,
  layoutGraph,
  phaseRail,
  planModel,
  schedulerModel,
  stageCounts,
  cycleTasks,
} from "./lab.js";

/** Golden recorded logs, not fixtures invented for the test.
 *
 *  `efee736eb669` is the RLA run the audit used for UI-07 (50 progress events,
 *  no plan); `17ee03228c0b` is the 8-task deterministic demo; `Q01-deep` is the
 *  26-task live run with two cancelled sources. */
function events(name) {
  return readFileSync(
    resolve(process.cwd(), "..", "tests", "fixtures", "fods_logs", `${name}.jsonl`),
    "utf8",
  )
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function runOf(name, overrides = {}) {
  return { id: name, events: events(name), pipeline: "", engine: "", ...overrides };
}

const PHASES = ["search", "fetch", "score", "fulltext", "extract", "resolve"];

describe("labPipeline", () => {
  it("reads the declared pipeline, then the engine, then the recorded vocabulary", () => {
    expect(labPipeline({ pipeline: "fods-scheduler" })).toBe(LAB_PIPELINES.scheduler);
    expect(labPipeline({ pipeline: "rla-phases" })).toBe(LAB_PIPELINES.phases);
    expect(labPipeline(runOf("efee736eb669"))).toBe(LAB_PIPELINES.phases);
    expect(labPipeline(runOf("17ee03228c0b"))).toBe(LAB_PIPELINES.scheduler);
    expect(labPipeline({ events: [] })).toBe("unknown");
  });

  it("prefers the pipeline recorded inside run_started", () => {
    expect(
      labPipeline({
        events: [{ kind: "run_started", payload: { pipeline: "rla-phases", engine: "fods" } }],
      }),
    ).toBe(LAB_PIPELINES.phases);
  });
});

describe("RLA phase rail", () => {
  it("renders the 10 recorded phases in recorded order and says order is not declared", () => {
    const rail = phaseRail(runOf("efee736eb669"));
    expect(rail.declared).toBe(false);
    expect(rail.stages.map((stage) => stage.id)).toEqual([
      "search",
      "fetch",
      "score",
      "fulltext",
      "extract",
      "resolve",
      "graph",
      "traverse",
      "answer",
      "done",
    ]);
    expect(rail.note).toMatch(/predates the declared stage list/);
    expect(rail.stages.every((stage) => stage.recorded)).toBe(true);
    expect(rail.stages.every((stage) => stage.timing === null)).toBe(true);
  });

  it("marks fulltext as a Phase 2 stub, never as completed", () => {
    const rail = phaseRail(runOf("efee736eb669"));
    const fulltext = rail.stages.find((stage) => stage.id === "fulltext");
    expect(fulltext.stub).toBe(true);
    expect(fulltext.recorded).toBe(true);
    expect(fulltext.counts).toEqual([]);
  });

  it("shows the counts the stage payload recorded", () => {
    const rail = phaseRail(runOf("efee736eb669"));
    const counts = (id) =>
      formatCounts(rail.stages.find((stage) => stage.id === id).counts);

    expect(counts("search")).toBe("sources 5 · queries 4");
    expect(counts("score")).toContain("scored 30");
    expect(counts("extract")).toBe("reused 10 · pending 0");
    expect(counts("graph")).toBe("papers 10 · concepts 33 · derived edges 36 · citations 2");
    expect(counts("done")).toBe(
      "cache hits 75 · cache misses 10 · extractions reused 10 · extractions new 0",
    );
    expect(formatCounts([])).toBe("");
  });

  it("uses the backend's declared stages and order when run_started carries them", () => {
    const stages = [...PHASES, "graph", "traverse", "answer", "done"]
      .map((id, index) => ({ id, label: `Stage ${id}`, order: index }))
      .reverse(); // input order must not matter
    const rail = phaseRail({
      id: "declared",
      events: [
        {
          kind: "run_started",
          payload: { pipeline: "rla-phases", pipeline_stages: stages },
        },
        {
          kind: "research_progress",
          payload: { phase: "score", stage_payload: { scored: 12 }, message: "score" },
        },
        {
          kind: "run_finished",
          payload: {
            succeeded: true,
            stages: [{ id: "score", started_ms: 10, duration_ms: 20 }],
          },
        },
      ],
    });

    expect(rail.declared).toBe(true);
    expect(rail.stages).toHaveLength(10);
    expect(rail.stages.map((stage) => stage.id)).toEqual([
      "search",
      "fetch",
      "score",
      "fulltext",
      "extract",
      "resolve",
      "graph",
      "traverse",
      "answer",
      "done",
    ]);
    expect(rail.stages.every((stage) => stage.label.startsWith("Stage "))).toBe(true);
    expect(rail.stages.find((stage) => stage.id === "score")).toMatchObject({
      recorded: true,
      timing: { started_ms: 10, duration_ms: 20 },
    });
    expect(rail.stages.find((stage) => stage.id === "extract")).toMatchObject({
      recorded: false,
      counts: [],
    });
    expect(rail.note).toBe("");
  });

  it("never reports an absent stage as zero", () => {
    expect(stageCounts({}, "score")).toEqual([]);
    expect(stageCounts({ sources: [] }, "fetch")).toEqual([
      { key: "sources", value: 0 },
    ]);
  });
});

describe("scheduler plan", () => {
  it("uses the validated Kahn levels and recorded dependencies for the demo", () => {
    const plan = planModel(events("17ee03228c0b"));
    expect(plan.tasks).toHaveLength(8);
    expect(plan.levels).toHaveLength(6);
    expect(plan.levelsComputed).toBe(false);
    expect(plan.levels[0]).toEqual([
      "search_semantic_scholar",
      "search_openalex",
      "search_arxiv",
    ]);
    expect(plan.tasks.find((task) => task.id === "merge").dependsOn).toEqual([
      "search_semantic_scholar",
      "search_openalex",
      "search_arxiv",
    ]);
    expect(plan.tasks.every((task) => task.priority !== null)).toBe(true);
  });

  it("lays the 26-task live plan out in its recorded 8 levels", () => {
    const plan = planModel(events("Q01-deep"));
    expect(plan.tasks).toHaveLength(26);
    expect(plan.levels).toHaveLength(8);
    expect(plan.levels[0]).toHaveLength(5);
    expect(plan.levels[2]).toHaveLength(15);
    expect(plan.levelsComputed).toBe(false);
  });

  it("computes levels from dependencies only when the log has none", () => {
    const plan = planModel([
      {
        kind: "plan_received",
        payload: {
          tasks: [
            { id: "a", tool: "search_a", depends_on: [] },
            { id: "b", tool: "search_b", depends_on: [] },
            { id: "c", tool: "merge_and_save_context", depends_on: ["a", "b"] },
            { id: "d", tool: "write_cited_brief", depends_on: ["c"] },
          ],
        },
      },
    ]);
    expect(plan.levelsComputed).toBe(true);
    expect(plan.levels).toEqual([["a", "b"], ["c"], ["d"]]);
    expect(plan.hasCycle).toBe(false);
  });

  it("records a rejected cyclic plan without pretending it ran", () => {
    const plan = planModel([
      {
        kind: "plan_received",
        payload: {
          tasks: [
            { id: "a", tool: "t", depends_on: ["b"] },
            { id: "b", tool: "t", depends_on: ["a"] },
          ],
        },
      },
      {
        kind: "plan_rejected",
        payload: {
          message: "plan rejected: dependency cycle a -> b -> a",
          tasks: [
            { id: "a", tool: "t", depends_on: ["b"] },
            { id: "b", tool: "t", depends_on: ["a"] },
          ],
        },
      },
    ]);
    expect(plan.rejected).toBe(true);
    expect(plan.rejectionMessage).toMatch(/cycle/);
    expect(plan.rejectedTasks).toHaveLength(2);
    expect(plan.hasCycle).toBe(true);
    expect(cycleTasks(plan.rejectedTasks)).toEqual(["a", "b"]);
  });
});

describe("scheduler state, queue, workers and stacks", () => {
  it("folds the demo into 8 completed tasks with 8 recorded durations", () => {
    const model = schedulerModel(events("17ee03228c0b"));
    expect(model.tasks).toHaveLength(8);
    expect(model.tasks.every((task) => task.state === "completed")).toBe(true);
    expect(model.tasks.filter((task) => task.durationMs !== null)).toHaveLength(8);
    expect(model.counts).toMatchObject({ total: 8, completed: 8, failed: 0 });
    expect(model.workers.concurrency).toBe(3);
    expect(model.workers.slotOrderAvailable).toBe(false);
    expect(model.stacks.taskCount).toBe(8);
  });

  it("keeps cancellation a recorded state, not a guessed failure", () => {
    const model = schedulerModel(events("Q01-deep"));
    expect(model.counts).toMatchObject({ total: 26, completed: 24, cancelled: 2 });
    expect(model.tasks.filter((task) => task.state === "cancelled")).toHaveLength(2);
    expect(model.tasks.find((task) => task.state === "cancelled").tool).toMatch(/^search_/);
  });

  it("shows at most the recorded concurrency of running tasks", () => {
    const seen = [];
    for (const cursor of [40, 60, 80, 120, 200, 300]) {
      const model = schedulerModel(events("Q01-deep").slice(0, cursor));
      seen.push(model.concurrency.active);
      expect(model.concurrency.active).toBeLessThanOrEqual(model.concurrency.capacity);
    }
    expect(seen.some((active) => active > 0)).toBe(true);
  });

  it("reports the recorded queue snapshot and the last non-empty one", () => {
    const model = schedulerModel(events("17ee03228c0b"));
    expect(model.queue.policy).toBe("fifo");
    expect(model.queue.recorded).toBe(true);
    expect(model.queue.priorityRecorded).toBe(false);
    expect(model.queue.priorityMissingBecause).toBe("fifo");
    // At the head the run has drained the queue; the last snapshot is kept.
    expect(model.queue.items).toEqual([]);
    expect(model.queue.lastNonEmpty.seq).toBeGreaterThan(0);
    expect(model.queue.lastNonEmpty.items).toHaveLength(1);
  });

  it("reads priorities only when the priority queue snapshot recorded them", () => {
    const model = schedulerModel([
      { kind: "run_started", payload: { concurrency: 1, schedule: "priority" } },
      {
        kind: "queue_updated",
        seq: 2,
        payload: {
          schedule: "priority",
          ready_queue: [
            { task_id: "a", priority: 30, sequence: 0 },
            { task_id: "b", priority: 10, sequence: 1 },
          ],
        },
      },
    ]);
    expect(model.queue.priorityRecorded).toBe(true);
    expect(model.queue.items[0]).toEqual({ taskId: "a", priority: 30, sequence: 0 });
  });

  it("uses the stack array the event recorded, including a pop back to the run frame", () => {
    const model = schedulerModel([
      {
        kind: "task_started",
        payload: { task_id: "t1", stack: ["run:r1", "task:t1"], attempt: 1 },
      },
      {
        kind: "stack_push",
        payload: { task_id: "t1", stack: ["run:r1", "task:t1", "tool:search_arxiv"] },
      },
      {
        kind: "stack_pop",
        payload: { task_id: "t1", stack: ["run:r1", "task:t1"] },
      },
    ]);
    expect(model.stacks.byTask.t1).toEqual(["run:r1", "task:t1"]);
    expect(model.stacks.latest).toEqual(["run:r1", "task:t1"]);
  });

  it("does not invent a worker id or a provider peak", () => {
    const model = schedulerModel(events("17ee03228c0b"));
    expect(model.workers.slotOrderAvailable).toBe(false);
    expect(model.concurrency.peak).toEqual([]);
  });
});

describe("graph layout", () => {
  it("is deterministic and follows the level grid", () => {
    const plan = planModel(events("17ee03228c0b"));
    const first = layoutGraph(plan);
    const second = layoutGraph(plan);
    expect(first.width).toBe(second.width);
    expect(first.height).toBe(second.height);
    expect([...first.positions.entries()]).toEqual([...second.positions.entries()]);
    const merge = first.positions.get("merge");
    expect(merge.x).toBe(LAB_NODE.pad + (LAB_NODE.width + LAB_NODE.gutter));
    expect(first.edges).toHaveLength(8);
    expect(first.edges[0].path.startsWith("M ")).toBe(true);
    expect(first.edges[0].path).toContain(" C ");
  });

  it("sizes the 26-task live graph without collapsing the wide level", () => {
    const layout = layoutGraph(planModel(events("Q01-deep")));
    expect(layout.width).toBeGreaterThan(2000);
    expect(layout.height).toBeGreaterThan(1500);
    expect(layout.nodes).toHaveLength(26);
  });
});

describe("captions", () => {
  const run = {
    id: "captions",
    events: [
      {
        seq: 1,
        kind: "task_ready",
        timestamp: 1000,
        payload: { task_id: "a", prerequisites: [], remaining_prerequisites: 0 },
      },
      {
        seq: 2,
        kind: "task_ready",
        timestamp: 2000,
        payload: { task_id: "b", prerequisites: [], remaining_prerequisites: 0 },
      },
      {
        seq: 3,
        kind: "task_completed",
        timestamp: 9000,
        payload: { task_id: "a", duration_ms: 120 },
      },
      {
        seq: 4,
        kind: "run_finished",
        timestamp: 9400,
        payload: { succeeded: true, termination_reason: "completed" },
      },
    ],
  };

  it("keeps the earlier caption inside the four-second window", () => {
    const caption = labCaption(run, 2);
    expect(caption.seq).toBe(1);
    expect(caption.text).toBe("no prerequisites → a enters the queue");
  });

  it("moves on after the window and always shows a terminal caption", () => {
    expect(labCaption(run, 3).text).toBe("a completed in 120 ms");
    expect(labCaption(run, 4).text).toBe("run finished: Completed");
  });

  it("returns a stable dismissal id and no caption for an empty cursor", () => {
    expect(labCaption(run, 2).id).toBe("captions:1");
    expect(labCaption(run, 0)).toBeNull();
    expect(labCaption({ id: "x", events: [] }, 0)).toBeNull();
  });
});
