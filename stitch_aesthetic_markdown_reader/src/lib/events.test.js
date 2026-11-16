import { describe, expect, it } from "vitest";
import {
  STATUS_LABEL,
  answerFrom,
  countPhases,
  describeEvent,
  finishReason,
  modeLabel,
  phaseLabel,
  phaseOf,
  statusFromFinish,
  statusLabel,
  statusTone,
  workedFor,
  workingLines,
} from "./events.js";
import { formatDuration, redactText, relativeTime, shorten } from "./format.js";

describe("run status", () => {
  it("maps only the termination reasons the runtime records", () => {
    expect(statusFromFinish({ succeeded: true })).toBe("completed");
    expect(statusFromFinish({ termination_reason: "completed_with_partial_sources" })).toBe(
      "partial",
    );
    expect(statusFromFinish({ termination_reason: "cancelled" })).toBe("cancelled");
    expect(statusFromFinish({ succeeded: false })).toBe("failed");
  });

  it("never advertises an abstained status", () => {
    expect(STATUS_LABEL).not.toHaveProperty("abstained");
    expect(statusLabel("abstained")).toBe("Unknown");
    expect(statusTone("abstained")).toBe("muted");
    expect(statusLabel("stopping")).toBe("Stopping");
    expect(statusTone("stopping")).toBe("warn");
  });

  it("labels replay and simulation honestly", () => {
    expect(modeLabel("simulate")).toBe("Deterministic demo");
    expect(modeLabel("replay")).toBe("Replay");
    expect(modeLabel("live")).toBe("Live");
  });
});

describe("describeEvent", () => {
  it("prefers the backend summary and keeps it to ninety characters", () => {
    const long = "x".repeat(200);
    const line = describeEvent({ kind: "task_started", summary: long });
    expect(line).toHaveLength(90);
    expect(line.endsWith("…")).toBe(true);
  });

  it("falls back to the recorded message, then the kind", () => {
    expect(describeEvent({ kind: "queue_updated", message: "enqueued search_alpha" })).toBe(
      "enqueued search_alpha",
    );
    expect(describeEvent({ kind: "task_started" })).toBe("task started");
  });

  it("never renders an absolute path or a secret from an old log", () => {
    const event = {
      kind: "brief_saved",
      message: "saved brief to C:\\Users\\someone\\data\\fods\\briefs\\abc.md",
    };
    const line = describeEvent(event);
    expect(line).not.toContain("Users");
    expect(line).toContain("[path]");
    expect(describeEvent({ kind: "model_call", message: "key sk-abcdef123456 rejected" })).toContain(
      "[secret]",
    );
  });

  it("does not leak raw JSON when only a payload exists", () => {
    const line = describeEvent({ kind: "stage_progress", payload: { phase: "resolving", n: 3 } });
    expect(line).toBe("resolving phase");
    expect(line).not.toContain("{");
  });
});

describe("finishReason", () => {
  it("names the reason and the unavailable sources", () => {
    expect(
      finishReason({
        termination_reason: "completed_with_partial_sources",
        unavailable_sources: ["arxiv", "dblp"],
      }),
    ).toBe("completed with partial sources · 2 sources unavailable (arxiv, dblp)");
  });

  it("is empty when the runtime recorded no reason", () => {
    expect(finishReason({ succeeded: true })).toBe("");
    expect(finishReason({ termination_reason: "completed" })).toBe("");
  });
});

describe("phaseOf", () => {
  it("uses the recorded phase before guessing from the kind", () => {
    expect(phaseOf({ kind: "task_started", payload: { phase: "write" } })).toBe("write");
    expect(phaseOf({ kind: "queue_updated" })).toBe("queue");
    expect(phaseOf({ kind: "citation_validation" })).toBe("runtime");
  });

  it("derives a FODS phase from the tool that ran, as the backend does", () => {
    expect(phaseOf({ kind: "task_started", payload: { tool: "search_arxiv" } })).toBe("acquire");
    expect(phaseOf({ kind: "tool_call_started", payload: { tool: "retrieve_evidence" } })).toBe(
      "evidence",
    );
    expect(phaseOf({ kind: "task_started" })).toBe("runtime");
  });

  it("labels known phases and humanises unknown ones", () => {
    expect(phaseLabel("search")).toBe("Search");
    expect(phaseLabel("")).toBe("Runtime");
    expect(phaseLabel("brand-new")).toBe("Brand-new");
  });
});

describe("in-thread working lines", () => {
  function lineage(count) {
    return Array.from({ length: count }, (_, index) => ({
      seq: index + 1,
      kind: "task_started",
      message: `step ${index + 1}`,
      payload: { phase: index % 2 === 0 ? "source" : "evidence" },
      timestamp: 10 + index,
    }));
  }

  it("keeps the most recent six lines and counts the rest", () => {
    const { lines, more } = workingLines(lineage(9));
    expect(lines).toHaveLength(6);
    expect(more).toBe(3);
    expect(lines[0].text).toBe("step 4");
    expect(lines[5].text).toBe("step 9");
    expect(lines[5].phase).toBe("source");
  });

  it("shows nothing for a finished run and ignores the terminal event itself", () => {
    const events = [
      ...lineage(2),
      {
        seq: 3,
        kind: "run_finished",
        message: "run completed",
        payload: { succeeded: true, termination_reason: "completed" },
        timestamp: 20,
      },
    ];
    const { lines, more } = workingLines(events);
    expect(lines.map((line) => line.text)).toEqual(["step 1", "step 2"]);
    expect(more).toBe(0);
    expect(countPhases(events)).toBe(2);
  });
});

describe("workedFor", () => {
  const finish = (payload) => ({
    seq: 9,
    kind: "run_finished",
    message: "run completed",
    payload,
    timestamp: 30,
  });

  it("uses the recorded duration and stage count", () => {
    expect(
      workedFor([finish({ succeeded: true, elapsed_ms: 134000, stages: [{}, {}, {}] })]),
    ).toEqual({ duration: "2m 14s", steps: 3 });
  });

  it("states an unrecorded duration instead of guessing one", () => {
    expect(workedFor([finish({ succeeded: true })])).toEqual({ duration: "", steps: 0 });
  });

  it("returns null while the run has no terminal record", () => {
    expect(workedFor([{ seq: 1, kind: "run_started", payload: {} }])).toBeNull();
  });
});

describe("answerFrom", () => {
  it("finds the recorded answer and keeps the citation evidence", () => {
    const answer = answerFrom([
      { seq: 1, kind: "run_started", payload: {} },
      {
        seq: 2,
        kind: "research_answer",
        message: "cited answer generated",
        payload: {
          answer: "  The graph holds. [P1]  ",
          citations: ["[P1]"],
          stripped_citations: ["[P9]"],
          question_type: "factual",
          evidence: [{ citation: "[P1]" }],
        },
      },
    ]);
    expect(answer).toMatchObject({
      seq: 2,
      text: "The graph holds. [P1]",
      questionType: "factual",
      citations: ["[P1]"],
      stripped: ["[P9]"],
    });
    // A cited label with no recorded card still resolves, honestly, to a
    // "not recorded" card instead of a dead chip.
    expect(answer.evidence).toEqual([
      expect.objectContaining({ citation: "P1", kind: "paper", missing: true }),
    ]);
  });

  it("returns null when no answer text was recorded", () => {
    expect(answerFrom([])).toBeNull();
    expect(answerFrom([{ seq: 1, kind: "research_answer", payload: { answer: "   " } }])).toBeNull();
  });
});

describe("format helpers", () => {
  it("formats durations without locale surprises", () => {
    expect(formatDuration(840)).toBe("840 ms");
    expect(formatDuration(2100)).toBe("2.1 s");
    expect(formatDuration(134000)).toBe("2m 14s");
    expect(formatDuration(null)).toBe("");
  });

  it("treats epoch seconds and milliseconds consistently", () => {
    const now = Date.UTC(2026, 10, 16, 12, 0, 0);
    expect(relativeTime(now / 1000 - 120, now)).toBe("2m ago");
    expect(relativeTime(now - 86_400_000, now)).toBe("1d ago");
  });

  it("redacts Windows paths, POSIX home paths and tokens", () => {
    expect(redactText("C:\\Users\\me\\out.md")).toBe("[path]");
    expect(redactText("/home/me/out.md")).toBe("[path]");
    expect(redactText("AIzaABCDEFGHIJKLMNOP")).toBe("[secret]");
    expect(shorten("a  b\n c", 10)).toBe("a b c");
  });
});
