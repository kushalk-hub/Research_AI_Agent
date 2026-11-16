import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  barGeometry,
  classOf,
  durationOf,
  filterRows,
  previousRow,
  relatedFor,
  severityOf,
  timestampMs,
  TRACE_ROW_HEIGHT,
  traceItems,
  traceRows,
  traceSpan,
  traceSummary,
  virtualWindow,
} from "./trace.js";

/** Golden recorded logs, not fixtures invented for the test.
 *
 *  `efee736eb669` is the audit's RLA trace (every row used to say
 *  `research_progress`); `17ee03228c0b` is the 114-event deterministic demo;
 *  `Q01-deep` is the 381-event live run, which is what virtualisation exists
 *  for. None of them carries the slice-3a fields, so every fallback is
 *  exercised for real. */
function events(name) {
  return readFileSync(
    resolve(process.cwd(), "..", "tests", "fixtures", "fods_logs", `${name}.jsonl`),
    "utf8",
  )
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

describe("trace rows from recorded logs", () => {
  it("gives every event a short non-empty summary and a real phase", () => {
    for (const name of ["efee736eb669", "17ee03228c0b", "Q01-deep"]) {
      const rows = traceRows(events(name));
      expect(rows.length).toBeGreaterThan(0);
      for (const row of rows) {
        expect(row.summary.trim(), `event #${row.seq} of ${name}`).not.toBe("");
        expect(row.summary.length, `event #${row.seq} of ${name}`).toBeLessThanOrEqual(90);
      }
      const phases = new Set(rows.map((row) => row.phase));
      expect(phases.size).toBeGreaterThan(1);
      expect([...phases]).not.toEqual(["research_progress"]);
    }
  });

  it("uses the RLA payload phase, not the kind", () => {
    const rows = traceRows(events("efee736eb669"));
    const progress = rows.filter((row) => row.kind === "research_progress");
    expect(progress.length).toBeGreaterThan(0);
    expect(progress.every((row) => row.phase !== "research_progress")).toBe(true);
    expect(new Set(progress.map((row) => row.phase)).size).toBeGreaterThanOrEqual(8);
    expect(new Set(rows.map((row) => row.phase))).toEqual(
      new Set([
        "runtime",
        "search",
        "fetch",
        "score",
        "fulltext",
        "extract",
        "resolve",
        "graph",
        "traverse",
        "answer",
        "done",
      ]),
    );
  });

  it("derives the FODS phase from the recorded tool, as the backend does", () => {
    const rows = traceRows(events("17ee03228c0b"));
    const count = (phase) => rows.filter((row) => row.phase === phase).length;
    expect(count("acquire")).toBe(12);
    expect(count("merge")).toBe(4);
    expect(count("evidence")).toBe(4);
    expect(count("answer")).toBe(4);
    expect(count("validate")).toBe(4);
    expect(count("write")).toBe(4);
    const started = rows.find(
      (row) => row.kind === "task_started" && row.event.payload.tool === "search_arxiv",
    );
    expect(started.phase).toBe("acquire");
    expect(count("task")).toBe(0);
    expect(count("tool")).toBe(0);
  });

  it("keeps durations only where the log recorded one", () => {
    const rla = traceRows(events("efee736eb669"));
    expect(rla.filter((row) => row.durationMs !== null)).toHaveLength(0);
    expect(traceSummary(events("efee736eb669"))).toMatchObject({
      events: 55,
      phases: 11,
      failed: 0,
      durationMs: null,
    });

    const demo = traceRows(events("17ee03228c0b"));
    expect(demo.filter((row) => row.durationMs !== null)).toHaveLength(16);
    expect(traceSummary(events("17ee03228c0b")).durationMs).toBe(189.4);

    const deep = traceRows(events("Q01-deep"));
    expect(deep.filter((row) => row.durationMs !== null)).toHaveLength(48);
    expect(traceSummary(events("Q01-deep"))).toMatchObject({
      events: 381,
      phases: 9,
      failed: 0,
      durationMs: 2628.7,
    });
  });

  it("computes offsets from the first recorded event, never from wall-clock now", () => {
    const rows = traceRows(events("17ee03228c0b"));
    expect(rows.every((row) => row.offsetMs !== null)).toBe(true);
    expect(rows[0].offsetMs).toBe(0);
    expect(traceSpan(rows)).toBeGreaterThan(189.4);
    expect(rows[rows.length - 1].offsetMs).toBeLessThanOrEqual(traceSpan(rows));
  });
});

describe("trace classification", () => {
  it("prefers the recorded class/severity over the kind", () => {
    expect(classOf({ kind: "whatever", class: "evidence" })).toBe("evidence");
    expect(severityOf({ kind: "task_failed", severity: "warn" })).toBe("warn");
  });

  it("maps the old logs' classes and severities from what they recorded", () => {
    const rows = traceRows(events("Q01-deep"));
    const count = (name) => rows.filter((row) => row.className === name).length;
    expect(count("queue")).toBe(149);
    expect(count("task")).toBe(54);
    expect(count("stack")).toBe(78);
    expect(count("tool")).toBe(76);
    expect(rows.filter((row) => row.severity === "warn")).toHaveLength(5);
    expect(rows.filter((row) => row.severity === "error")).toHaveLength(0);
  });

  it("marks a failed finish as an error and a partial finish as a warning", () => {
    expect(severityOf({ kind: "run_finished", payload: { succeeded: false } })).toBe("error");
    expect(
      severityOf({ kind: "run_finished", payload: { termination_reason: "completed_with_partial_sources" } }),
    ).toBe("warn");
    expect(severityOf({ kind: "run_finished", payload: { succeeded: true } })).toBe("ok");
    expect(severityOf({ kind: "citation_validation", payload: { valid: false } })).toBe("warn");
    expect(severityOf({ kind: "citation_validation", payload: { valid: true } })).toBe("ok");
    expect(severityOf({ kind: "task_retry" })).toBe("warn");
    expect(severityOf({ kind: "task_completed" })).toBe("ok");
    expect(severityOf({ kind: "something_new" })).toBe("info");
  });

  it("reads a duration only where one is recorded", () => {
    expect(durationOf({ duration_ms: 0 })).toBe(0);
    expect(durationOf({ payload: { duration_ms: 12.5 } })).toBe(12.5);
    expect(durationOf({ duration_ms: "12" })).toBeNull();
    expect(durationOf({ payload: { duration_ms: -1 } })).toBeNull();
    expect(durationOf({})).toBeNull();
  });

  it("reads epoch seconds and epoch milliseconds", () => {
    expect(timestampMs({ timestamp: 1794647977.699 })).toBe(1794647977699);
    expect(timestampMs({ timestamp: 1794647977699 })).toBe(1794647977699);
    expect(timestampMs({ timestamp: 0 })).toBeNull();
    expect(timestampMs({})).toBeNull();
  });
});

describe("trace filters, grouping and virtualisation", () => {
  const rows = traceRows(events("Q01-deep"));

  it("filters by class without reordering the rows", () => {
    const queue = filterRows(rows, { classes: ["queue"] });
    expect(queue).toHaveLength(149);
    expect(queue.every((row) => row.className === "queue")).toBe(true);
    expect(queue.map((row) => row.seq)).toEqual(
      rows.filter((row) => row.className === "queue").map((row) => row.seq),
    );
  });

  it("supports failures-only, status chips and text search, including no matches", () => {
    expect(filterRows(rows, { failuresOnly: true })).toHaveLength(0);
    const warned = filterRows(rows, { severities: ["warn"] });
    expect(warned).toHaveLength(5);
    expect(warned.every((row) => row.severity === "warn")).toBe(true);

    const needle = rows[10].summary.toLowerCase();
    const hits = filterRows(rows, { query: needle });
    expect(hits).toContain(rows[10]);
    expect(hits.every((row) => row.seq !== undefined)).toBe(true);
    expect(filterRows(rows, { query: "no-such-event-anywhere" })).toHaveLength(0);
  });

  it("groups by phase and honours a collapsed group", () => {
    const sample = rows.slice(0, 40);
    const grouped = traceItems(sample, { grouped: true });
    expect(grouped[0]).toMatchObject({
      type: "group",
      phase: sample[0].phase,
      collapsed: false,
    });
    const firstGroup = grouped[0];
    expect(firstGroup.count).toBe(sample.filter((row) => row.phase === sample[0].phase).length);

    const closed = traceItems(sample, { grouped: true, collapsed: [sample[0].phase] });
    expect(closed[0]).toMatchObject({ type: "group", collapsed: true });
    expect(
      closed.filter((item) => item.type === "event" && item.row.phase === sample[0].phase),
    ).toHaveLength(0);
    expect(traceItems(sample)).toHaveLength(sample.length);
  });

  it("renders a window of ±10 rows, never the whole 381-event run", () => {
    expect(virtualWindow(381, 0, 480)).toEqual({
      start: 0,
      end: 25,
      topPad: 0,
      bottomPad: (381 - 25) * TRACE_ROW_HEIGHT,
    });

    const middle = virtualWindow(381, TRACE_ROW_HEIGHT * 100, 480);
    expect(middle.start).toBe(90);
    expect(middle.end).toBe(125);
    expect(middle.end - middle.start).toBe(35);
    expect(middle.topPad).toBe(90 * TRACE_ROW_HEIGHT);
    expect(middle.bottomPad).toBe((381 - 125) * TRACE_ROW_HEIGHT);
    expect(virtualWindow(0, 0, 480)).toEqual({ start: 0, end: 0, topPad: 0, bottomPad: 0 });
  });

  it("draws a bar for a recorded duration and a 2 px tick otherwise", () => {
    expect(barGeometry({ offsetMs: 0, durationMs: null }, 1000)).toEqual({
      left: 0,
      width: null,
      tick: true,
    });
    expect(barGeometry({ offsetMs: 1000, durationMs: 500 }, 2000)).toEqual({
      left: 50,
      width: 25,
      tick: false,
    });
    expect(barGeometry({ offsetMs: 1900, durationMs: 500 }, 2000)).toEqual({
      left: 95,
      width: 5,
      tick: false,
    });
    expect(barGeometry({ offsetMs: 10, durationMs: 0 }, 1000).tick).toBe(true);
    expect(barGeometry({ offsetMs: null, durationMs: 10 }, 1000).tick).toBe(true);
  });

  it("links related events only through a recorded task, provider or paper id", () => {
    const row = rows.find((item) => typeof item.event.payload?.task_id === "string");
    const related = relatedFor(row, rows);
    expect(related.length).toBeGreaterThan(0);
    expect(related.every((entry) => entry.row.seq !== row.seq)).toBe(true);
    expect(related.some((entry) => entry.reason === "same task")).toBe(true);

    const http = rows.find((item) => item.kind === "source_http_attempt");
    const byProvider = relatedFor(http, rows);
    expect(byProvider.some((entry) => entry.reason === "same provider")).toBe(true);

    expect(previousRow(rows[1], rows)).toBe(rows[0]);
    expect(previousRow(rows[0], rows)).toBeNull();
  });
});
