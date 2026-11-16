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
  function card(citation, overrides = {}) {
    return {
      citation,
      kind: citation.startsWith("C") ? "concept" : "paper",
      missing: false,
      title: citation.startsWith("C") ? `Concept ${citation}` : `Paper ${citation}`,
      year: 2024,
      authors: [],
      venue: "",
      abstract: "",
      doi: "",
      url: "",
      ...overrides,
    };
  }

  function answer(overrides = {}) {
    return {
      seq: 4,
      text: "The graph holds [P1] and learns [C3].",
      questionType: "factual",
      citations: ["P1", "C3"],
      evidence: [card("P1"), card("C3")],
      stripped: [],
      ...overrides,
    };
  }

  it("renders the recorded answer, chips and evidence without injecting HTML", () => {
    const scrolled = [];
    Element.prototype.scrollIntoView = vi.fn(function scroll() {
      scrolled.push(this);
    });
    try {
      render(
        <Turn
          turn={makeTurn({
            answer: answer({
              stripped: ["[P9]"],
              evidence: [
                card("P1", { title: "<script>alert(1)</script>" }),
                card("C3"),
              ],
            }),
          })}
          onOpenTrace={() => {}}
        />,
      );

      const region = screen.getByRole("region", { name: "Answer" });
      expect(region).toBeTruthy();
      expect(region.querySelector("script")).toBeNull();
      expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy();
      expect(screen.getByText(/could not be matched to the evidence graph/)).toBeTruthy();
      expect(screen.getByRole("list", { name: "Citations in this answer" })).toBeTruthy();

      fireEvent.click(
        screen.getAllByRole("button", { name: /Select evidence for \[P1\]/i })[0],
      );
      const evidenceCard = screen.getByRole("button", {
        name: /Evidence \[P1\]: <script>alert\(1\)<\/script>/i,
      });
      expect(evidenceCard.getAttribute("data-active")).toBe("true");
      expect(evidenceCard.getAttribute("aria-pressed")).toBe("true");
      expect(scrolled).toContain(evidenceCard);
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
        block: "nearest",
        behavior: "smooth",
      });
    } finally {
      delete Element.prototype.scrollIntoView;
    }
  });

  it("highlights the chips when an evidence card is hovered", () => {
    render(<Turn turn={makeTurn({ answer: answer() })} onOpenTrace={() => {}} />);
    const evidenceCard = screen.getByRole("button", {
      name: /Evidence \[C3\]: Concept C3/i,
    });
    fireEvent.mouseEnter(evidenceCard);
    for (const chip of document.querySelectorAll('.cite-chip[data-citation="C3"]')) {
      expect(chip.getAttribute("data-active")).toBe("true");
    }
    fireEvent.mouseLeave(evidenceCard);
    for (const chip of document.querySelectorAll('.cite-chip[data-citation="C3"]')) {
      expect(chip.getAttribute("data-active")).toBeNull();
    }
  });

  it("scrolls to the last evidence card, not just the first ten", () => {
    const scrolled = [];
    Element.prototype.scrollIntoView = vi.fn(function scroll() {
      scrolled.push(this);
    });
    try {
      const cards = Array.from({ length: 14 }, (_, index) => card(`P${index + 1}`));
      render(
        <Turn
          turn={makeTurn({
            answer: answer({
              text: "Long answer [P14].",
              citations: ["P14"],
              evidence: cards,
            }),
          })}
          onOpenTrace={() => {}}
        />,
      );

      expect(document.querySelectorAll(".evidence-item")).toHaveLength(14);
      fireEvent.click(
        screen.getAllByRole("button", { name: /Select evidence for \[P14\]/i })[0],
      );
      const last = document.querySelector('.evidence-item[data-citation="P14"]');
      expect(last.getAttribute("data-active")).toBe("true");
      expect(scrolled).toContain(last);
    } finally {
      delete Element.prototype.scrollIntoView;
    }
  });

  it("selects a concept card with the keyboard (native button)", () => {
    render(<Turn turn={makeTurn({ answer: answer() })} onOpenTrace={() => {}} />);
    const evidenceCard = screen.getByRole("button", { name: /Evidence \[C3\]/i });
    expect(evidenceCard.tagName).toBe("BUTTON");
    evidenceCard.focus();
    fireEvent.click(evidenceCard);
    expect(evidenceCard.getAttribute("aria-pressed")).toBe("true");
  });

  it("states unresolved citations instead of calling them verified", () => {
    render(
      <Turn
        turn={makeTurn({
          answer: answer({
            text: "Holds [P1] [P9].",
            evidence: [card("P1"), card("P9", { missing: true })],
          }),
        })}
        onOpenTrace={() => {}}
      />,
    );
    expect(screen.getByText(/no recorded evidence card/)).toBeTruthy();
    expect(screen.getByText(/marked as not recorded/)).toBeTruthy();
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
