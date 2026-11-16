import { describe, expect, it } from "vitest";
import {
  answerEvidence,
  collectCitations,
  evidenceFrom,
  normaliseLabel,
  parseCitations,
  safeHttpUrl,
} from "./citations.js";

describe("citation labels", () => {
  it("normalises both recorded shapes and rejects other brackets", () => {
    expect(normaliseLabel("[P1]")).toBe("P1");
    expect(normaliseLabel(" c12 ")).toBe("C12");
    expect(normaliseLabel("[9]")).toBe("");
    expect(normaliseLabel("P")).toBe("");
    expect(normaliseLabel(null)).toBe("");
  });

  it("splits prose into text and citation groups without losing words", () => {
    const segments = parseCitations("A [P2] uses [C3] and [P2, C4]. [not a cite] Done.");
    expect(segments.map((segment) => segment.type)).toEqual([
      "text",
      "cite",
      "text",
      "cite",
      "text",
      "cite",
      "text",
    ]);
    expect(segments.filter((segment) => segment.type === "cite").map((s) => s.labels)).toEqual([
      ["P2"],
      ["C3"],
      ["P2", "C4"],
    ]);
    expect(segments.map((segment) => segment.text || "").join("")).toContain("[not a cite]");
  });

  it("lists distinct labels in first-appearance order", () => {
    expect(collectCitations("[P2] [C1] [P2, C4] [P1]")).toEqual(["P2", "C1", "C4", "P1"]);
  });
});

describe("evidence resolution", () => {
  it("resolves FODS evidence_selected papers", () => {
    const cards = evidenceFrom([
      {
        kind: "evidence_selected",
        payload: {
          evidence: [
            {
              citation: "P1",
              paper: {
                title: "Graph Transformers",
                year: 2021,
                authors: ["A. Author"],
                url: "https://example.org/paper",
              },
            },
          ],
        },
      },
    ]);
    expect(cards).toEqual([
      expect.objectContaining({
        citation: "P1",
        kind: "paper",
        title: "Graph Transformers",
        year: 2021,
        url: "https://example.org/paper",
      }),
    ]);
  });

  it("resolves RLA concept evidence and old traverse-only logs", () => {
    const newLog = evidenceFrom([
      {
        kind: "research_answer",
        payload: {
          evidence: [{ citation: "C3", concept: { name: "Machine learning", year: 2024 } }],
        },
      },
    ]);
    expect(newLog[0]).toMatchObject({ citation: "C3", kind: "concept", title: "Machine learning" });

    const oldLog = evidenceFrom([
      {
        kind: "research_progress",
        payload: {
          phase: "traverse",
          stage_payload: {
            nodes: [
              { label: "P1", type: "Paper", name: "A paper", year: 2019 },
              { label: "C1", type: "Concept", name: "A concept", year: 2024, extra: {} },
            ],
          },
        },
      },
    ]);
    expect(oldLog.map((card) => card.citation)).toEqual(["P1", "C1"]);
    expect(oldLog[1]).toMatchObject({ kind: "concept", title: "A concept" });
  });

  it("never invents details for a cited label the run did not record", () => {
    const cards = answerEvidence({ text: "Holds [P1]. Also [C9]." }, []);
    expect(cards.map((card) => card.citation)).toEqual(["P1", "C9"]);
    expect(cards[0]).toMatchObject({ missing: true, kind: "paper" });
    expect(cards[1]).toMatchObject({ missing: true, kind: "concept" });
    expect(cards[0].title).toContain("No recorded evidence");
  });

  it("sorts papers before concepts and keeps numeric order beyond P9", () => {
    const cards = answerEvidence(
      { text: "[P10] [P2] [C9] [C1] [P11]" },
      [],
    );
    expect(cards.map((card) => card.citation)).toEqual(["P2", "P10", "P11", "C1", "C9"]);
  });

  it("only allows http(s) source links", () => {
    expect(safeHttpUrl("https://example.org/x")).toBe("https://example.org/x");
    expect(safeHttpUrl("http://example.org/x")).toBe("http://example.org/x");
    expect(safeHttpUrl("javascript:alert(1)")).toBe("");
    expect(safeHttpUrl("data:text/html,<script>")).toBe("");
    expect(safeHttpUrl("  ")).toBe("");
  });
});
