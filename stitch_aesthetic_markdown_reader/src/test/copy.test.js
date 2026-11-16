import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** The UI must not promise more than the record can show. Copy is part of the
 *  product: these words are claims about verification, so they are banned from
 *  every user-facing source file. Test files are excluded because this test
 *  necessarily contains the banned patterns. */

const SRC = resolve(process.cwd(), "src");
const FORBIDDEN =
  /\b(?:prove|proves|proved|proven|proof|proofs|verify|verifies|verified|accurate|accuracy|guarantee|guarantees|guaranteed)\b/i;

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!/\.(?:js|jsx)$/.test(entry.name)) return [];
    if (/\.test\.(?:js|jsx)$/.test(entry.name)) return [];
    return [path];
  });
}

describe("UI copy", () => {
  it("never claims verification, proof or accuracy", () => {
    const offenders = [];
    for (const path of sourceFiles(SRC)) {
      const text = readFileSync(path, "utf8");
      const match = text.match(FORBIDDEN);
      if (match) offenders.push(`${path}: ${match[0]}`);
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  it("asks a neutral question on the empty thread", () => {
    const empty = readFileSync(join(SRC, "thread", "EmptyThread.jsx"), "utf8");
    expect(empty).toContain("What should we investigate?");
    expect(empty).toContain("reads from the events a run records");
    expect(empty).not.toMatch(/the record can prove/i);
  });
});
