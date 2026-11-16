import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LabView from "./LabView.jsx";
import TraceView from "./TraceView.jsx";
import Turn from "../thread/Turn.jsx";
import { initialState } from "../store/reducer.js";

const run = {
  id: "0123456789ab",
  mode: "simulate",
  status: "completed",
  statusReason: "",
  stream: "idle",
  events: [
    {
      seq: 1,
      kind: "plan_validated",
      payload: { levels: [["search_alpha", "search_beta"], ["join_context"]], tasks: [] },
    },
    { seq: 2, kind: "task_started", message: "search_alpha started", payload: {} },
  ],
};

describe("LabView", () => {
  it("renders the plan levels the runtime recorded", () => {
    render(<LabView state={initialState} run={run} onFocusComposer={() => {}} />);
    expect(screen.getByText("Level 0")).toBeTruthy();
    expect(screen.getByText("search_alpha")).toBeTruthy();
    expect(screen.getByText("2 tasks")).toBeTruthy();
    expect(screen.getByText(/3 tasks · 2 levels · Completed/)).toBeTruthy();
  });

  it("does not invent a plan for a run that never recorded one", () => {
    render(
      <LabView
        state={initialState}
        run={{ ...run, events: [{ seq: 1, kind: "run_started", payload: {} }] }}
        onFocusComposer={() => {}}
      />,
    );
    expect(screen.getByText(/has not recorded a plan yet/)).toBeTruthy();
  });
});

describe("TraceView", () => {
  it("renders recorded events oldest first with kind and phase", () => {
    render(<TraceView run={run} onFocusComposer={() => {}} />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // header + two events
    expect(within(rows[1]).getByText("plan_validated")).toBeTruthy();
    expect(within(rows[2]).getByText("search_alpha started")).toBeTruthy();
  });

  it("offers a start action when no run is open", () => {
    const onFocus = vi.fn();
    render(<TraceView run={null} onFocusComposer={onFocus} />);
    fireEvent.click(screen.getByRole("button", { name: /start a run/i }));
    expect(onFocus).toHaveBeenCalledTimes(1);
  });
});

describe("Turn", () => {
  const turn = {
    id: "0123456789ab",
    question: "Why does the scheduler exist?",
    engineLabel: "FODS scheduler",
    mode: "simulate",
    status: "failed",
    statusReason: "",
    stream: "error",
    eventCount: 2,
    recent: [
      { seq: 1, text: "run started" },
      { seq: 2, text: "task failed" },
    ],
    finished: true,
  };

  it("shows the real status, the recent recorded lines and the disconnect honestly", () => {
    const onOpenTrace = vi.fn();
    render(<Turn turn={turn} onOpenTrace={onOpenTrace} />);
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("task failed")).toBeTruthy();
    expect(screen.getByText(/event stream disconnected/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /open execution trace/i }));
    expect(onOpenTrace).toHaveBeenCalledTimes(1);
  });

  it("does not call an unfinished run complete", () => {
    render(
      <Turn
        turn={{ ...turn, status: "starting", stream: "connecting", eventCount: 0, finished: false }}
        onOpenTrace={() => {}}
      />,
    );
    expect(screen.getByText("Starting")).toBeTruthy();
    expect(screen.getByText(/waiting for the first recorded event/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /open execution trace/i })).toBeNull();
  });
});
