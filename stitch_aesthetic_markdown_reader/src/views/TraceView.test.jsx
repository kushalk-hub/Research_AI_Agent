import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TraceView from "./TraceView.jsx";

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
  return {
    id: name,
    mode: "simulate",
    status: "completed",
    statusReason: "",
    stream: "idle",
    events: events(name),
    ...overrides,
  };
}

const smallRun = {
  id: "0123456789ab",
  mode: "simulate",
  status: "completed",
  statusReason: "",
  stream: "idle",
  events: [
    {
      seq: 1,
      kind: "plan_validated",
      timestamp: 100,
      payload: { levels: [["search_alpha"]], tasks: [{}] },
    },
    {
      seq: 2,
      kind: "task_started",
      message: "search_alpha started",
      timestamp: 101,
      payload: { task_id: "t1", tool: "search_arxiv" },
    },
    {
      seq: 3,
      kind: "tool_call_started",
      message: "search_arxiv started",
      timestamp: 102,
      payload: { task_id: "t1", tool: "search_arxiv" },
    },
  ],
};

function region() {
  return screen.getByRole("region", { name: /recorded events/i });
}

describe("TraceView table and filters", () => {
  it("shows the summary bar from the record, with an honest duration", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    expect(screen.getByText("3 of 3 events")).toBeTruthy();
    expect(screen.getByText(/duration not recorded/)).toBeTruthy();
    expect(screen.getAllByLabelText("duration not recorded")).toHaveLength(3);
  });

  it("filters by class and restores the list when the chip is pressed again", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    const taskChip = screen.getByRole("button", { name: "task" });
    fireEvent.click(taskChip);
    expect(taskChip.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("1 of 3 events")).toBeTruthy();
    expect(screen.getByText("search_alpha started")).toBeTruthy();
    expect(screen.queryByText("search_arxiv started")).toBeNull();

    fireEvent.click(taskChip);
    expect(screen.getByText("3 of 3 events")).toBeTruthy();
  });

  it("shows a clear empty state when nothing matches", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    fireEvent.change(screen.getByLabelText("Filter events"), {
      target: { value: "no-such-event" },
    });
    expect(screen.getByText(/No events match these filters/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("3 of 3 events")).toBeTruthy();
  });

  it("shows only failures when the failures toggle is on", () => {
    const failed = {
      ...smallRun,
      events: [
        ...smallRun.events,
        { seq: 4, kind: "task_failed", message: "search failed", timestamp: 103, payload: {} },
      ],
    };
    render(<TraceView run={failed} onFocusComposer={() => {}} />);
    fireEvent.click(screen.getByLabelText("Failures only"));
    expect(screen.getByText("1 of 4 events")).toBeTruthy();
    expect(screen.getByText("search failed")).toBeTruthy();
    expect(screen.getAllByText("Failed").length).toBeGreaterThanOrEqual(2); // chip + row
  });

  it("filters by a recorded status chip", () => {
    const mixed = {
      ...smallRun,
      events: [
        ...smallRun.events,
        { seq: 4, kind: "task_retry", message: "retrying search", timestamp: 103, payload: {} },
      ],
    };
    render(<TraceView run={mixed} onFocusComposer={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Warn" }));
    expect(screen.getByText("1 of 4 events")).toBeTruthy();
    expect(screen.getByText("retrying search")).toBeTruthy();
  });

  it("collapses and expands a phase group", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    fireEvent.click(screen.getByLabelText("Group by phase"));

    const toggles = document.querySelectorAll(".trace-group-toggle");
    expect(toggles).toHaveLength(2); // plan, acquire
    const acquire = [...toggles].find((button) => button.textContent.includes("acquire"));
    expect(acquire.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(acquire);
    expect(acquire.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText("plan validated")).toBeTruthy();
    expect(screen.queryByText("search_alpha started")).toBeNull();
    fireEvent.click(acquire);
    expect(screen.getByText("search_alpha started")).toBeTruthy();
  });
});

describe("TraceView keyboard and detail", () => {
  it("moves the selection with ↑/↓ and Home/End", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    const list = region();

    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(screen.getByRole("heading", { name: "Event #1" })).toBeTruthy();
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(screen.getByRole("heading", { name: "Event #2" })).toBeTruthy();
    fireEvent.keyDown(list, { key: "End" });
    expect(screen.getByRole("heading", { name: "Event #3" })).toBeTruthy();
    fireEvent.keyDown(list, { key: "Home" });
    expect(screen.getByRole("heading", { name: "Event #1" })).toBeTruthy();
    fireEvent.keyDown(list, { key: "ArrowUp" });
    expect(screen.getByRole("heading", { name: "Event #1" })).toBeTruthy();
  });

  it("opens all four detail tabs and never invents a duration", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Select event 1/ }));
    expect(screen.getAllByText("plan validated").length).toBeGreaterThanOrEqual(2); // row + detail
    expect(screen.getAllByText("not recorded for this event").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: "Payload" }));
    expect(screen.getByText(/Payload JSON/)).toBeTruthy();
    expect(screen.getByText(/levels/)).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Timing" }));
    expect(screen.getByText("Start offset")).toBeTruthy();
    expect(screen.getByText(/no adjacent timestamps recorded/)).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Related" }));
    expect(screen.getByText(/No related events were recorded/)).toBeTruthy();
  });

  it("jumps to a related event and clears the filters hiding it", () => {
    render(<TraceView run={smallRun} onFocusComposer={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "task" }));
    fireEvent.click(screen.getByRole("button", { name: /Select event 2/ }));

    fireEvent.click(screen.getByRole("tab", { name: "Related" }));
    const related = document.querySelectorAll(".trace-related-link");
    expect(related.length).toBeGreaterThan(0);
    fireEvent.click(related[0]);

    expect(screen.getByRole("heading", { name: "Event #3" })).toBeTruthy();
    expect(screen.getByLabelText("Filter events").value).toBe("");
    expect(screen.getByRole("button", { name: "task" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });
});

describe("TraceView virtualisation", () => {
  it("renders a window, not all 381 recorded events", () => {
    const { container } = render(
      <TraceView run={runOf("Q01-deep", { status: "completed" })} onFocusComposer={() => {}} />,
    );
    expect(screen.getByText("381 of 381 events")).toBeTruthy();
    const rendered = container.querySelectorAll(".trace-row");
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThanOrEqual(60);
    expect(container.querySelectorAll(".trace-spacer")).toHaveLength(2);
  });

  it("renders an RLA run without a duration and with real phases", () => {
    render(<TraceView run={runOf("efee736eb669")} onFocusComposer={() => {}} />);
    expect(screen.getByText(/duration not recorded/)).toBeTruthy();
    expect(document.querySelectorAll('.trace-row').length).toBeLessThanOrEqual(60);
    const phases = new Set(
      [...document.querySelectorAll(".trace-row td:nth-child(2)")].map((cell) => cell.textContent),
    );
    expect(phases.size).toBeGreaterThan(1);
    expect(phases.has("research_progress")).toBe(false);
  });
});
