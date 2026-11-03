"use strict";

(function attachCore(root) {
  function clampCursor(cursor, eventCount) {
    const value = Number.isFinite(Number(cursor)) ? Math.trunc(Number(cursor)) : 0;
    return Math.max(0, Math.min(value, Math.max(0, eventCount)));
  }

  function stepCursor(cursor, direction, eventCount) {
    return clampCursor(cursor + Math.sign(direction), eventCount);
  }

  function deriveSnapshot(events, cursor) {
    const visible = events.slice(0, clampCursor(cursor, events.length));
    const tasksEvent = [...visible].reverse().find((event) =>
      ["plan_validated", "plan_received"].includes(event.kind) && event.payload?.tasks?.length,
    );
    const tasks = tasksEvent?.payload?.tasks || [];
    const taskStates = Object.fromEntries(tasks.map((task) => [task.id, "planned"]));
    const active = new Map();
    const stacks = {};
    let readyQueue = [];
    let queueRecorded = false;
    let evidence = [];
    let answer = "";
    let validation = null;

    for (const event of visible) {
      const payload = event.payload || {};
      const taskId = payload.task_id;
      if (taskId && Object.hasOwn(taskStates, taskId)) {
        if (event.kind === "task_ready") taskStates[taskId] = "ready";
        else if (event.kind === "task_started") {
          taskStates[taskId] = "running";
          active.set(taskId, { task_id: taskId, started_at: event.timestamp, attempt: payload.attempt });
        } else if (event.kind === "task_completed") {
          taskStates[taskId] = "completed";
          active.delete(taskId);
        } else if (event.kind === "task_failed") {
          taskStates[taskId] = "failed";
          active.delete(taskId);
        } else if (event.kind === "task_blocked") {
          taskStates[taskId] = "blocked";
          active.delete(taskId);
        } else if (event.kind === "task_cancelled") {
          taskStates[taskId] = "cancelled";
          active.delete(taskId);
        } else if (event.kind === "task_retry") {
          taskStates[taskId] = "ready";
          active.delete(taskId);
        }
      }
      if (event.kind === "queue_updated") {
        readyQueue = payload.ready_queue || [];
        queueRecorded = true;
      }
      if ((event.kind === "stack_push" || event.kind === "stack_pop") && taskId) {
        stacks[taskId] = payload.stack || [];
      }
      if (event.kind === "evidence_selected") evidence = payload.evidence || [];
      if (event.kind === "answer_ready") answer = payload.answer || "";
      if (event.kind === "citation_validation") validation = payload;
    }

    const activeTasks = [...active.values()];

    return {
      events: visible,
      tasks,
      taskStates,
      readyQueue,
      activeTasks,
      queueRecorded,
      workerAssignmentsAvailable: false,
      stacks,
      evidence,
      answer,
      validation,
      selectedEvent: visible.at(-1) || null,
    };
  }

  function findEvidenceByCitation(evidence, citation) {
    return evidence.find((item) => item.citation === citation) || null;
  }

  function executionLabel(run) {
    if (!run) return "NO RUN";
    if (run.run_kind === "replay") return "REPLAY";
    if (run.mode === "simulate") return "SIMULATION";
    return String(run.mode || "unknown").toUpperCase();
  }

  function eventIndexForTask(events, taskId) {
    const index = events.findLastIndex((event) => event.payload?.task_id === taskId);
    return index >= 0 ? index : events.findIndex((event) => event.kind === "plan_received");
  }

  function laneForEvent(kind) {
    if (kind.startsWith("model_")) return "Model";
    if (kind.startsWith("tool_call_") || kind.startsWith("source_")) return "Tool / source";
    if (kind.startsWith("context_")) return "Context";
    if (kind === "evidence_selected") return "Evidence";
    if (kind === "answer_ready") return "Answer";
    if (kind.includes("citation")) return "Validation";
    if (kind === "brief_saved") return "Output";
    return "Runtime";
  }

  const api = {
    clampCursor,
    stepCursor,
    deriveSnapshot,
    findEvidenceByCitation,
    executionLabel,
    eventIndexForTask,
    laneForEvent,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.FODSFrontendCore = api;
})(typeof globalThis === "undefined" ? this : globalThis);
