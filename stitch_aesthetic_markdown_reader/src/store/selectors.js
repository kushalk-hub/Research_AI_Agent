import {
  answerFrom,
  describeEvent,
  engineLabel,
  isTerminal,
  statusTone,
  workedFor,
  workingLines,
} from "../lib/events.js";

export function selectRun(state, runId) {
  if (!runId) return null;
  return state.runs[runId] || null;
}

export function selectActiveRun(state) {
  return selectRun(state, state.activeRunId);
}

/** Recents = runs opened in this tab (newest first), then recorded runs from
 *  disk that are not already shown. Deduplicated by run id. */
export function selectRecents(state) {
  const fromTab = state.order
    .map((id) => state.runs[id])
    .filter(Boolean)
    .map((run) => ({
      run_id: run.id,
      topic: run.topic,
      mode: run.mode,
      status: run.status,
      event_count: run.events.length,
      source_run_id: run.sourceRunId,
      at: run.openedAt || null,
      live: run.stream === "live" || run.stream === "connecting",
    }));

  const seen = new Set(fromTab.map((item) => item.run_id));
  const fromDisk = state.history
    .filter((item) => !seen.has(item.run_id))
    .map((item) => ({
      ...item,
      at: item.started_at || item.ended_at || null,
      live: false,
    }));

  return [...fromTab, ...fromDisk];
}

/** What the thread needs, without leaking the whole store into components. */
export function selectTurn(state, run) {
  if (!run) return null;
  const events = run.events;
  const finished = [...events].reverse().find(isTerminal);
  return {
    id: run.id,
    question: run.question || run.topic || "Untitled investigation",
    topic: run.topic,
    engineLabel: engineLabel(run.engine),
    mode: run.mode,
    status: run.status,
    statusTone: statusTone(run.status),
    statusReason: run.statusReason,
    stream: run.stream,
    eventCount: events.length,
    // Design §5.1: capped at six lines plus "and N more"; the collapse fact
    // comes from the terminal record, never from a wall clock.
    working: workingLines(events),
    answer: answerFrom(events),
    workedFor: workedFor(events),
    finished: Boolean(finished),
    stopping: Boolean(run.stopping) && !finished,
    historical: Boolean(run.historical),
    warnings: Number(run.warnings) || 0,
    sourceRunId: run.sourceRunId,
  };
}

/** Recorded plan levels (`list[list[str]]`) for the Lab, when present. */
export function selectPlan(state, run) {
  if (!run) return null;
  const planEvent = [...run.events]
    .reverse()
    .find((event) => event.kind === "plan_validated" || event.kind === "plan_received");
  const payload = planEvent?.payload || {};
  const levels = Array.isArray(payload.levels) ? payload.levels : [];
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  return { kind: planEvent?.kind || "", levels, tasks, mode: payload.mode || "" };
}

/** Recorded RLA phases in the order they appear (for the literature pipeline). */
export function selectPhases(state, run) {
  if (!run) return [];
  const phases = [];
  const seen = new Set();
  for (const event of run.events) {
    const phase = event.payload?.phase;
    if (typeof phase !== "string" || !phase || seen.has(phase)) continue;
    seen.add(phase);
    phases.push({
      id: phase,
      message: describeEvent(event),
      kind: event.payload?.phase_kind || "info",
      payload: event.payload?.stage_payload || {},
    });
  }
  return phases;
}
