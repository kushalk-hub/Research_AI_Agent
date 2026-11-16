/** The single place where a recorded event becomes human-readable text.
 *
 *  Both the execution trace and the in-thread status lines call these helpers,
 *  so the two surfaces cannot disagree (see docs/FRONTEND_DESIGN.md §5.1).
 *  Backend enrichment (slice 3a) may add `summary`, `phase`, `class`,
 *  `severity` and `duration_ms`; when a field is absent the fallbacks below keep
 *  the 82 already-recorded logs readable.
 */

import { answerEvidence } from "./citations.js";
import { formatDuration, redactText } from "./format.js";

/** The in-thread working list shows at most this many one-liners. */
export const MAX_WORKING_LINES = 6;

const PHASE_LABELS = Object.freeze({
  plan: "Plan",
  queue: "Queue",
  task: "Task",
  tool: "Tool",
  stack: "Stack",
  model: "Model",
  source: "Source",
  acquire: "Acquire",
  merge: "Merge",
  evidence: "Evidence",
  answer: "Answer",
  validation: "Validation",
  validate: "Validate",
  output: "Output",
  write: "Write",
  runtime: "Runtime",
  search: "Search",
  fetch: "Fetch",
  score: "Score",
  fulltext: "Full text",
  extract: "Extract",
  resolve: "Resolve",
  graph: "Graph",
  traverse: "Traverse",
  done: "Done",
  error: "Error",
});

export function phaseLabel(phase) {
  if (!phase) return PHASE_LABELS.runtime;
  const label = PHASE_LABELS[phase];
  if (label) return label;
  const text = String(phase);
  return text[0].toUpperCase() + text.slice(1);
}

/** Run statuses the UI can show. `abstained` is deliberately absent: no
 *  abstention flag exists in the runtime (only a prompt instruction), so the UI
 *  must not imply one. */
export const STATUS = Object.freeze({
  STARTING: "starting",
  RUNNING: "running",
  STOPPING: "stopping",
  COMPLETED: "completed",
  PARTIAL: "partial",
  FAILED: "failed",
  CANCELLED: "cancelled",
  INTERRUPTED: "interrupted",
  REPLAYED: "replayed",
});

export const STATUS_LABEL = Object.freeze({
  starting: "Starting",
  running: "Running",
  stopping: "Stopping",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Stopped",
  interrupted: "Interrupted",
  replayed: "Replay",
  unknown: "Unknown",
});

const STATUS_TONE = Object.freeze({
  starting: "warn",
  running: "live",
  stopping: "warn",
  completed: "ok",
  partial: "warn",
  failed: "err",
  cancelled: "blocked",
  interrupted: "warn",
  replayed: "blocked",
  unknown: "muted",
});

export function statusTone(status) {
  return STATUS_TONE[status] || "muted";
}

export function statusLabel(status) {
  return STATUS_LABEL[status] || STATUS_LABEL.unknown;
}

/** Terminal status from a `run_finished` payload. */
export function statusFromFinish(payload = {}) {
  if (payload.termination_reason === "completed_with_partial_sources") return STATUS.PARTIAL;
  if (payload.termination_reason === "cancelled") return STATUS.CANCELLED;
  if (payload.succeeded) return STATUS.COMPLETED;
  return STATUS.FAILED;
}

export function isTerminal(event) {
  return event?.kind === "run_finished";
}

const ENGINE_LABEL = Object.freeze({
  rla: "Literature pipeline",
  fods: "FODS scheduler",
});

export function engineLabel(engine) {
  return ENGINE_LABEL[engine] || "Runtime";
}

export function modeLabel(mode) {
  if (mode === "simulate") return "Deterministic demo";
  if (mode === "replay") return "Replay";
  if (mode === "live") return "Live";
  return "Unknown mode";
}

/** Compact mode label for dense lists; the full label stays in the tooltip. */
export function modeShort(mode) {
  if (mode === "simulate") return "Demo";
  if (mode === "replay") return "Replay";
  if (mode === "live") return "Live";
  return "Unknown";
}

/** Tool name -> trace phase, mirroring `fods/event_meta.py:TOOL_PHASE`. */
const TOOL_PHASE = Object.freeze({
  search_: "acquire",
  acquisition_checkpoint: "acquire",
  merge_and_save_context: "merge",
  load_saved_context: "merge",
  retrieve_evidence: "evidence",
  draft_cited_answer: "answer",
  validate_citations: "validate",
  write_cited_brief: "write",
});

const PLAN_KINDS = new Set([
  "research_query_plan",
  "plan_received",
  "plan_repaired",
  "plan_validated",
  "plan_rejected",
]);
const QUEUE_KINDS = new Set([
  "task_ready",
  "queue_updated",
  "task_dequeued",
  "dependency_updated",
]);

/** Phase of an event, from the recorded field or the event kind.
 *
 *  Design §5: the phase is a fact about the record, not a guess from `kind`.
 *  RLA events carry `payload.phase`; FODS events carry the tool that ran, and
 *  the tool decides the phase. `plan`, `queue`, `task`, `stack`, `tool` and
 *  everything else are runtime — the backend's `phase_for()` says the same. */
export function phaseOf(event) {
  const payload = event?.payload || {};
  if (typeof payload.phase === "string" && payload.phase) return payload.phase;
  const tool = typeof payload.tool === "string" ? payload.tool : "";
  if (tool) {
    for (const [needle, phase] of Object.entries(TOOL_PHASE)) {
      if (tool === needle || (needle.endsWith("_") && tool.startsWith(needle))) return phase;
    }
  }
  const kind = String(event?.kind || "");
  if (PLAN_KINDS.has(kind)) return "plan";
  if (QUEUE_KINDS.has(kind)) return "queue";
  return "runtime";
}

/** A short, honest explanation of why a run ended the way it did.
 *  Only uses fields the runtime actually records. */
export function finishReason(payload = {}) {
  const parts = [];
  const reason = payload.termination_reason;
  if (reason && reason !== "completed") parts.push(String(reason).replace(/_/g, " "));
  const sources = Array.isArray(payload.unavailable_sources)
    ? payload.unavailable_sources.filter(Boolean).map(String)
    : [];
  if (sources.length) {
    const shown = sources.slice(0, 3).join(", ");
    const more = sources.length > 3 ? "…" : "";
    parts.push(`${sources.length} source${sources.length === 1 ? "" : "s"} unavailable (${shown}${more})`);
  }
  return parts.join(" · ");
}

/** One line, at most ~90 characters, never raw JSON. */
export function describeEvent(event) {
  if (!event) return "";
  if (typeof event.summary === "string" && event.summary.trim()) {
    return truncate(redactText(event.summary), 90);
  }
  const message = typeof event.message === "string" ? event.message : "";
  if (message.trim()) return truncate(redactText(message), 90);
  const payload = event.payload || {};
  const phase = payload.phase;
  if (phase) return truncate(redactText(`${phase} phase`), 90);
  return truncate(redactText(String(event.kind || "event").replace(/_/g, " ")), 90);
}

function truncate(text, max) {
  const value = String(text).replace(/\s+/g, " ").trim();
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trimEnd()}…`;
}

/** The most recent recorded one-liners, each tagged with its phase.
 *
 *  Design §5.1: capped at six lines plus "and N more". The list is derived from
 *  the same `describeEvent()` used by the Trace, so the two never disagree. */
export function workingLines(events = [], limit = MAX_WORKING_LINES) {
  const lines = [];
  for (const event of events) {
    if (!event || isTerminal(event)) continue;
    lines.push({
      seq: Number.isFinite(Number(event.seq)) ? Number(event.seq) : lines.length + 1,
      phase: phaseOf(event),
      text: describeEvent(event),
    });
  }
  const shown = limit > 0 ? lines.slice(-limit) : [];
  return { lines: shown, more: Math.max(0, lines.length - shown.length) };
}

/** How many distinct phases the run actually recorded. */
export function countPhases(events = []) {
  const seen = new Set();
  for (const event of events) {
    if (!event || isTerminal(event)) continue;
    seen.add(phaseOf(event));
  }
  return seen.size;
}

/** The recorded answer, when there is one. Citation chips and evidence cards
 *  are resolved by `lib/citations.js` (slice 5); Markdown rendering is slice 6. */
export function answerFrom(events = []) {
  const event = [...events]
    .reverse()
    .find((item) => item?.kind === "research_answer" || item?.kind === "answer_ready");
  if (!event) return null;
  const payload = event.payload || {};
  const text = typeof payload.answer === "string" ? payload.answer.trim() : "";
  if (!text) return null;
  return {
    seq: event.seq,
    text,
    questionType: payload.question_type || "",
    citations: Array.isArray(payload.citations) ? payload.citations : [],
    evidence: answerEvidence({ text }, events),
    stripped: Array.isArray(payload.stripped_citations) ? payload.stripped_citations : [],
  };
}

/** "Worked for 2m 14s · 9 steps" facts, from the terminal record only.
 *
 *  `elapsed_ms` may be absent on old logs; the caller must then say the
 *  duration was not recorded instead of inventing one. */
export function workedFor(events = []) {
  const finish = [...events].reverse().find(isTerminal);
  if (!finish) return null;
  const payload = finish.payload || {};
  const elapsed = Number(payload.elapsed_ms);
  const stages = Array.isArray(payload.stages) ? payload.stages.filter(Boolean).length : 0;
  return {
    duration: Number.isFinite(elapsed) && elapsed >= 0 ? formatDuration(elapsed) : "",
    steps: stages || countPhases(events),
  };
}
