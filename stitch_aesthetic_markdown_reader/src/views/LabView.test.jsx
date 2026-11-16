import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialState } from "../store/reducer.js";
import LabView from "./LabView.jsx";

/** The three committed golden logs: the RLA run from UI-07, the 8-task demo,
 *  and the 26-task live run. The view tests use the first two. */
function events(name) {
  return readFileSync(
    resolve(process.cwd(), "..", "tests", "fixtures", "fods_logs", `${name}.jsonl`),
    "utf8",
  )
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function demoRun(overrides = {}) {
  return {
    id: "17ee03228c0b",
    mode: "simulate",
    kind: "simulate",
    status: "completed",
    statusReason: "completed",
    stream: "idle",
    historical: false,
    pipeline: "fods-scheduler",
    topic: "QA demo: GNN reasoning",
    events: events("17ee03228c0b"),
    ...overrides,
  };
}

function rlaRun(overrides = {}) {
  return {
    id: "efee736eb669",
    mode: "live",
    kind: "live",
    status: "completed",
    statusReason: "completed",
    stream: "idle",
    historical: true,
    pipeline: "",
    topic: "AI methods for autonomous scientific discovery",
    events: events("efee736eb669"),
    ...overrides,
  };
}

function renderLab(run, state = initialState) {
  return render(<LabView state={state} run={run} onFocusComposer={() => {}} />);
}

describe("LabView: no run", () => {
  it("explains what the Lab needs instead of rendering an empty frame", () => {
    renderLab(null);
    expect(screen.getByRole("heading", { name: "No run to show" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /start a run/i })).toBeTruthy();
  });

  it("does not invent structure for a log with neither a plan nor phases", () => {
    renderLab(
      demoRun({
        pipeline: "",
        events: [{ seq: 1, kind: "run_started", payload: { mode: "live" } }],
      }),
    );
    expect(screen.getByRole("heading", { name: "No recorded structure" })).toBeTruthy();
  });
});

describe("LabView: deterministic demo", () => {
  it("renders the plan, its 8 nodes and 8 edges from the recorded levels", () => {
    const { container } = renderLab(demoRun());
    expect(screen.getByRole("heading", { name: "Recorded structure" })).toBeTruthy();
    expect(screen.getByText("Dependency plan")).toBeTruthy();
    expect(
      screen.getByText(/8 tasks · 8 completed · 6 levels · Completed/),
    ).toBeTruthy();
    expect(container.querySelectorAll(".lab-node")).toHaveLength(8);
    expect(container.querySelectorAll(".lab-edge")).toHaveLength(8);
    expect(screen.getByText("114 of 114 events · 100%")).toBeTruthy();
    expect(screen.getByText("REPLAY")).toBeTruthy();
  });

  it("opens the recorded queue, worker slots and the last non-empty snapshot", () => {
    renderLab(demoRun());
    fireEvent.click(screen.getByRole("tab", { name: "Queue" }));

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { name: "Ready queue" })).toBeTruthy();
    expect(within(panel).getByText("FIFO")).toBeTruthy();
    expect(within(panel).getByText("Queue empty at the playhead.")).toBeTruthy();
    expect(within(panel).getByText(/Last recorded non-empty snapshot at event 102/)).toBeTruthy();
    expect(within(panel).getByText(/Priority not recorded in FIFO mode/)).toBeTruthy();
    expect(within(panel).getByRole("heading", { name: "Worker pool" })).toBeTruthy();
    expect(within(panel).getByText(/Slot order is display order/)).toBeTruthy();
    expect(within(panel).getAllByText(/^slot \d$/)).toHaveLength(3);
    expect(within(panel).getByText("8")).toBeTruthy();
  });

  it("shows each task's recorded stack, top first", () => {
    const { container } = renderLab(demoRun());
    fireEvent.click(screen.getByRole("tab", { name: "Stacks" }));

    expect(screen.getByRole("heading", { name: "Run stack" })).toBeTruthy();
    expect(container.querySelectorAll(".lab-stack-card")).toHaveLength(8);
    expect(container.querySelectorAll(".lab-stack-card .lab-stack-top")).toHaveLength(8);
    expect(screen.getAllByText("TOP")).toHaveLength(9);
    expect(screen.getByText(/frames are not replayed from push\/pop counts/)).toBeTruthy();
  });

  it("uses the accessible state table as the alternative to the SVG", () => {
    const { container } = renderLab(demoRun());
    fireEvent.click(screen.getByRole("tab", { name: "State" }));

    const rows = container.querySelectorAll(".lab-state-table tbody tr");
    expect(rows).toHaveLength(8);
    expect(screen.getAllByText("Completed")).toHaveLength(8);
    expect(screen.getByText(/never filled in with zero/)).toBeTruthy();
  });

  it("selects a task from the graph and states the recorded facts", () => {
    const { container } = renderLab(demoRun());
    fireEvent.click(container.querySelector(".lab-node"));

    const facts = within(container.querySelector(".lab-task-facts"));
    expect(screen.getByRole("heading", { name: "Selected task" })).toBeTruthy();
    expect(facts.getAllByText("search_semantic_scholar")).toHaveLength(2);
    expect(facts.getByText("source task")).toBeTruthy();
    expect(facts.getByText("1 of 2")).toBeTruthy();
  });

  it("rebuilds the state at the playhead instead of showing the finished run", () => {
    renderLab(demoRun());
    const scrub = screen.getByLabelText("Playback position");
    fireEvent.change(scrub, { target: { value: "30" } });

    expect(screen.getByText("30 of 114 events · 26%")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "State" }));
    expect(screen.getAllByText("Running")).toHaveLength(3);
    expect(screen.getAllByText("Planned")).toHaveLength(5);
  });

  it("steps one event at a time and shows a caption for the transition", () => {
    renderLab(demoRun());
    expect(screen.getByText("run finished: Completed")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Step back one event" }));
    expect(screen.getByText("113 of 114 events · 99%")).toBeTruthy();
    expect(screen.queryByText("run finished: Completed")).toBeNull();
    expect(screen.getByText("Concept caption")).toBeTruthy();
  });

  it("dismisses a caption for the session", () => {
    renderLab(demoRun());
    expect(screen.getByText("run finished: Completed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss caption" }));
    expect(screen.queryByText("run finished: Completed")).toBeNull();
    expect(sessionStorage.getItem("fods.lab.captions.dismissed")).toContain("17ee03228c0b:114");
  });

  it("moves between tabs with the arrow keys", () => {
    renderLab(demoRun());
    const graph = screen.getByRole("tab", { name: "Graph" });
    graph.focus();
    fireEvent.keyDown(graph, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Queue" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { name: "Ready queue" })).toBeTruthy();
  });

  it("shows no plan at the start of the run, without filling it in", () => {
    renderLab(demoRun());
    fireEvent.change(screen.getByLabelText("Playback position"), { target: { value: "0" } });
    expect(screen.getByText("No task plan has been recorded at this point in the run.")).toBeTruthy();
    expect(screen.getByText(/0 tasks · 0 completed/)).toBeTruthy();
  });

  it("renders a rejected cyclic plan as rejected, never as executed", () => {
    renderLab(
      demoRun({
        events: [
          {
            seq: 1,
            kind: "plan_received",
            payload: {
              tasks: [
                { id: "a", tool: "merge_and_save_context", depends_on: ["b"] },
                { id: "b", tool: "write_cited_brief", depends_on: ["a"] },
              ],
            },
          },
          {
            seq: 2,
            kind: "plan_rejected",
            message: "plan rejected: dependency cycle a -> b -> a",
            payload: {
              tasks: [
                { id: "a", tool: "merge_and_save_context", depends_on: ["b"] },
                { id: "b", tool: "write_cited_brief", depends_on: ["a"] },
              ],
            },
          },
        ],
      }),
    );
    expect(screen.getByText("Cycle detected by replay analysis of the recorded plan")).toBeTruthy();
    expect(screen.getByText(/no task executed/)).toBeTruthy();
    expect(screen.getByText("a → b")).toBeTruthy();
    expect(screen.getByText("Plan rejected")).toBeTruthy();
  });
});

describe("LabView: RLA phase rail", () => {
  it("labels the pipeline and shows every recorded phase with its counts", () => {
    renderLab(rlaRun());
    expect(screen.getByText("RLA pipeline phases")).toBeTruthy();
    expect(screen.getByText(/sequential · not a task DAG/)).toBeTruthy();
    expect(screen.getByText("Phase 2 stub")).toBeTruthy();
    expect(screen.getAllByText("Not implemented yet.")).toHaveLength(1);
    expect(screen.getAllByText(/cache hits 75/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("timing not recorded").length).toBe(10);
    expect(screen.getByText(/predates the declared stage list/)).toBeTruthy();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
  });

  it("uses none of the scheduler vocabulary on the RLA screen", () => {
    const { container } = renderLab(rlaRun());
    expect(container.textContent).not.toMatch(
      /scheduler|queue|worker|topological|parallel/i,
    );
  });

  it("never renders an absent stage as zero", () => {
    const { container } = renderLab(rlaRun());
    expect(container.textContent).not.toContain("counts recorded 0");
    expect(screen.getAllByText("Not implemented yet.")).toHaveLength(1);
  });
});
