import { describe, expect, it } from "vitest";
import {
  STATUS_LABEL,
  describeEvent,
  finishReason,
  modeLabel,
  phaseOf,
  statusFromFinish,
  statusLabel,
  statusTone,
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
    expect(phaseOf({ kind: "citation_validation" })).toBe("validation");
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
