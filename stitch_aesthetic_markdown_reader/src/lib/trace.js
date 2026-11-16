/** The trace model: one place that turns recorded events into rows.
 *
 *  UI-11: the old trace read `event.phase`, which never existed — every RLA row
 *  said `research_progress`. Phases, classes and severities now come from the
 *  backend fields (slice 3a, `fods/event_meta.py`) and fall back here for the
 *  logs recorded before those fields existed.
 *
 *  The same `describeEvent()` used by the in-chat working lines supplies the
 *  summary, so the trace and the thread cannot disagree (design §5.1, §8.5).
 */

import { describeEvent, isTerminal, phaseOf } from "./events.js";

export const TRACE_CLASSES = [
  "plan",
  "queue",
  "task",
  "stack",
  "tool",
  "model",
  "source",
  "evidence",
  "answer",
  "validation",
  "output",
  "runtime",
];

export const TRACE_ROW_HEIGHT = 32;
export const TRACE_OVERSCAN = 10;

const CLASS_BY_PHASE = {
  search: "source",
  fetch: "source",
  score: "source",
  fulltext: "source",
  extract: "evidence",
  resolve: "evidence",
  graph: "evidence",
  traverse: "evidence",
  answer: "answer",
  done: "runtime",
  error: "runtime",
};

const ERROR_KINDS = new Set([
  "plan_rejected",
  "run_failed",
  "tool_call_failed",
  "task_failed",
  "model_call_failed",
  "source_rate_limit_stopped",
  "source_http_budget_stopped",
]);

const WARN_KINDS = new Set([
  "task_retry",
  "task_cancelled",
  "research_stopping",
  "run_cancel_requested",
  "task_cancel_requested",
  "recovery_decision",
]);

/** Trace class for an event, recorded or derived from its kind/phase. */
export function classOf(event) {
  const recorded = String(event?.class || event?.event_class || "");
  if (TRACE_CLASSES.includes(recorded)) return recorded;
  const kind = String(event?.kind || "");
  if (kind.startsWith("plan") || kind.startsWith("research_query")) return "plan";
  if (kind === "task_ready" || kind === "task_dequeued" || kind === "queue_updated") {
    return "queue";
  }
  if (kind === "dependency_updated") return "queue";
  if (kind.startsWith("task")) return "task";
  if (kind.startsWith("stack")) return "stack";
  if (kind.startsWith("tool")) return "tool";
  if (kind.startsWith("model")) return "model";
  if (
    kind === "context_ready" ||
    kind === "research_papers" ||
    kind === "research_stopping" ||
    kind.startsWith("source_")
  ) {
    return "source";
  }
  if (kind === "evidence_selected") return "evidence";
  if (kind === "answer_ready" || kind === "research_answer") return "answer";
  if (kind === "citation_validation") return "validation";
  if (kind === "brief_saved") return "output";
  const phase = String(event?.payload?.phase || "");
  if (phase) return CLASS_BY_PHASE[phase] || "runtime";
  return "runtime";
}

/** info | ok | warn | error, from the record, never from the appearance. */
export function severityOf(event) {
  const recorded = String(event?.severity || "");
  if (["info", "ok", "warn", "error"].includes(recorded)) return recorded;
  const kind = String(event?.kind || "");
  const payload = event?.payload || {};
  if (ERROR_KINDS.has(kind)) return "error";
  if (kind === "citation_validation") return payload.valid ? "ok" : "warn";
  if (kind === "run_finished") {
    if (payload.succeeded === false) return "error";
    if (payload.termination_reason === "completed_with_partial_sources") return "warn";
    return "ok";
  }
  if (WARN_KINDS.has(kind)) return "warn";
  if (payload.valid === false) return "warn";
  if (kind.endsWith("_completed") || kind.endsWith("_saved") || kind.endsWith("_ready")) {
    return "ok";
  }
  if (kind.endsWith("_validated")) return "ok";
  return "info";
}

export const SEVERITY_LABEL = Object.freeze({
  info: "Info",
  ok: "OK",
  warn: "Warn",
  error: "Failed",
});

/** Recorded duration in ms, or null. Never guessed from neighbouring events. */
export function durationOf(event) {
  const payload = event?.payload || {};
  for (const value of [event?.duration_ms, payload.duration_ms]) {
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) return value;
  }
  return null;
}

/** Epoch milliseconds for an event, from seconds or milliseconds. */
export function timestampMs(event) {
  const raw = event?.timestamp ?? event?.payload?.event_timestamp;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) return null;
  return value > 1e12 ? value : value * 1000;
}

/** Every event as a trace row, in recorded order. */
export function traceRows(events = []) {
  let t0 = null;
  for (const event of events) {
    const ms = timestampMs(event);
    if (ms !== null && (t0 === null || ms < t0)) t0 = ms;
  }
  return events.map((event) => {
    const ms = timestampMs(event);
    const offset = ms !== null && t0 !== null ? Math.max(0, ms - t0) : null;
    return {
      seq: event?.seq,
      kind: String(event?.kind || ""),
      phase: phaseOf(event),
      className: classOf(event),
      severity: severityOf(event),
      summary: describeEvent(event),
      durationMs: durationOf(event),
      offsetMs: offset,
      terminal: isTerminal(event),
      event,
    };
  });
}

/** The bottom bar: counts from the rows, duration from the terminal record. */
export function traceSummary(events = [], rows = traceRows(events)) {
  const finish = [...events].reverse().find((event) => event?.kind === "run_finished");
  const elapsed = finish?.payload?.elapsed_ms;
  return {
    events: rows.length,
    phases: new Set(rows.map((row) => row.phase)).size,
    failed: rows.filter((row) => row.severity === "error").length,
    // `null` is a recorded fact, not zero: an RLA run today has no elapsed_ms,
    // so the summary bar must say "duration not recorded" (design §5).
    durationMs:
      typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0 ? elapsed : null,
  };
}

function matchesQuery(row, query) {
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [row.summary, row.phase, row.className, row.kind, String(row.seq)]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

/** Apply the toolbar filters. Empty arrays mean "all classes" / "all statuses". */
export function filterRows(
  rows,
  { query = "", classes = [], severities = [], failuresOnly = false, hiddenPhases = [] } = {},
) {
  const chosen = new Set(classes);
  const statuses = new Set(severities);
  const hidden = new Set(hiddenPhases);
  return rows.filter((row) => {
    if (chosen.size > 0 && !chosen.has(row.className)) return false;
    if (statuses.size > 0 && !statuses.has(row.severity)) return false;
    if (failuresOnly && row.severity !== "error") return false;
    if (hidden.has(row.phase)) return false;
    return matchesQuery(row, query);
  });
}

/** Rows plus a collapsible header per phase, or rows alone when ungrouped. */
export function traceItems(rows, { grouped = false, collapsed = [] } = {}) {
  if (!grouped) return rows.map((row) => ({ type: "event", row }));
  const closed = new Set(collapsed);
  const order = [];
  const byPhase = new Map();
  for (const row of rows) {
    if (!byPhase.has(row.phase)) {
      byPhase.set(row.phase, []);
      order.push(row.phase);
    }
    byPhase.get(row.phase).push(row);
  }
  const items = [];
  for (const phase of order) {
    const groupRows = byPhase.get(phase);
    const isCollapsed = closed.has(phase);
    items.push({ type: "group", phase, count: groupRows.length, collapsed: isCollapsed });
    if (isCollapsed) continue;
    for (const row of groupRows) items.push({ type: "event", row });
  }
  return items;
}

/** Fixed-height virtual window plus the spacer sizes around it. */
export function virtualWindow(
  count,
  scrollTop = 0,
  viewportHeight = 480,
  rowHeight = TRACE_ROW_HEIGHT,
  overscan = TRACE_OVERSCAN,
) {
  const total = Math.max(0, count);
  if (total === 0) return { start: 0, end: 0, topPad: 0, bottomPad: 0 };
  const height = viewportHeight > 0 ? viewportHeight : 480;
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const visible = Math.ceil(height / rowHeight);
  const start = Math.max(0, first - overscan);
  const end = Math.min(total, first + visible + overscan);
  return { start, end, topPad: start * rowHeight, bottomPad: (total - end) * rowHeight };
}

/** Extent the fit scale uses: the last recorded moment, not a guess. */
export function traceSpan(rows) {
  let span = 0;
  for (const row of rows) {
    if (row.offsetMs === null) continue;
    span = Math.max(span, row.offsetMs + (row.durationMs || 0));
  }
  return Math.max(span, 1);
}

/** Bar geometry in percent, or a tick when no duration was recorded. */
export function barGeometry(row, scaleMs) {
  const scale = scaleMs > 0 ? scaleMs : 1;
  if (row.offsetMs === null) return { left: 0, width: null, tick: true };
  const left = Math.min(100, Math.max(0, (row.offsetMs / scale) * 100));
  if (row.durationMs === null) return { left, width: null, tick: true };
  const width = Math.min(100 - left, Math.max(0, (row.durationMs / scale) * 100));
  return { left, width, tick: width <= 0 };
}

function paperIds(payload = {}) {
  const ids = new Set();
  if (typeof payload.paper_id === "string") ids.add(payload.paper_id);
  if (typeof payload.paper?.id === "string") ids.add(payload.paper.id);
  if (Array.isArray(payload.paper_ids)) {
    for (const id of payload.paper_ids) if (typeof id === "string") ids.add(id);
  }
  if (Array.isArray(payload.papers)) {
    for (const paper of payload.papers) {
      if (typeof paper?.id === "string") ids.add(paper.id);
    }
  }
  // `evidence_selected.evidence` is a list of `{citation, paper}` cards.
  if (Array.isArray(payload.evidence)) {
    for (const card of payload.evidence) {
      if (typeof card?.paper?.id === "string") ids.add(card.paper.id);
      if (typeof card?.paper_id === "string") ids.add(card.paper_id);
    }
  }
  return ids;
}

/** Events the current row can be read against, with the reason they match. */
export function relatedFor(row, rows, limit = 8) {
  if (!row) return [];
  const payload = row.event?.payload || {};
  const task = typeof payload.task_id === "string" ? payload.task_id : "";
  const provider = typeof payload.provider === "string" ? payload.provider : "";
  const papers = paperIds(payload);
  const related = [];
  for (const other of rows) {
    if (other.seq === row.seq) continue;
    const otherPayload = other.event?.payload || {};
    if (task && otherPayload.task_id === task) {
      related.push({ row: other, reason: "same task" });
      continue;
    }
    if (provider && otherPayload.provider === provider) {
      related.push({ row: other, reason: "same provider" });
      continue;
    }
    if (papers.size > 0) {
      const match = [...paperIds(otherPayload)].find((id) => papers.has(id));
      if (match) related.push({ row: other, reason: "same paper" });
    }
  }
  return related.slice(0, limit);
}

/** The row immediately before `row` in recorded order, for the gap figure. */
export function previousRow(row, rows) {
  const index = rows.indexOf(row);
  return index > 0 ? rows[index - 1] : null;
}
