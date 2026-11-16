import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { collectCitations } from "./citations.js";
import { answerFrom } from "./events.js";

/** Golden recorded logs, not fixtures invented for the test.
 *
 *  `efee736eb669` (RLA) is the audit's evidence that real answers cite `[C3]`;
 *  its `[P2, C4]` group also proves the chip parser must handle comma groups.
 *  `17ee03228c0b` (FODS demo) keeps its evidence on `evidence_selected`. */

function events(name) {
  return readFileSync(
    resolve(process.cwd(), "..", "tests", "fixtures", "fods_logs", `${name}.jsonl`),
    "utf8",
  )
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

describe("recorded answers resolve every citation", () => {
  it("resolves RLA [P#] and [C#] labels, including a comma group", () => {
    const answer = answerFrom(events("efee736eb669"));
    expect(answer).toBeTruthy();

    const labels = collectCitations(answer.text);
    expect(labels).toContain("C3");
    expect(labels).toContain("C4");

    const resolved = new Set(answer.evidence.map((card) => card.citation));
    for (const label of labels) {
      expect(resolved, `[${label}] must resolve to a card`).toContain(label);
    }
    expect(answer.evidence.find((card) => card.citation === "C3")).toMatchObject({
      kind: "concept",
      missing: false,
    });
    expect(answer.evidence.every((card) => card.missing)).toBe(false);
  });

  it("resolves FODS [P#] labels from evidence_selected", () => {
    const answer = answerFrom(events("17ee03228c0b"));
    expect(answer).toBeTruthy();

    const labels = collectCitations(answer.text);
    expect(labels.length).toBeGreaterThan(0);
    const resolved = new Set(answer.evidence.map((card) => card.citation));
    for (const label of labels) expect(resolved).toContain(label);
    expect(answer.evidence.every((card) => card.kind === "paper")).toBe(true);
  });
});
