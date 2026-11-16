/** The single place where a recorded event becomes human-readable text.
 *
 *  Both the execution trace and the in-thread status lines call these helpers,
 *  so the two surfaces cannot disagree (see docs/FRONTEND_DESIGN.md §5.1).
 *  Backend enrichment (slice 3a) may add `summary`, `phase`, `class`,
 *  `severity` and `duration_ms`; when a field is absent the fallbacks below keep
 *  the 82 already-recorded logs readable.
 */

import { redactText } from "./format.js";

/** Run statuses the UI can show. `abstained` is deliberately absent: no
 *  abstention flag exists in the runtime (only a prompt instruction), so the UI
 *  must not imply one. */
export const STATUS = Object.freeze({
  STARTING: "starting",
  RUNNING: "running",
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

/** Phase of an event, from the recorded field or the event kind. */
export function phaseOf(event) {
  const payload = event?.payload || {};
  if (typeof payload.phase === "string" && payload.phase) return payload.phase;
  const kind = String(event?.kind || "");
  if (kind.startsWith("plan") || kind.startsWith("research_query")) return "plan";
  if (kind.startsWith("queue") || kind === "task_ready" || kind === "task_dequeued") return "queue";
  if (kind.startsWith("task")) return "task";
  if (kind.startsWith("tool")) return "tool";
  if (kind.startsWith("stack")) return "stack";
  if (kind.startsWith("model")) return "model";
  if (kind.includes("source")) return "source";
  if (kind.includes("evidence")) return "evidence";
  if (kind.includes("answer")) return "answer";
  if (kind.includes("citation") || kind.includes("validation")) return "validation";
  if (kind === "brief_saved") return "output";
  if (kind === "run_started" || kind === "run_finished" || kind === "run_failed") return "runtime";
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
