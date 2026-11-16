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

describe("status reconciliation", () => {
  it("takes the recorded status from GET /api/runs/<id>", () => {
    const state = reducer(opened(), {
      type: "run/info",
      runId: handle.run_id,
      info: {
        status: "completed",
        status_reason: "completed",
        historical: true,
        pipeline: "rla-phases",
        warnings: 2,
        started_at: 1_700_000_000,
        ended_at: 1_700_000_010,
      },
    });
    const run = state.runs[handle.run_id];
    expect(run.status).toBe("completed");
    expect(run.historical).toBe(true);
    expect(run.pipeline).toBe("rla-phases");
    expect(run.warnings).toBe(2);
    expect(run.startedAt).toBe(1_700_000_000_000);
    expect(run.endedAt).toBe(1_700_000_010_000);
  });

  it("never lets a late fetch overwrite a terminal event already streamed", () => {
    let state = reducer(opened(), {
      type: "run/events",
      runId: handle.run_id,
      events: [
        { seq: 1, kind: "run_started", payload: {} },
        {
          seq: 2,
          kind: "run_finished",
          timestamp: 1_700_000_000,
          payload: { succeeded: false, termination_reason: "cancelled" },
        },
      ],
    });
    state = reducer(state, {
      type: "run/info",
      runId: handle.run_id,
      info: { status: "running", status_reason: "" },
    });
    expect(state.runs[handle.run_id].status).toBe("cancelled");
    expect(state.runs[handle.run_id].statusReason).toBe("cancelled");
  });
});

describe("stop", () => {
  function cancelled() {
    return reducer(opened(), {
      type: "run/events",
      runId: handle.run_id,
      events: [
        { seq: 1, kind: "run_started", payload: {} },
        {
          seq: 2,
          kind: "run_finished",
          timestamp: 1_700_000_000,
          payload: { succeeded: false, termination_reason: "cancelled" },
        },
      ],
    });
  }

  it("marks a requested stop and clears it when the request is rejected", () => {
    const requested = reducer(opened(), { type: "run/stop-requested", runId: handle.run_id });
    expect(requested.runs[handle.run_id].stopping).toBe(true);
    const rejected = reducer(requested, { type: "run/stop-rejected", runId: handle.run_id });
    expect(rejected.runs[handle.run_id].stopping).toBe(false);
  });

  it("clears the pending flag as soon as the recorded outcome arrives", () => {
    let state = reducer(opened(), { type: "run/stop-requested", runId: handle.run_id });
    state = reducer(state, {
      type: "run/events",
      runId: handle.run_id,
      events: [{ seq: 1, kind: "run_started", payload: {} }],
    });
    // A non-terminal batch must not pretend the stop happened.
    expect(state.runs[handle.run_id].stopping).toBe(true);
    state = reducer(state, {
      type: "run/events",
      runId: handle.run_id,
      events: [
        {
          seq: 2,
          kind: "run_finished",
          timestamp: 1_700_000_000,
          payload: { succeeded: false, termination_reason: "cancelled" },
        },
      ],
    });
    expect(state.runs[handle.run_id].stopping).toBe(false);
    expect(state.runs[handle.run_id].status).toBe("cancelled");
    expect(cancelled().runs[handle.run_id].status).toBe("cancelled");
  });
});

describe("workspace actions", () => {
  it("clears the active run on New investigation", () => {
    const state = reducer(opened(), { type: "ui/new-investigation" });
    expect(state.activeRunId).toBeNull();
    expect(state.page).toBe("research");
    expect(state.runs[handle.run_id]).toBeDefined();
  });

  it("clears the local composer on New investigation but keeps the chosen mode", () => {
    let state = opened();
    state = reducer(state, { type: "composer/mode", mode: "demo" });
    state = reducer(state, { type: "composer/topic", topic: "My topic" });
    state = reducer(state, { type: "composer/override", field: "paper_limit", value: "7" });

    const cleared = reducer(state, { type: "ui/new-investigation" });
    expect(cleared.composerEpoch).toBe(state.composerEpoch + 1);
    expect(cleared.composer.mode).toBe("demo");
    expect(cleared.composer.topic).toBe("");
    expect(cleared.composer.overrides.paper_limit).toBeNull();
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

  describe("composer", () => {
    it("closes the menu when a mode is chosen", () => {
      const open = reducer(initialState, { type: "composer/menu" });
      expect(open.composer.menuOpen).toBe(true);
      const picked = reducer(open, { type: "composer/mode", mode: "demo" });
      expect(picked.composer.mode).toBe("demo");
      expect(picked.composer.menuOpen).toBe(false);
    });

    it("records only the fields the user edited", () => {
      const state = reducer(initialState, {
        type: "composer/override",
        field: "paper_limit",
        value: "7",
      });
      expect(state.composer.overrides.paper_limit).toBe("7");
      expect(state.composer.overrides.llm_request_budget).toBeNull();
    });

    it("clears topic and overrides after a run but keeps the chosen mode", () => {
      let state = reducer(initialState, { type: "composer/mode", mode: "demo" });
      state = reducer(state, { type: "composer/topic", topic: "My topic" });
      state = reducer(state, {
        type: "composer/override",
        field: "llm_request_budget",
        value: "40",
      });
      state = reducer(state, { type: "composer/allow-budget-override", value: true });

      const reset = reducer(state, { type: "composer/reset" });
      expect(reset.composer.mode).toBe("demo");
      expect(reset.composer.topic).toBe("");
      expect(reset.composer.overrides.llm_request_budget).toBeNull();
      expect(reset.composer.allowBudgetOverride).toBe(false);
    });
  });
});
