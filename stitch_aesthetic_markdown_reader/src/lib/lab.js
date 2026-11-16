/** The FODS Lab model: what the recorded run actually did, and nothing else.
 *
 *  UI-07: two pipelines with disjoint vocabularies share one page. An RLA run
 *  records `research_progress` phases and no plan; a FODS run records a plan,
 *  a queue, task stacks and worker concurrency. Every function here reads the
 *  log and returns what is present, marking what is absent as "not recorded"
 *  rather than inventing a value (design §4.1, §4.3, §4.4).
 *
 *  Geometry is deterministic: the plan's own Kahn levels decide columns, task
 *  order inside a level decides rows, so a replay lays out identically.
 */

import { describeEvent, phaseLabel } from "./events.js";
import { formatDuration } from "./format.js";
import { classOf } from "./trace.js";

export const LAB_PIPELINES = Object.freeze({
  scheduler: "fods-scheduler",
  phases: "rla-phases",
});

export const LAB_TABS = Object.freeze([
  { id: "plan", label: "Graph" },
  { id: "queue", label: "Queue" },
  { id: "stacks", label: "Stacks" },
  { id: "state", label: "State" },
]);

export const LAB_PLAYBACK_SPEEDS = Object.freeze([0.5, 1, 2, 4]);

export const LAB_CAPTION_WINDOW_MS = 4000;

export const LAB_NODE = Object.freeze({
  width: 216,
  height: 76,
  gutter: 96,
  gap: 28,
  pad: 32,
});

export const TASK_STATES = Object.freeze([
  "planned",
  "ready",
  "dispatched",
  "running",
  "completed",
  "failed",
  "blocked",
  "cancelled",
]);

const FODS_EVIDENCE = new Set([
  "plan_validated",
  "plan_received",
  "task_ready",
  "queue_updated",
  "task_started",
  "stack_push",
]);

const CAPTION_KINDS = new Set([
  "plan_validated",
  "task_ready",
  "task_dequeued",
  "task_completed",
  "task_failed",
  "task_cancelled",
  "plan_rejected",
  "run_finished",
  "stack_push",
]);

function findEvent(events, kind) {
  return events.find((event) => event?.kind === kind) || null;
}

function lastEvent(events, kind) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.kind === kind) return events[index];
  }
  return null;
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function text(value) {
  return typeof value === "string" ? value : "";
}

function humanise(value) {
  const raw = text(value).replace(/[_-]+/g, " ").trim();
  return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : "";
}

/** Which pipeline recorded this run: declared first, then structural evidence. */
export function labPipeline(run) {
  const declared = text(run?.pipeline);
  if (Object.values(LAB_PIPELINES).includes(declared)) return declared;

  const events = run?.events || [];
  const started = findEvent(events, "run_started");
  const declaredInLog = text(started?.payload?.pipeline);
  if (Object.values(LAB_PIPELINES).includes(declaredInLog)) return declaredInLog;
  if (text(started?.payload?.engine) === "rla") return LAB_PIPELINES.phases;

  if (events.some((event) => FODS_EVIDENCE.has(event?.kind))) {
    return LAB_PIPELINES.scheduler;
  }
  if (events.some((event) => typeof event?.payload?.phase === "string")) {
    return LAB_PIPELINES.phases;
  }
  return "unknown";
}

/** The counts worth showing for each RLA stage, in the recorded payload. */
const STAGE_FIELDS = Object.freeze({
  search: [["sources", "sources"]],
  fetch: [["sources", "sources"]],
  score: [
    ["scored", "scored"],
    ["failed_batches", "failed batches"],
  ],
  fulltext: [],
  extract: [
    ["reused", "reused"],
    ["pending", "pending"],
  ],
  resolve: [
    ["mentions", "mentions"],
    ["names", "names"],
  ],
  graph: [
    ["papers", "papers"],
    ["concepts", "concepts"],
    ["derived_edges", "derived edges"],
    ["citations", "citations"],
  ],
  traverse: [
    ["nodes", "nodes"],
    ["edges", "edges"],
    ["seeds", "seeds"],
  ],
  answer: [
    ["citations", "citations"],
    ["uncited", "uncited"],
    ["stats.nodes", "nodes"],
    ["stats.edges", "edges"],
  ],
  done: [
    ["cache.hits", "cache hits"],
    ["cache.misses", "cache misses"],
    ["extraction.reused", "extractions reused"],
    ["extraction.extracted", "extractions new"],
  ],
});

function valueAt(payload, path) {
  let value = payload;
  for (const part of path.split(".")) {
    if (!value || typeof value !== "object") return undefined;
    value = value[part];
  }
  return value;
}

function countValue(item) {
  if (typeof item === "number" && Number.isFinite(item)) return item;
  // A recorded list is a recorded length; a missing list is not a zero.
  if (Array.isArray(item)) return item.length;
  return null;
}

function numericLeaves(value, prefix, out, depth) {
  if (!value || typeof value !== "object" || depth > 2 || out.length >= 8) return out;
  for (const [key, item] of Object.entries(value)) {
    if (out.length >= 8) break;
    const path = prefix ? `${prefix}.${key}` : key;
    const count = countValue(item);
    if (count !== null) {
      out.push({ key: path, value: count });
    } else if (item && typeof item === "object" && !Array.isArray(item)) {
      numericLeaves(item, path, out, depth + 1);
    }
  }
  return out;
}

/** Up to four recorded counts from a stage payload.
 *
 *  Known stages use the fields that carry the teaching fact (graph papers and
 *  concepts, extraction reuse, cache hits); anything else falls back to the
 *  first recorded numeric leaves. Arrays contribute their recorded length.
 *  Absent means absent: an empty result is rendered as "not recorded", not 0. */
export function stageCounts(payload, phase = "") {
  const source = payload || {};
  const curated = STAGE_FIELDS[phase];
  if (Array.isArray(curated)) {
    const present = curated
      .map(([path, label]) => ({ key: label, value: countValue(valueAt(source, path)) }))
      .filter((entry) => entry.value !== null);
    if (present.length > 0) return present;
  }
  return numericLeaves(source, "", [], 0).slice(0, 4);
}

export function formatCounts(counts) {
  return counts
    .map(({ key, value }) => {
      const label = key.replace(/[._]+/g, " ");
      const shown = Number.isInteger(value) ? String(value) : String(Math.round(value * 10) / 10);
      return `${label} ${shown}`;
    })
    .join(" · ");
}

/** Merge counts recorded across several events of the same stage.
 *
 *  `search` first records 5 sources and later the 4 generated queries; both are
 *  facts, so both stay. A repeated key takes the later recorded value, and the
 *  rail shows at most four. */
function mergeCounts(existing, incoming) {
  const merged = new Map(existing.map((entry) => [entry.key, entry.value]));
  for (const entry of incoming) merged.set(entry.key, entry.value);
  return [...merged.entries()].slice(0, 4).map(([key, value]) => ({ key, value }));
}

/** The RLA phase rail (design §4.1), in the backend's declared order only.
 *
 *  Old logs predate `run_started.pipeline_stages`. They are shown in the order
 *  the phases were first recorded, and the rail says so; no edges are drawn
 *  because no order was declared. `fulltext` is always a Phase 2 stub. */
export function phaseRail(run) {
  const events = run?.events || [];
  const started = findEvent(events, "run_started");
  const declaredStages = started?.payload?.pipeline_stages;
  const declared =
    Array.isArray(declaredStages) && declaredStages.length > 0
      ? [...declaredStages].sort((left, right) => (left.order ?? 0) - (right.order ?? 0))
      : null;

  const recorded = new Map();
  for (const event of events) {
    const payload = event?.payload || {};
    if (event?.kind !== "research_progress") continue;
    if (typeof payload.phase !== "string" || !payload.phase) continue;
    const entry = recorded.get(payload.phase) || { counts: [], message: describeEvent(event) };
    if (payload.stage_payload && Object.keys(payload.stage_payload).length > 0) {
      const counts = stageCounts(payload.stage_payload, payload.phase);
      // A stage records several events; merge the facts instead of letting a
      // later title-only event erase an earlier count.
      if (counts.length > 0) entry.counts = mergeCounts(entry.counts, counts);
      entry.message = describeEvent(event);
    }
    recorded.set(payload.phase, entry);
  }

  const finish = lastEvent(events, "run_finished");
  const timings = new Map(
    (Array.isArray(finish?.payload?.stages) ? finish.payload.stages : [])
      .filter((stage) => typeof stage?.id === "string")
      .map((stage) => [stage.id, stage]),
  );

  const ids = declared ? declared.map((stage) => String(stage.id)) : [...recorded.keys()];
  const declaredIds = new Set(ids);
  for (const id of recorded.keys()) {
    if (!declaredIds.has(id)) ids.push(id);
  }

  const stages = ids.map((id, index) => {
    const entry = recorded.get(id);
    const declaredStage = declared?.find((stage) => String(stage.id) === id);
    return {
      id,
      order: index,
      label: text(declaredStage?.label) || phaseLabel(id),
      class: classOf({ kind: "research_progress", payload: { phase: id } }),
      recorded: Boolean(entry),
      stub: id === "fulltext",
      // Absent counts stay absent: a phase with no recorded counts is not 0.
      counts: entry?.counts || [],
      message: entry?.message || "",
      timing: timings.get(id) || null,
    };
  });

  return {
    declared: Boolean(declared),
    declaredOrder: declared ? ids : [],
    stages,
    note: declared
      ? ""
      : "This log predates the declared stage list; stages are shown in the order they were first recorded, and no order is implied.",
  };
}

/** Recorded level, or a longest-path fallback that survives a cycle. */
function levelsOf(tasks) {
  const ids = new Set(tasks.map((task) => task.id));
  const dependencies = new Map(
    tasks.map((task) => [
      task.id,
      (Array.isArray(task.dependsOn)
        ? task.dependsOn
        : Array.isArray(task.depends_on)
          ? task.depends_on
          : []
      ).filter((id) => ids.has(id)),
    ]),
  );
  const depth = new Map();
  let hasCycle = false;

  function depthOf(id, stack) {
    if (depth.has(id)) return depth.get(id);
    if (stack.has(id)) {
      hasCycle = true;
      return 0;
    }
    stack.add(id);
    const parents = dependencies.get(id) || [];
    const value = parents.length
      ? Math.max(...parents.map((parent) => depthOf(parent, stack))) + 1
      : 0;
    stack.delete(id);
    depth.set(id, value);
    return value;
  }

  for (const task of tasks) depthOf(task.id, new Set());

  const levels = [];
  for (const task of tasks) {
    const level = depth.get(task.id) || 0;
    while (levels.length <= level) levels.push([]);
    levels[level].push(task.id);
  }
  return { levels, hasCycle };
}

/** The recorded plan, its levels and the edges the plan declares. */
export function planModel(events = []) {
  const validated = lastEvent(events, "plan_validated");
  const received = lastEvent(events, "plan_received");
  const source = validated || received;
  const payload = source?.payload || {};
  const rawTasks = Array.isArray(validated?.payload?.tasks)
    ? validated.payload.tasks
    : Array.isArray(payload.tasks)
      ? payload.tasks
      : [];
  const tasks = rawTasks
    .filter((task) => task && typeof task.id === "string")
    .map((task) => ({
      id: task.id,
      tool: text(task.tool) || task.id,
      dependsOn: (Array.isArray(task.depends_on) ? task.depends_on : []).filter(
        (id) => typeof id === "string",
      ),
      priority: finite(task.priority),
    }));
  const byId = new Map(tasks.map((task) => [task.id, task]));
  // Only dependencies on tasks this plan actually declares become edges.
  for (const task of tasks) {
    task.dependsOn = task.dependsOn.filter((id) => byId.has(id));
  }

  const recordedLevels = Array.isArray(validated?.payload?.levels)
    ? validated.payload.levels
        .filter((level) => Array.isArray(level))
        .map((level) => level.filter((id) => byId.has(id)))
    : [];
  const covered = new Set(recordedLevels.flat());
  const usableLevels =
    recordedLevels.length > 0 && tasks.every((task) => covered.has(task.id));
  const fallback = usableLevels ? null : levelsOf(tasks);

  const planRejected = lastEvent(events, "plan_rejected");
  const rejectedTasks = Array.isArray(planRejected?.payload?.tasks)
    ? planRejected.payload.tasks
        .filter((task) => task && typeof task.id === "string")
        .map((task) => ({
          id: task.id,
          tool: text(task.tool) || task.id,
          dependsOn: (Array.isArray(task.depends_on) ? task.depends_on : []).filter(
            (id) => typeof id === "string",
          ),
          priority: finite(task.priority),
        }))
    : [];

  return {
    kind: source?.kind || "",
    tasks,
    byId,
    levels: usableLevels ? recordedLevels : fallback.levels,
    levelsComputed: !usableLevels,
    hasCycle: Boolean(fallback?.hasCycle),
    // A rejection may be the only record of the tasks (the cycle demo).
    rejectedTasks,
    rejected: Boolean(planRejected),
    rejectionMessage: planRejected
      ? text(planRejected.message) || text(planRejected.payload?.message) || describeEvent(planRejected)
      : "",
  };
}

function normaliseQueueItem(item) {
  if (!item || typeof item !== "object") return null;
  const id = text(item.task_id) || text(item.id);
  if (!id) return null;
  return {
    taskId: id,
    priority: finite(item.priority),
    sequence: finite(item.sequence),
  };
}

/** Fold the scheduler vocabulary into task states, queue, workers and stacks. */
export function schedulerModel(events = []) {
  const started = findEvent(events, "run_started");
  const plan = planModel(events);
  const states = new Map(
    plan.tasks.map((task) => [
      task.id,
      {
        id: task.id,
        tool: task.tool,
        priority: task.priority,
        dependsOn: [...task.dependsOn],
        state: "planned",
        attempt: null,
        durationMs: null,
        readyReason: "",
        remaining: null,
        cancelRequested: false,
        error: "",
      },
    ]),
  );

  const queue = {
    items: [],
    policy: text(started?.payload?.schedule),
    operation: "",
    seq: 0,
    recorded: false,
    lastNonEmpty: null,
  };
  const stacks = {};
  let latestStack = [];

  for (const event of events) {
    if (!event) continue;
    const payload = event.payload || {};
    const taskId = text(payload.task_id);
    const record = taskId ? states.get(taskId) : null;

    switch (event.kind) {
      case "task_ready":
        if (record) {
          record.state = "ready";
          record.readyReason = text(payload.ready_reason);
          record.remaining = finite(payload.remaining_prerequisites);
          if (finite(payload.priority) !== null) record.priority = finite(payload.priority);
        }
        break;
      case "task_dequeued":
        if (record) record.state = "dispatched";
        break;
      case "task_started":
        if (record) {
          record.state = "running";
          record.attempt = finite(payload.attempt) ?? record.attempt;
        }
        if (Array.isArray(payload.stack)) {
          stacks[taskId] = [...payload.stack];
          latestStack = [...payload.stack];
        }
        break;
      case "stack_push":
      case "stack_pop":
        if (Array.isArray(payload.stack)) {
          stacks[taskId] = [...payload.stack];
          latestStack = [...payload.stack];
        }
        break;
      case "task_completed":
        if (record) {
          record.state = "completed";
          record.durationMs = finite(payload.duration_ms);
        }
        break;
      case "task_failed":
        if (record) {
          record.state = "failed";
          record.error = text(payload.error);
          record.durationMs = finite(payload.duration_ms) ?? record.durationMs;
        }
        break;
      case "task_blocked":
        if (record) {
          record.state = "blocked";
          record.error = text(payload.failed_dependency);
        }
        break;
      case "task_cancelled":
        if (record) record.state = "cancelled";
        break;
      case "task_cancel_requested":
        if (record) record.cancelRequested = true;
        break;
      case "task_retry":
        if (record) record.state = "ready";
        break;
      case "dependency_updated":
        if (record) record.remaining = finite(payload.remaining_prerequisites);
        break;
      default:
        break;
    }

    if (Array.isArray(payload.ready_queue)) {
      queue.items = payload.ready_queue.map(normaliseQueueItem).filter(Boolean);
      queue.operation = text(payload.operation);
      queue.policy = text(payload.schedule) || queue.policy;
      queue.seq = Number(event.seq) || queue.seq;
      queue.recorded = true;
      if (queue.items.length > 0) {
        queue.lastNonEmpty = {
          items: queue.items.map((item) => ({ ...item })),
          seq: queue.seq,
          operation: queue.operation,
        };
      }
    }
  }

  const tasks = [...states.values()];
  const active = tasks.filter((task) => task.state === "running");
  const occupied = tasks.filter(
    (task) => task.state === "dispatched" || task.state === "running",
  );
  const completed = tasks.filter((task) => task.state === "completed");
  const finish = lastEvent(events, "run_finished");
  const peak = finish?.payload?.provider_max_in_flight_observed;

  return {
    plan,
    tasks,
    byId: states,
    queue: {
      ...queue,
      // FIFO snapshots record only ids, so a missing priority is a fact.
      priorityRecorded:
        queue.items.length > 0 && queue.items.every((item) => item.priority !== null),
      priorityMissingBecause: queue.policy === "fifo" ? "fifo" : "snapshot",
    },
    workers: {
      concurrency: finite(started?.payload?.concurrency),
      active: active.map((task) => task.id),
      occupied: occupied.map((task) => task.id),
      // The runtime records which tasks run together, not a worker id.
      slotOrderAvailable: false,
      maxAttempts: finite(started?.payload?.task_attempt_limit),
    },
    stacks: {
      byTask: stacks,
      latest: latestStack,
      taskCount: Object.keys(stacks).length,
    },
    concurrency: {
      active: active.length,
      capacity: finite(started?.payload?.concurrency),
      // Provider-level peak, when the run recorded one; never a guess.
      peak:
        peak && typeof peak === "object" && Object.keys(peak).length > 0
          ? Object.entries(peak).map(([provider, count]) => ({ provider, count }))
          : [],
    },
    counts: {
      total: tasks.length,
      completed: completed.length,
      running: active.length,
      queued: tasks.filter((task) => task.state === "ready").length,
      failed: tasks.filter((task) => ["failed", "blocked"].includes(task.state)).length,
      cancelled: tasks.filter((task) => task.state === "cancelled").length,
    },
    finished: Boolean(finish),
  };
}

/** Deterministic positions: column = level, row = index inside the level. */
export function layoutGraph(plan) {
  const levels = Array.isArray(plan?.levels) ? plan.levels : [];
  const { width: nodeWidth, height: nodeHeight, gutter, gap, pad } = LAB_NODE;
  const positions = new Map();
  let maxRows = 0;

  levels.forEach((level, levelIndex) => {
    level.forEach((id, rowIndex) => {
      positions.set(id, {
        level: levelIndex,
        row: rowIndex,
        x: pad + levelIndex * (nodeWidth + gutter),
        y: pad + rowIndex * (nodeHeight + gap),
      });
    });
    maxRows = Math.max(maxRows, level.length);
  });

  const width = Math.max(
    nodeWidth + pad * 2,
    pad * 2 + levels.length * nodeWidth + Math.max(0, levels.length - 1) * gutter,
  );
  const height = Math.max(
    nodeHeight + pad * 2,
    pad * 2 + maxRows * nodeHeight + Math.max(0, maxRows - 1) * gap,
  );

  const edges = [];
  for (const task of plan?.tasks || []) {
    const target = positions.get(task.id);
    if (!target) continue;
    for (const parentId of task.dependsOn) {
      const source = positions.get(parentId);
      if (!source) continue;
      const startX = source.x + nodeWidth;
      const startY = source.y + nodeHeight / 2;
      const endX = target.x;
      const endY = target.y + nodeHeight / 2;
      const middleX = startX + (endX - startX) / 2;
      edges.push({
        id: `${parentId}->${task.id}`,
        from: parentId,
        to: task.id,
        path: `M ${startX} ${startY} C ${middleX} ${startY}, ${middleX} ${endY}, ${endX} ${endY}`,
      });
    }
  }

  return { width, height, positions, edges, nodes: levels.flat() };
}

/** Recorded task ids that form a dependency cycle, for the cycle demo. */
export function cycleTasks(tasks = []) {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const visiting = new Set();
  const done = new Set();
  const path = [];
  let found = null;

  function visit(id) {
    if (found) return;
    if (visiting.has(id)) {
      found = path.slice(path.indexOf(id));
      return;
    }
    if (done.has(id)) return;
    visiting.add(id);
    path.push(id);
    for (const next of byId.get(id)?.dependsOn || []) {
      if (byId.has(next)) visit(next);
      if (found) return;
    }
    path.pop();
    visiting.delete(id);
    done.add(id);
  }

  for (const task of tasks) {
    visit(task.id);
    if (found) break;
  }
  return found || [];
}

function captionText(event) {
  const payload = event?.payload || {};
  const id = text(payload.task_id) || "task";
  switch (event?.kind) {
    case "plan_validated": {
      const tasks = Array.isArray(payload.tasks) ? payload.tasks.length : null;
      const levels = Array.isArray(payload.levels) ? payload.levels.length : null;
      if (tasks === null && levels === null) return "";
      const parts = [];
      if (tasks !== null) parts.push(`${tasks} tasks`);
      if (levels !== null) parts.push(`${levels} levels`);
      return `plan accepted: ${parts.join(" across ")}`;
    }
    case "task_ready": {
      const remaining = finite(payload.remaining_prerequisites);
      const prerequisites = Array.isArray(payload.prerequisites)
        ? payload.prerequisites.length
        : 0;
      if (remaining !== null && remaining > 0) {
        return `${id}: ${remaining} prerequisite${remaining === 1 ? "" : "s"} left`;
      }
      if (prerequisites > 0) {
        return `all ${prerequisites} prerequisites completed → ${id} enters the queue`;
      }
      return `no prerequisites → ${id} enters the queue`;
    }
    case "task_dequeued":
      return finite(payload.priority) !== null
        ? `priority ${payload.priority} dispatched: ${id}`
        : `${id} dispatched from the queue`;
    case "task_completed": {
      const duration = finite(payload.duration_ms);
      return duration === null
        ? `${id} completed; duration not recorded`
        : `${id} completed in ${formatDuration(duration)}`;
    }
    case "task_failed":
      return `${id} failed${text(payload.error) ? `: ${text(payload.error)}` : ""}`;
    case "task_cancelled":
      return `${id} cancelled${
        text(payload.recovery_action) ? `: ${humanise(payload.recovery_action)}` : ""
      }`;
    case "plan_rejected": {
      const message =
        text(payload.message) || text(event.message) || describeEvent(event);
      return /^plan rejected/i.test(message) ? message : `plan rejected: ${message}`;
    }
    case "run_finished": {
      const reason = humanise(payload.termination_reason);
      return reason ? `run finished: ${reason}` : "run finished";
    }
    case "stack_push":
      return Array.isArray(payload.stack) && payload.stack.length > 0
        ? `stack push: ${payload.stack.join(" → ")}`
        : "";
    default:
      return "";
  }
}

/** One caption per meaningful transition, throttled on recorded time only. */
export function labCaption(run, cursor) {
  const events = (run?.events || []).slice(
    0,
    Math.max(0, Math.min(Number(cursor) || 0, (run?.events || []).length)),
  );
  let candidateIndex = -1;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (CAPTION_KINDS.has(events[index]?.kind)) {
      candidateIndex = index;
      break;
    }
  }
  if (candidateIndex < 0) return null;

  const candidate = events[candidateIndex];
  const when = finite(candidate.timestamp);
  let previous = null;
  for (let index = candidateIndex - 1; index >= 0; index -= 1) {
    if (CAPTION_KINDS.has(events[index]?.kind)) {
      previous = events[index];
      break;
    }
  }

  let chosen = candidate;
  if (previous && !["run_finished", "plan_rejected"].includes(candidate.kind)) {
    const before = finite(previous.timestamp);
    if (when !== null && before !== null && when - before < LAB_CAPTION_WINDOW_MS) {
      // Keep the earlier caption rather than flickering through a burst.
      chosen = previous;
    }
  }

  const message = captionText(chosen).trim();
  if (!message) return null;
  return {
    id: `${run?.id || "run"}:${chosen.seq ?? candidateIndex + 1}`,
    seq: Number(chosen.seq) || null,
    text: message.length > 160 ? `${message.slice(0, 157)}…` : message,
  };
}
