import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Turn, { WORKING_THROTTLE_MS } from "./Turn.jsx";

function makeTurn(overrides = {}) {
  return {
    id: "0123456789ab",
    question: "Why does the scheduler keep going?",
    engineLabel: "FODS scheduler",
    mode: "simulate",
    status: "running",
    statusTone: "live",
    statusReason: "",
    stream: "live",
    eventCount: 3,
    working: {
      lines: [
        { seq: 1, phase: "plan", text: "plan validated" },
        { seq: 2, phase: "source", text: "3 sources searched" },
      ],
      more: 0,
    },
    answer: null,
    workedFor: null,
    finished: false,
    stopping: false,
    historical: false,
    warnings: 0,
    sourceRunId: "",
    ...overrides,
  };
}

function lines(count) {
  return Array.from({ length: count }, (_, index) => ({
    seq: index + 1,
    phase: index % 2 === 0 ? "source" : "evidence",
    text: `step ${index + 1}`,
  }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Turn working lines", () => {
  it("shows the phase-tagged lines in one polite live region", () => {
    render(<Turn turn={makeTurn()} onOpenTrace={() => {}} />);
    const region = document.querySelector(".working");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(screen.getByText("plan validated")).toBeTruthy();
    expect(screen.getAllByText("Source").length).toBeGreaterThan(0);
  });

  it("caps at six lines and states how many are hidden", () => {
    render(
      <Turn
        turn={makeTurn({ working: { lines: lines(6), more: 3 }, eventCount: 9 })}
        onOpenTrace={() => {}}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(screen.getByText("and 3 more")).toBeTruthy();
  });

  it("throttles updates to at most one per 500 ms", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Turn turn={makeTurn()} onOpenTrace={() => {}} />);
    expect(screen.queryByText("step 3")).toBeNull();

    rerender(
      <Turn
        turn={makeTurn({ working: { lines: lines(3), more: 0 }, eventCount: 6 })}
        onOpenTrace={() => {}}
      />,
    );
    // The DOM still shows the snapshot from before the throttle window.
    expect(screen.queryByText("step 3")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(WORKING_THROTTLE_MS);
    });
    expect(screen.getByText("step 3")).toBeTruthy();
  });
});

describe("Turn collapse", () => {
  it("replaces the list with the recorded duration and step count", () => {
    const onOpenTrace = vi.fn();
    render(
      <Turn
        turn={makeTurn({
          finished: true,
          stream: "idle",
          status: "completed",
          workedFor: { duration: "2m 14s", steps: 9 },
        })}
        onOpenTrace={onOpenTrace}
      />,
    );
    expect(screen.queryByRole("list")).toBeNull();
    const button = screen.getByRole("button", {
      name: /Worked for 2m 14s · 9 steps — open execution trace/i,
    });
    expect(button.textContent).toContain("Worked for 2m 14s · 9 steps");
    fireEvent.click(button);
    expect(onOpenTrace).toHaveBeenCalledTimes(1);
  });

  it("states an unrecorded duration rather than inventing one", () => {
    render(
      <Turn
        turn={makeTurn({
          finished: true,
          stream: "idle",
          status: "completed",
          workedFor: { duration: "", steps: 4 },
        })}
        onOpenTrace={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /Worked for an unrecorded duration · 4 steps — open execution trace/i,
      }),
    ).toBeTruthy();
  });
});

describe("Turn answer and state", () => {
  it("renders the recorded answer and the stripped-citation notice", () => {
    render(
      <Turn
        turn={makeTurn({
          answer: {
            seq: 4,
            text: "The graph holds. [P1]",
            questionType: "factual",
            citations: ["[P1]"],
            evidence: [],
            stripped: ["[P9]"],
          },
        })}
        onOpenTrace={() => {}}
      />,
    );
    expect(screen.getByRole("region", { name: "Answer" })).toBeTruthy();
    expect(screen.getByText("The graph holds. [P1]")).toBeTruthy();
    expect(screen.getByText(/could not be matched to the evidence graph/)).toBeTruthy();
  });

  it("shows a stopping chip while a stop is pending", () => {
    render(<Turn turn={makeTurn({ stopping: true })} onOpenTrace={() => {}} />);
    expect(screen.getByText("Stopping")).toBeTruthy();
  });

  it("shows a skipped-line note when the log had corrupt lines", () => {
    render(<Turn turn={makeTurn({ warnings: 2 })} onOpenTrace={() => {}} />);
    expect(screen.getByText(/2 unreadable log lines were skipped/)).toBeTruthy();
  });
});
