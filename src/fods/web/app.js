"use strict";

const state = {
  config: null,
  contexts: [],
  history: [],
  runs: new Map(),
  currentRunId: null,
  selectedTask: null,
  selectedSeq: null,
  sourceCards: new Map(),
  evidence: [],
  compare: null,
  eventSource: null,
  active: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const el = (tag, className = "", text = "") => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
const current = () => state.runs.get(state.currentRunId) || null;
const currentEvents = () => current()?.events || [];
const fmtMs = (value) => {
  if (!Number.isFinite(Number(value))) return "—";
  const n = Number(value);
  return n < 1000 ? `${n.toFixed(0)} ms` : `${(n / 1000).toFixed(2)} s`;
};
const isoTime = (stamp) => {
  const date = new Date(Number(stamp) * 1000);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour12: false });
};
const httpURL = (value) => {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch { return ""; }
};
const stateLabel = (s) => ({
  completed: "completed", running: "running", failed: "failed", blocked: "blocked",
  cancelled: "cancelled", ready: "ready", planned: "planned",
})[s] || s || "planned";

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.error || `Request failed (${response.status})`);
  return body;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3200);
}

function setView(name) {
  $$(".tab").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  if (name === "execution") renderExecution();
  if (name === "lab") renderLab();
  if (name === "evidence") renderEvidence();
  if (name === "runs") refreshHistory();
}

function setStatus(status, detail = "") {
  const node = $("#run-status");
  node.className = `status-pill ${status}`;
  node.textContent = detail || ({
    idle: "No active run", starting: "Starting", running: "Running", completed: "Completed",
    partial: "Completed · partial sources", failed: "Failed", cancelled: "Cancelled", replayed: "Replay complete",
  })[status] || status;
}

function initializeTabs() {
  $$(".tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
}

async function initialize() {
  initializeTabs();
  try {
    const [config, contexts] = await Promise.all([api("/api/config"), api("/api/contexts")]);
    state.config = config;
    state.contexts = contexts.contexts;
    renderConfig();
    renderContexts();
    await refreshHistory();
    $("#connection").className = "connection ok";
    $("#connection").replaceChildren(el("i"), document.createTextNode(" API connected"));
  } catch (error) {
    $("#connection").className = "connection error";
    $("#connection").replaceChildren(el("i"), document.createTextNode(" API unavailable"));
    $("#form-error").textContent = error.message;
  }
  $("#mode").addEventListener("change", updateModeNote);
  $("#reuse-context").addEventListener("change", updateReuseControl);
  $("#saved-context").addEventListener("change", selectContext);
  $("#run-form").addEventListener("submit", submitRun);
  $("#cancel-run").addEventListener("click", cancelRun);
  $("#refresh-history").addEventListener("click", refreshHistory);
  $("#start-replay").addEventListener("click", startReplay);
  $("#demo-cycle").addEventListener("click", () => startDemo({ inject_cycle: true }, "Cycle rejection"));
  $("#demo-failure").addEventListener("click", () => startDemo({ fail_sources: ["arxiv"] }, "Bounded source failure"));
  $("#demo-citation").addEventListener("click", () => startDemo({ invalid_citation: true }, "Citation guard"));
  $("#demo-queues").addEventListener("click", startQueueComparison);
  updateModeNote();
}

function renderConfig() {
  const config = state.config;
  if (!config) return;
  $("#planner-model").textContent = config.models.structured;
  $("#answer-model").textContent = config.models.answer;
  const plannerLocal = config.providers.planner === "ollama";
  $("#planner-state").textContent = plannerLocal ? "local route" : "configured";
  $("#planner-state").className = `model-state ${plannerLocal ? "ready" : ""}`;
  const geminiReady = config.providers.answer === "gemini" && config.gemini_key_configured;
  $("#gemini-state").textContent = !geminiReady ? "key missing" : config.gemini_opted_in ? "opted in" : "opt-in required";
  $("#gemini-state").className = `model-state ${geminiReady && config.gemini_opted_in ? "ready" : "warn"}`;
  updateModeNote();
}

function updateModeNote() {
  const note = $("#mode-note");
  const live = $("#mode").value === "live";
  const selectedPlanner = $("#planner").value;
  if (!live) {
    note.className = "note";
    note.textContent = "Simulation uses fixture papers and deterministic answer drafting. No model API is called.";
  } else if (selectedPlanner === "fixture") {
    note.className = "note warning";
    note.textContent = "The plan is deterministic. Live sources run; Gemini answers only when RLA_FODS_ALLOW_GEMINI=1 is set in the server process.";
  } else if (state.config && state.config.providers.answer === "gemini" && !state.config.gemini_opted_in) {
    note.className = "note warning";
    note.textContent = "Live source calls are enabled. Gemini answer calls are currently opted out; set RLA_FODS_ALLOW_GEMINI=1 before starting the server to enable them.";
  } else {
    note.className = "note";
    note.textContent = "Live mode may call public academic sources, local Qwen for planning, and Gemini for the answer when opted in. Source outcomes can be partial.";
  }
}

function renderContexts() {
  const select = $("#saved-context");
  select.replaceChildren(new Option("Choose saved context", ""));
  for (const context of state.contexts) {
    const option = new Option(`${context.topic} · ${context.paper_count} papers`, context.topic);
    select.add(option);
  }
}

function updateReuseControl() {
  const enabled = $("#reuse-context").checked;
  $("#saved-context").disabled = !enabled;
  if (enabled) $("#saved-context").focus();
}

function selectContext() {
  const context = state.contexts.find((item) => item.topic === $("#saved-context").value);
  if (!context) return;
  $("#topic").value = context.topic;
  $("#reuse-context").checked = true;
  $("#saved-context").disabled = false;
  toast(`Follow-up will reuse ${context.paper_count} saved papers.`);
}

function runPayload(overrides = {}) {
  return {
    topic: $("#topic").value.trim(),
    question: $("#question").value.trim(),
    mode: $("#mode").value,
    planner: $("#planner").value,
    schedule: $("#schedule").value,
    concurrency: Number($("#concurrency").value),
    source_limit: Number($("#source-limit").value),
    output_name: $("#output-name").value.trim(),
    reuse_context: $("#reuse-context").checked,
    ...overrides,
  };
}

async function submitRun(event) {
  event.preventDefault();
  await launchRun(runPayload());
}

async function startDemo(options, title) {
  const payload = {
    ...runPayload({ mode: "simulate", planner: "fixture", reuse_context: false, ...options }),
    output_name: "",
    topic: $("#topic").value.trim() || "Graph Attention Networks",
    question: $("#question").value.trim() || "How does graph attention use neighborhoods?",
    delay_ms: 40,
  };
  const error = $("#form-error");
  error.textContent = "";
  try {
    await launchRun(payload, title);
  } catch (err) {
    error.textContent = err.message;
  }
}

async function launchRun(payload, title = "") {
  if (state.active) {
    toast("A run is already active. Wait for it to finish before starting another.");
    return null;
  }
  $("#form-error").textContent = "";
  const button = $("#start-run");
  button.disabled = true;
  button.textContent = "Starting…";
  state.active = true;
  setStatus("starting", title || "Starting run");
  const key = crypto.randomUUID();
  try {
    const handle = await api("/api/runs", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    });
    const run = {
      ...handle,
      title,
      events: [],
      run_kind: handle.run_kind,
      source_run_id: handle.source_run_id,
      status: handle.status,
    };
    state.runs.set(run.run_id, run);
    state.currentRunId = run.run_id;
    state.selectedTask = null;
    state.selectedSeq = null;
    state.sourceCards.clear();
    state.evidence = [];
    $("#cancel-run").disabled = false;
    setStatus("running", title ? `${title} · running` : "Running");
    connectRun(run.run_id);
    setView("execution");
    return run.run_id;
  } catch (error) {
    state.active = false;
    button.disabled = false;
    button.textContent = "Start research run";
    setStatus("failed", "Could not start");
    $("#form-error").textContent = error.message;
    throw error;
  }
}

function connectRun(runId) {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource(`/api/runs/${runId}/events`);
  state.eventSource = source;
  source.onmessage = (message) => {
    let envelope;
    try { envelope = JSON.parse(message.data); } catch { return; }
    const run = state.runs.get(runId);
    if (!run) return;
    run.run_kind = envelope.run_kind;
    run.source_run_id = envelope.source_run_id;
    const event = envelope.event;
    run.events.push(event);
    state.currentRunId = runId;
    handleRuntimeEvent(event);
    renderAll();
    if (event.kind === "run_finished") finishRun(run, event);
  };
  source.onerror = () => {
    const connection = $("#connection");
    if (source.readyState === EventSource.CLOSED) {
      connection.className = "connection error";
      connection.replaceChildren(el("i"), document.createTextNode(" Stream closed"));
    } else {
      connection.className = "connection pending";
      connection.replaceChildren(el("i"), document.createTextNode(" Reconnecting"));
    }
  };
}

function handleRuntimeEvent(event) {
  const p = event.payload || {};
  if (event.kind === "task_ready") $("#progress-label").textContent = `${p.task_id} became ready`;
  else if (event.kind === "task_started") $("#progress-label").textContent = `${p.task_id} started · attempt ${p.attempt}`;
  else if (event.kind === "context_ready") {
    $("#metric-context").textContent = fmtMs(p.elapsed_ms);
    $("#metric-papers").textContent = p.paper_count ?? "—";
    for (const paper of p.papers || []) if (paper.id) state.sourceCards.set(paper.id, paper);
    refreshContextsSoon();
  } else if (event.kind === "model_call_completed" && p.stage === "fods_answer") {
    const started = [...currentEvents()].reverse().find((item) => item.kind === "model_call_started" && item.payload?.activity_id === p.activity_id);
    const duration = started ? (event.timestamp - started.timestamp) * 1000 : null;
    $("#metric-answer").textContent = fmtMs(duration);
    $("#answer-attribution").textContent = `${p.provider} · ${p.model?.split("/").at(-1) || "model unknown"}`;
  } else if (event.kind === "citation_validation") {
    const status = $("#citation-status");
    status.className = `citation-status ${p.valid ? "valid" : "invalid"}`;
    status.textContent = p.valid
      ? `Passed · ${p.found.length} citation marker(s) match selected evidence.`
      : `Blocked · unknown citations: ${(p.unknown || []).join(", ") || "no valid citation found"}. Output write is blocked.`;
  } else if (event.kind === "brief_saved") {
    const node = $("#brief-link");
    node.replaceChildren(document.createTextNode("Saved validated brief: "));
    const link = el("a", "", p.path || "Open brief");
    link.href = `/api/runs/${state.currentRunId}/brief`;
    link.target = "_blank";
    link.rel = "noopener";
    node.append(link);
  } else if (event.kind === "tool_call_completed" && p.tool?.startsWith("search_")) {
    for (const paper of p.output_summary?.papers || []) if (paper.id) state.sourceCards.set(paper.id, paper);
  } else if (event.kind === "evidence_selected") {
    state.evidence = p.evidence || [];
  }
}

async function refreshContextsSoon() {
  try {
    const body = await api("/api/contexts");
    state.contexts = body.contexts;
    renderContexts();
  } catch { /* Current run remains inspectable if the history request drops. */ }
}

function finishRun(run, event) {
  const p = event.payload || {};
  run.status = run.run_kind === "replay" ? "replayed" : p.termination_reason === "completed_with_partial_sources" ? "partial" : p.succeeded ? "completed" : p.termination_reason === "cancelled" ? "cancelled" : "failed";
  state.active = false;
  $("#start-run").disabled = false;
  $("#start-run").textContent = "Start research run";
  $("#cancel-run").disabled = true;
  setStatus(run.status);
  $("#progress-label").textContent = p.termination_reason || event.message;
  if (state.eventSource) state.eventSource.close();
  refreshHistory();
  if (state.compare?.firstRun === run.run_id) startPriorityComparison();
  if (state.compare?.secondRun === run.run_id) renderQueueComparison();
  toast(run.status === "completed" ? "Run completed and recorded." : `Run ended: ${run.status}.`);
}

async function cancelRun() {
  const runId = state.currentRunId;
  if (!runId || !state.active) return;
  try {
    await api(`/api/runs/${runId}`, { method: "DELETE", body: "{}" });
    $("#cancel-run").disabled = true;
    toast("Cancellation requested. The runtime will record cooperative task cancellation.");
  } catch (error) { toast(error.message); }
}

function renderAll() {
  renderOverview();
  renderExecution();
  renderLab();
  renderEvidence();
}

function renderOverview() {
  const events = currentEvents();
  const taskIds = new Set(events.map((event) => event.payload?.task_id).filter(Boolean));
  const total = (events.find((event) => event.kind === "plan_validated")?.payload?.tasks || []).length;
  const terminals = new Set(events.filter((event) => ["task_completed", "task_failed", "task_blocked", "task_cancelled"].includes(event.kind)).map((event) => event.payload?.task_id));
  const pct = total ? Math.min(100, terminals.size / total * 100) : events.length ? 4 : 0;
  $("#progress-bar").style.width = `${pct}%`;
  $("#progress-count").textContent = `${events.length} events · ${taskIds.size} tasks observed`;
  const successSources = events.filter((event) => event.kind === "task_completed" && event.payload?.task_id?.startsWith("search_")).length;
  const sourceTasks = (events.find((event) => event.kind === "plan_validated")?.payload?.tasks || []).filter((task) => task.tool.startsWith("search_")).length;
  if (sourceTasks) $("#metric-sources").textContent = `${successSources}/${sourceTasks}`;
}

function getTasks(events) {
  const validated = events.find((event) => event.kind === "plan_validated");
  const planned = [...events].reverse().find((event) => event.kind === "plan_repaired") || events.find((event) => event.kind === "plan_received");
  return validated?.payload?.tasks || planned?.payload?.tasks || [];
}

function taskStates(events) {
  const states = new Map();
  for (const event of events) {
    const id = event.payload?.task_id;
    if (!id) continue;
    const map = {
      task_ready: "ready", task_started: "running", task_completed: "completed",
      task_failed: "failed", task_blocked: "blocked", task_cancelled: "cancelled",
      task_retry: "ready",
    };
    if (map[event.kind]) states.set(id, map[event.kind]);
  }
  return states;
}

function renderExecution() {
  const events = currentEvents();
  const run = current();
  $("#execution-mode").textContent = run ? `${run.run_kind === "replay" ? "Recorded event replay" : run.run_kind === "live" ? "Live execution" : "Deterministic simulation"}${run.source_run_id ? ` · source ${run.source_run_id}` : ""}` : "No run selected";
  $("#timeline-kind").textContent = run?.run_kind === "replay" ? "RECORDED TIMINGS · REPLAY" : run?.run_kind === "live" ? "LIVE RECORDED TIMINGS" : run?.run_kind === "simulate" ? "SIMULATED RECORDED TIMINGS" : "—";
  $("#event-total").textContent = `${events.length} events`;
  renderGraph(events);
  renderInspector(events);
  renderTimeline(events);
  renderEventRows(events);
}

function renderGraph(events) {
  const tasks = getTasks(events);
  const svg = $("#dag");
  const wrap = $("#dag-wrap");
  const empty = $("#graph-empty");
  svg.replaceChildren();
  if (!tasks.length) {
    empty.hidden = false;
    svg.hidden = true;
    $("#graph-count").textContent = "—";
    return;
  }
  empty.hidden = true;
  svg.hidden = false;
  const validated = events.find((event) => event.kind === "plan_validated");
  const levels = validated?.payload?.levels;
  let columns;
  if (Array.isArray(levels) && levels.length) {
    const byId = new Map(tasks.map((task) => [task.id, task]));
    columns = levels.map((ids) => ids.map((id) => byId.get(id)).filter(Boolean));
  } else {
    columns = [tasks];
  }
  const xGap = 205, yGap = 86, x0 = 18, y0 = 32, cardW = 172, cardH = 54;
  const maxRows = Math.max(1, ...columns.map((column) => column.length));
  const width = Math.max(500, x0 * 2 + columns.length * xGap);
  const height = Math.max(190, y0 * 2 + maxRows * yGap);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  wrap.style.minHeight = `${Math.min(height, 520)}px`;
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "arrow"); marker.setAttribute("markerWidth", "8"); marker.setAttribute("markerHeight", "8"); marker.setAttribute("refX", "7"); marker.setAttribute("refY", "3"); marker.setAttribute("orient", "auto");
  const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path"); arrow.setAttribute("d", "M0,0 L0,6 L7,3 z"); arrow.setAttribute("fill", "#9db3c0"); marker.append(arrow); defs.append(marker); svg.append(defs);
  const positions = new Map();
  columns.forEach((column, col) => column.forEach((task, row) => {
    const y = y0 + (row + (maxRows - column.length) / 2) * yGap;
    positions.set(task.id, { x: x0 + col * xGap, y });
  }));
  const states = taskStates(events);
  const completedIds = new Set(events.filter((event) => event.kind === "task_completed").map((event) => event.payload?.task_id));
  for (const task of tasks) {
    const target = positions.get(task.id);
    for (const parentId of task.depends_on || []) {
      const source = positions.get(parentId);
      if (!source || !target) continue;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${source.x + cardW} ${source.y + cardH / 2} C ${source.x + xGap / 2} ${source.y + cardH / 2}, ${target.x - xGap / 2} ${target.y + cardH / 2}, ${target.x} ${target.y + cardH / 2}`);
      path.setAttribute("class", `dag-edge ${completedIds.has(parentId) ? "done" : ""}`);
      path.dataset.task = task.id;
      svg.append(path);
    }
  }
  for (const task of tasks) {
    const pos = positions.get(task.id);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const taskState = states.get(task.id) || "planned";
    group.setAttribute("class", `dag-node ${taskState} ${state.selectedTask === task.id ? "selected" : ""}`);
    group.setAttribute("transform", `translate(${pos.x},${pos.y})`);
    group.setAttribute("tabindex", "0"); group.setAttribute("role", "button"); group.setAttribute("aria-label", `${task.id}, ${task.tool}, ${taskState}`);
    group.addEventListener("click", () => selectTask(task.id));
    group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectTask(task.id); } });
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect"); rect.setAttribute("width", cardW); rect.setAttribute("height", cardH); group.append(rect);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "text"); title.setAttribute("x", "10"); title.setAttribute("y", "20"); title.setAttribute("class", "dag-label"); title.textContent = task.id; group.append(title);
    const tool = document.createElementNS("http://www.w3.org/2000/svg", "text"); tool.setAttribute("x", "10"); tool.setAttribute("y", "37"); tool.setAttribute("class", "dag-tool"); tool.textContent = `${task.tool} · ${stateLabel(taskState)}`; group.append(tool);
    svg.append(group);
  }
  $("#graph-count").textContent = `${tasks.length} tasks · ${validated ? `${columns.length} levels` : "rejected / unvalidated plan"}`;
}

function selectTask(taskId) {
  state.selectedTask = taskId;
  const relevant = currentEvents().filter((event) => event.payload?.task_id === taskId);
  state.selectedSeq = relevant.at(-1)?.seq || null;
  renderExecution();
}

function renderInspector(events) {
  const target = $("#inspector-content");
  target.replaceChildren();
  const taskId = state.selectedTask;
  const tasks = getTasks(events);
  if (taskId) {
    const task = tasks.find((item) => item.id === taskId);
    const taskEvents = events.filter((event) => event.payload?.task_id === taskId);
    if (task) {
      target.append(el("h3", "", `${task.id} · ${task.tool}`));
      const states = taskStates(events);
      const firstStart = taskEvents.find((event) => event.kind === "task_started");
      const terminal = [...taskEvents].reverse().find((event) => ["task_completed", "task_failed", "task_blocked", "task_cancelled"].includes(event.kind));
      const duration = terminal?.payload?.duration_ms ?? (firstStart && terminal ? (terminal.timestamp - firstStart.timestamp) * 1000 : null);
      const data = [
        ["State", stateLabel(states.get(taskId) || "planned")], ["Attempt", terminal?.payload?.attempt || firstStart?.payload?.attempt || 0],
        ["Duration", fmtMs(duration)], ["Priority", task.priority ?? 0],
        ["Dependencies", (task.depends_on || []).join(", ") || "none"],
        ["Ready proof", taskEvents.find((event) => event.kind === "task_ready")?.payload?.ready_reason || "awaiting prerequisites"],
      ];
      const grid = el("div", "detail-grid");
      for (const [label, value] of data) { const cell = el("div"); cell.append(el("small", "", label), el("strong", "", value)); grid.append(cell); }
      target.append(grid);
      const validated = taskEvents.find((event) => event.kind === "tool_call_validated");
      if (validated) target.append(el("pre", "json-detail", JSON.stringify(validated.payload.arguments, null, 2)));
      const finalEvent = terminal || taskEvents.at(-1);
      if (finalEvent) target.append(el("pre", "json-detail", JSON.stringify(finalEvent.payload, null, 2)));
      return;
    }
  }
  const selected = events.find((event) => event.seq === state.selectedSeq);
  if (!selected) { target.className = "empty"; target.textContent = "Choose a task or event."; return; }
  target.className = "";
  target.append(el("h3", "", selected.kind));
  target.append(el("p", "concept-copy", selected.message));
  target.append(el("pre", "json-detail", JSON.stringify(selected.payload, null, 2)));
}

function renderTimeline(events) {
  const target = $("#timeline");
  target.replaceChildren();
  const tasks = getTasks(events);
  if (!tasks.length) { target.append(el("div", "empty", "No task timings recorded.")); return; }
  const startEvents = new Map(events.filter((event) => event.kind === "task_started").map((event) => [event.payload.task_id, event]));
  const terminalKinds = ["task_completed", "task_failed", "task_blocked", "task_cancelled"];
  const endEvents = new Map(events.filter((event) => terminalKinds.includes(event.kind)).map((event) => [event.payload.task_id, event]));
  const taskRuns = tasks.map((task) => ({ task, start: startEvents.get(task.id), end: endEvents.get(task.id) })).filter((item) => item.start);
  if (!taskRuns.length) { target.append(el("div", "empty", "Tasks are planned; none has started.")); return; }
  const startAt = Math.min(...taskRuns.map((item) => item.start.timestamp));
  const endAt = Math.max(...taskRuns.map((item) => item.end?.timestamp || Date.now() / 1000));
  const span = Math.max(.001, endAt - startAt);
  for (const item of taskRuns) {
    const end = item.end?.timestamp || endAt;
    const row = el("div", "time-row");
    row.addEventListener("click", () => selectTask(item.task.id));
    row.append(el("span", "time-label", `${item.task.id} · ${item.task.tool}`));
    const track = el("div", "time-track");
    const bar = el("div", `time-bar ${item.end?.kind === "task_failed" || item.end?.kind === "task_blocked" ? "failed" : item.end?.kind === "task_cancelled" ? "cancelled" : item.end ? "" : "running"}`);
    bar.style.left = `${((item.start.timestamp - startAt) / span) * 100}%`;
    bar.style.width = `${Math.max(.5, ((end - item.start.timestamp) / span) * 100)}%`;
    track.append(bar); row.append(track);
    row.append(el("span", "time-value", fmtMs(item.end ? item.end.payload?.duration_ms ?? (end - item.start.timestamp) * 1000 : (Date.now() / 1000 - item.start.timestamp) * 1000)));
    row.append(el("span", "time-state", stateLabel(item.end?.kind?.replace("task_", "") || "running")));
    target.append(row);
  }
}

function renderEventRows(events) {
  const body = $("#event-rows"); body.replaceChildren();
  if (!events.length) { const row = el("tr"); const cell = el("td", "empty", "No events yet."); cell.colSpan = 5; row.append(cell); body.append(row); return; }
  for (const event of events) {
    const p = event.payload || {};
    const row = el("tr", state.selectedSeq === event.seq ? "selected" : "");
    row.addEventListener("click", () => { state.selectedSeq = event.seq; state.selectedTask = p.task_id || null; renderExecution(); });
    row.append(el("td", "", event.seq), el("td", "", isoTime(event.timestamp)), el("td", "event-name", event.kind), el("td", "", p.task_id || p.activity_id || p.stage || "runtime"), el("td", "event-message", event.message));
    body.append(row);
  }
}

function renderLab() {
  const events = currentEvents();
  const tasks = getTasks(events);
  const counts = events.find((event) => event.kind === "plan_validated")?.payload?.dependency_counts || {};
  const deps = $("#dependency-map"); deps.replaceChildren();
  if (!tasks.length) { deps.className = "data-list empty"; deps.textContent = "Waiting for an accepted plan."; }
  else {
    deps.className = "data-list";
    for (const task of tasks) {
      const ready = events.find((event) => event.kind === "task_ready" && event.payload?.task_id === task.id);
      const row = el("div", "data-row");
      row.append(el("code", "", task.id), el("span", "", `in-degree ${counts[task.id] ?? (task.depends_on || []).length} · depends on ${(task.depends_on || []).join(", ") || "none"}`), el("span", "state-label", ready ? `ready · ${ready.payload.remaining_prerequisites} left` : "waiting"));
      deps.append(row);
    }
  }
  const depEvents = $("#dependency-events"); depEvents.replaceChildren();
  const updates = events.filter((event) => event.kind === "dependency_updated");
  for (const event of updates.slice(-12)) depEvents.append(el("div", "", `#${event.seq} ${event.payload.completed_dependency} → ${event.payload.task_id}: ${event.payload.remaining_prerequisites} remaining (${event.payload.readiness_rule})`));
  if (!updates.length) depEvents.textContent = events.some((event) => event.kind === "plan_rejected") ? "Cycle was rejected before task dispatch." : "Dependency updates appear as prerequisites complete.";

  const queueList = $("#queue-list"); queueList.replaceChildren();
  const qEvents = events.filter((event) => event.kind === "queue_updated");
  $("#queue-policy").textContent = events.find((event) => event.kind === "plan_validated")?.payload?.schedule || "—";
  if (!qEvents.length) { queueList.className = "queue-list empty"; queueList.textContent = "No queue operations recorded."; }
  else {
    queueList.className = "queue-list";
    for (const event of qEvents.slice(-16)) {
      const row = el("div", "queue-item");
      const queued = (event.payload.ready_queue || []).map((entry) => entry.task_id).join(", ") || "empty";
      row.append(el("b", "", event.payload.operation), el("span", "", `${event.payload.task_id} · queue: ${queued}`), el("small", "", `${event.payload.schedule}${event.payload.priority !== undefined ? ` · priority ${event.payload.priority}` : ""}`));
      queueList.append(row);
    }
  }

  const stateMap = $("#state-map"); stateMap.replaceChildren();
  const taskState = taskStates(events);
  if (!tasks.length) { stateMap.className = "data-list empty"; stateMap.textContent = "No task state recorded."; }
  else {
    stateMap.className = "data-list";
    for (const task of tasks) {
      const taskEvents = events.filter((event) => event.payload?.task_id === task.id);
      const attempts = Math.max(0, ...taskEvents.map((event) => Number(event.payload?.attempt || 0)));
      const completed = [...taskEvents].reverse().find((event) => event.kind === "task_completed");
      const output = completed?.payload?.result_summary;
      const outputText = output ? ` · out ${JSON.stringify(output)}` : "";
      const row = el("div", "data-row");
      row.append(el("code", "", task.id), el("span", "", `${task.tool} · attempts ${attempts}${outputText}`), el("span", "state-label", stateLabel(taskState.get(task.id) || "planned")));
      stateMap.append(row);
    }
  }

  const stack = $("#stack-list"); stack.replaceChildren();
  const stackEvents = events.filter((event) => event.kind === "stack_push" || event.kind === "stack_pop");
  if (!stackEvents.length) { stack.className = "stack-list empty"; stack.textContent = "No stack frames recorded."; }
  else {
    stack.className = "stack-list";
    for (const event of stackEvents.slice(-20).reverse()) {
      const row = el("div", "stack-item");
      row.append(el("span", "", event.kind === "stack_push" ? "push" : event.payload?.failed ? "unwind" : "pop"), el("code", "", (event.payload?.stack || []).at(-1) || event.message), el("small", "", `#${event.seq}`));
      stack.append(row);
    }
  }
  const recoveries = events.filter((event) => ["task_retry", "recovery_decision", "task_blocked", "task_cancelled", "partial_source_set", "run_cancel_requested"].includes(event.kind));
  $("#recovery-status").textContent = recoveries.length ? `${recoveries.length} decisions` : "No failures";
  $("#recovery-status").className = `tag ${recoveries.some((event) => event.kind === "task_failed") ? "warn" : ""}`;
  renderQueueComparison();
}

function renderQueueComparison() {
  const target = $("#queue-comparison-detail");
  if (!state.compare) return;
  const first = state.runs.get(state.compare.firstRun);
  const second = state.compare.secondRun ? state.runs.get(state.compare.secondRun) : null;
  target.className = "compare-grid";
  target.replaceChildren();
  target.append(queueBox("FIFO queue", first, "FIFO"));
  target.append(queueBox("Priority queue", second, "PRIORITY"));
}

function queueBox(title, run, policy) {
  const box = el("div", "compare-box"); box.append(el("h3", "", title));
  if (!run) { box.append(el("p", "compare-order", "Waiting for the first run…")); return box; }
  const order = run.events.filter((event) => event.kind === "task_dequeued").map((event) => {
    const task = getTasks(run.events).find((item) => item.id === event.payload.task_id);
    return `${event.payload.task_id}${policy === "PRIORITY" ? ` (p${task?.priority ?? 0})` : ""}`;
  });
  box.append(el("p", "compare-order", order.length ? order.join(" → ") : run.status === "running" ? "Scheduler running…" : "No dispatch recorded"));
  box.append(el("small", "", `${run.run_kind} · ${run.status}`));
  return box;
}

async function startQueueComparison() {
  if (state.active) return toast("Wait for the active run before starting the comparison.");
  state.compare = { firstRun: null, secondRun: null };
  const payload = {
    topic: "FODS ready-queue comparison",
    question: "What evidence is available for graph attention networks?",
    mode: "simulate", planner: "fixture", schedule: "fifo", concurrency: 1,
    source_limit: 3, output_name: "", delay_ms: 10,
  };
  try {
    state.compare.firstRun = await launchRun(payload, "FIFO queue comparison");
    renderQueueComparison();
  } catch (error) { toast(error.message); }
}

async function startPriorityComparison() {
  if (!state.compare || state.compare.secondRun) return;
  const payload = {
    topic: "FODS ready-queue comparison",
    question: "What evidence is available for graph attention networks?",
    mode: "simulate", planner: "fixture", schedule: "priority", concurrency: 1,
    source_limit: 3, output_name: "", delay_ms: 10,
  };
  try {
    state.compare.secondRun = await launchRun(payload, "Priority queue comparison");
    renderQueueComparison();
  } catch (error) { toast(error.message); }
}

function renderEvidence() {
  const events = currentEvents();
  const context = [...events].reverse().find((event) => event.kind === "context_ready");
  $("#context-meta").textContent = context ? `${context.payload.paper_count} papers · ${context.payload.abstract_count} abstracts · ${context.payload.source_names?.join(", ") || "saved context"}${context.payload.duplicates_merged ? ` · ${context.payload.duplicates_merged} duplicates merged` : ""}` : "No context loaded.";
  $("#context-hash").textContent = context?.payload.context_hash ? `${context.payload.context_hash.slice(0, 12)}…` : "—";
  const papers = $("#papers"); papers.replaceChildren();
  const records = [...state.sourceCards.values()];
  if (!records.length) { papers.className = "paper-list empty"; papers.textContent = "Run source tasks or load saved context."; }
  else {
    papers.className = "paper-list";
    for (const paper of records) papers.append(paperCard(paper, ""));
  }
  const selected = $("#selected-cards"); selected.replaceChildren();
  const selectionEvent = [...events].reverse().find((event) => event.kind === "evidence_selected");
  const evidence = state.evidence.length ? state.evidence : selectionEvent?.payload?.evidence || [];
  if (!evidence.length) { selected.className = "paper-list empty"; selected.textContent = "No retrieved evidence yet."; }
  else {
    selected.className = "paper-list";
    for (const item of evidence) {
      const paper = item.paper || item;
      const card = paperCard(paper, item.citation || "");
      card.id = `evidence-${item.citation || paper.id}`;
      selected.append(card);
    }
  }
  const answer = [...events].reverse().find((event) => event.kind === "answer_ready");
  const answerNode = $("#answer-content"); answerNode.replaceChildren();
  if (!answer) { answerNode.className = "answer-content empty"; answerNode.textContent = "The cited answer will appear here."; }
  else { answerNode.className = "answer-content"; renderCitedAnswer(answerNode, answer.payload.answer || ""); }
  const validation = [...events].reverse().find((event) => event.kind === "citation_validation");
  const citationNode = $("#citation-status");
  if (validation) {
    citationNode.className = `citation-status ${validation.payload.valid ? "valid" : "invalid"}`;
    citationNode.textContent = validation.payload.valid ? `Passed · ${validation.payload.found.length} citation marker(s) match selected evidence.` : `Blocked · ${(validation.payload.unknown || []).join(", ") || "invalid citation"}. Output write is blocked.`;
  }
}

function paperCard(paper, citation) {
  const card = el("article", "paper-card");
  if (citation) card.dataset.citation = citation;
  const title = el("h3", "", paper.title || "Untitled paper");
  card.append(title);
  const sourceNames = paper.sources || paper.source_names || [];
  card.append(el("p", "paper-meta", `${citation ? `${citation} · ` : ""}${paper.year || "Year unknown"}${paper.venue ? ` · ${paper.venue}` : ""}${sourceNames.length ? ` · ${sourceNames.join(", ")}` : ""}`));
  if (paper.abstract) card.append(el("p", "paper-abstract", paper.abstract));
  const links = el("div", "paper-links");
  if (paper.doi) { const a = el("a", "", `DOI ${paper.doi}`); a.href = `https://doi.org/${encodeURIComponent(paper.doi)}`; a.target = "_blank"; a.rel = "noopener noreferrer"; links.append(a); }
  const sourceURL = httpURL(paper.url || "");
  if (sourceURL) { const a = el("a", "", "Open source"); a.href = sourceURL; a.target = "_blank"; a.rel = "noopener noreferrer"; links.append(a); }
  if (links.childNodes.length) card.append(links);
  return card;
}

function renderCitedAnswer(target, text) {
  const regex = /\[(P\d+)\]/g;
  let previous = 0, match;
  while ((match = regex.exec(text))) {
    target.append(document.createTextNode(text.slice(previous, match.index)));
    const button = el("button", "citation-link", `[${match[1]}]`);
    button.type = "button";
    button.setAttribute("aria-label", `Inspect evidence ${match[1]}`);
    button.addEventListener("click", () => revealEvidence(match[1]));
    target.append(button);
    previous = regex.lastIndex;
  }
  target.append(document.createTextNode(text.slice(previous)));
}

function revealEvidence(citation) {
  setView("evidence");
  const card = $(`#evidence-${CSS.escape(citation)}`);
  if (card) {
    card.classList.add("highlight");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => card.classList.remove("highlight"), 2400);
  } else {
    toast(`No selected evidence card is recorded for ${citation}.`);
  }
}

async function refreshHistory() {
  try {
    const body = await api("/api/history");
    state.history = body.runs;
    renderHistory();
  } catch (error) { $("#history-rows").replaceChildren(el("tr", "", error.message)); }
}

function renderHistory() {
  const body = $("#history-rows"); body.replaceChildren();
  const select = $("#replay-run"); const selected = select.value;
  select.replaceChildren(new Option("Choose a JSONL run", ""));
  if (!state.history.length) { const row = el("tr"); const cell = el("td", "empty", "No recorded runs found."); cell.colSpan = 8; row.append(cell); body.append(row); return; }
  for (const run of state.history) {
    const option = new Option(`${run.run_id} · ${run.topic || "untitled"} · ${run.mode}`, run.run_id);
    select.add(option);
    const row = el("tr");
    const models = (run.models_used || []).map((item) => `${item.provider}/${item.model?.split("/").at(-1)} (${item.stage})`).join(" · ") || "No traced model calls";
    const artifact = el("span");
    if (run.output_path) { const link = el("a", "", "Brief"); link.href = `/api/runs/${run.run_id}/brief`; link.target = "_blank"; link.rel = "noopener"; artifact.append(link, document.createTextNode(" · ")); }
    const visual = el("a", "", "Run view"); visual.href = run.visualization_url; visual.target = "_blank"; visual.rel = "noopener"; artifact.append(visual);
    const replay = el("button", "button secondary", "Replay"); replay.type = "button"; replay.addEventListener("click", () => replayRun(run.run_id));
    const action = el("td"); action.append(replay);
    row.append(el("td", "", run.run_id), el("td", "", run.mode), el("td", "", run.status), el("td", "", run.topic || "—"), el("td", "", models), el("td", "", fmtMs(run.elapsed_ms)), el("td", "", ""), action);
    row.children[6].replaceChildren(artifact);
    body.append(row);
  }
  if (selected) select.value = selected;
}

async function startReplay() {
  const id = $("#replay-run").value;
  if (!id) return toast("Choose a recorded run first.");
  await replayRun(id);
}

async function replayRun(runId) {
  if (state.active) return toast("Wait for the active run before starting replay.");
  try {
    const handle = await api("/api/replay", { method: "POST", body: JSON.stringify({ run_id: runId, speed_ms: Number($("#replay-speed").value || 0) }) });
    const run = { ...handle, events: [], run_kind: "replay", status: "starting" };
    state.runs.set(run.run_id, run);
    state.currentRunId = run.run_id;
    state.selectedTask = null; state.selectedSeq = null; state.sourceCards.clear(); state.evidence = [];
    state.active = true;
    setStatus("running", "Recorded replay");
    $("#start-run").disabled = true;
    connectRun(run.run_id);
    setView("execution");
  } catch (error) { toast(error.message); }
}

initialize();
