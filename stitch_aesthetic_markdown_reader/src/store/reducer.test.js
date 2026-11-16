import { describe, expect, it } from "vitest";
import { MAX_EVENTS_PER_RUN, applyEvents, initialState, reducer } from "./reducer.js";

const handle = {
  run_id: "0123456789ab",
  engine: "fods",
  run_kind: "simulate",
  source_run_id: null,
  topic: "Deterministic demo",
  status: "starting",
  event_count: 0,
  error: "",
  output_path: "data/fods/briefs/0123456789ab.md",
  events_url: "/api/runs/0123456789ab/events",
};

function opened() {
  return reducer(initialState, {
    type: "run/opened",
    handle,
    request: { mode: "simulate", planner: "fixture", topic: handle.topic, question: "Why?" },
  });
}

describe("run lifecycle", () => {
  it("opens a run as starting and selects it", () => {
    const state = opened();
    expect(state.activeRunId).toBe(handle.run_id);
    expect(state.runs[handle.run_id].status).toBe("starting");
    expect(state.runs[handle.run_id].stream).toBe("connecting");
    expect(state.runs[handle.run_id].question).toBe("Why?");
  });

  it("moves to running on the first event, not before", () => {
    const state = reducer(opened(), {
      type: "run/events",
      runId: handle.run_id,
      events: [{ seq: 1, kind: "run_started", payload: {} }],
    });
    expect(state.runs[handle.run_id].status).toBe("running");
    expect(state.runs[handle.run_id].events).toHaveLength(1);
  });

  it("derives the terminal status and reason from run_finished", () => {
    const state = reducer(opened(), {
      type: "run/events",
      runId: handle.run_id,
      events: [
        { seq: 1, kind: "run_started", payload: {} },
        {
          seq: 2,
          kind: "run_finished",
          timestamp: 1_700_000_000,
          payload: {
            succeeded: false,
            termination_reason: "completed_with_partial_sources",
            unavailable_sources: ["arxiv"],
          },
        },
      ],
    });
    const run = state.runs[handle.run_id];
    expect(run.status).toBe("partial");
    expect(run.stream).toBe("idle");
    expect(run.statusReason).toContain("1 source unavailable (arxiv)");
    expect(run.endedAt).toBe(1_700_000_000_000);
  });

  it("caps retained events instead of growing without bound", () => {
    const many = Array.from({ length: MAX_EVENTS_PER_RUN + 10 }, (_, index) => ({
      seq: index + 1,
      kind: "stage_progress",
      payload: {},
    }));
    const run = applyEvents({ ...opened().runs[handle.run_id] }, many);
    expect(run.events).toHaveLength(MAX_EVENTS_PER_RUN);
    expect(run.events[0].seq).toBe(11);
  });
});

describe("workspace actions", () => {
  it("clears the active run on New investigation", () => {
    const state = reducer(opened(), { type: "ui/new-investigation" });
    expect(state.activeRunId).toBeNull();
    expect(state.page).toBe("research");
    expect(state.runs[handle.run_id]).toBeDefined();
  });

  it("ignores selecting a run this tab has not opened", () => {
    const state = reducer(initialState, { type: "run/selected", runId: "ffffffffffff" });
    expect(state.activeRunId).toBeNull();
  });

  it("keeps bootstrap facts separate from run state", () => {
    const state = reducer(initialState, {
      type: "bootstrap/succeeded",
      config: { llm_request_budget: 15 },
      history: [{ run_id: "aaaaaaaaaaaa" }],
      contexts: [{ id: "ctx" }],
    });
    expect(state.connection).toBe("ready");
    expect(state.config.llm_request_budget).toBe(15);
    expect(state.history).toHaveLength(1);
    expect(state.contexts).toHaveLength(1);
  });
});
