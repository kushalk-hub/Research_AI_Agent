"use strict";

(() => {
  const legacy = new URLSearchParams(location.search).has("legacy");
  const modernRoot = document.querySelector("#modern-shell");
  const legacyRoot = document.querySelector("#legacy-app");
  if (legacy) {
    modernRoot.hidden = true;
    legacyRoot.hidden = false;
    return;
  }

  const core = window.FODSFrontendCore;
  const state = {
    history: [],
    contexts: [],
    runs: new Map(),
    currentRunId: null,
    cursor: 0,
    selectedTask: null,
    followLive: true,
    playbackTimer: null,
    comparison: null,
    active: false,
    config: null,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const currentRun = () => state.runs.get(state.currentRunId) || null;
  const currentEvents = () => currentRun()?.events || [];
  const escapeSelector = (value) => CSS.escape(String(value));

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) throw new Error(body?.error || `Request failed (${response.status})`);
    return body;
  }

  function setView(name) {
    $$(".shell-nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    $$(".shell-view").forEach((view) => view.classList.toggle("active", view.id === `shell-view-${name}`));
  }

  function displayMode(run) {
    return core.executionLabel(run);
  }

  function setConnection(message, ok = false) {
    const node = $("#shell-connection");
    node.textContent = message;
    node.className = `shell-connection ${ok ? "ok" : "error"}`;
  }

  function appendText(parent, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = String(text ?? "");
    parent.append(node);
    return node;
  }

  function initialize() {
    $$(".shell-nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $("#shell-new-run").addEventListener("click", () => {
      setView("chat");
      $("#shell-question").focus();
    });
    $("#shell-refresh-history").addEventListener("click", loadHistory);
    $("#shell-library-refresh").addEventListener("click", loadInitialData);
    $("#shell-run-form").addEventListener("submit", submitRun);
    $("#shell-mode").addEventListener("change", renderModeNote);
    $("#shell-fresh-sources").addEventListener("change", renderModeNote);
    $("#shell-reuse-context").addEventListener("change", renderContextControl);
    $("#shell-context").addEventListener("change", selectContext);
    $("#shell-event-cursor").addEventListener("input", (event) => {
      state.followLive = false;
      setCursor(Number(event.target.value));
    });
    $("#shell-trace-filter").addEventListener("input", renderTrace);
    $("#shell-trace-kind").addEventListener("change", renderTrace);
    $("#shell-step-back").addEventListener("click", () => step(-1));
    $("#shell-step-forward").addEventListener("click", () => step(1));
    $("#shell-reset").addEventListener("click", () => { stopPlayback(); state.followLive = false; setCursor(0); });
    $("#shell-play").addEventListener("click", startPlayback);
    $("#shell-pause").addEventListener("click", stopPlayback);
    $("#shell-viz-follow").addEventListener("click", toggleFollow);
    $("#shell-compare-schedulers")?.addEventListener("click", compareSchedulers);
    $("#shell-demo-cycle")?.addEventListener("click", () => runControlledScenario({ inject_cycle: true }));
    $("#shell-demo-failure")?.addEventListener("click", () => runControlledScenario({ fail_sources: ["arxiv"] }));
    $("#shell-demo-citation")?.addEventListener("click", () => runControlledScenario({ invalid_citation: true }));
    loadInitialData();
  }

  async function loadInitialData() {
    try {
      const [health, contexts, config] = await Promise.all([
        request("/api/health"), request("/api/contexts"), request("/api/config"),
      ]);
      state.contexts = contexts.contexts || [];
      state.config = config;
      renderContexts();
      renderProviderReadiness();
      await loadHistory();
      setConnection(health.ok ? "Runtime connected" : "Runtime unavailable", Boolean(health.ok));
    } catch (error) {
      setConnection("Runtime unavailable");
      $("#shell-error").textContent = error.message;
    }
  }

  async function loadHistory() {
    try {
      const body = await request("/api/history");
      state.history = body.runs || [];
      renderHistory();
    } catch (error) {
      $("#shell-history").replaceChildren();
      appendText($("#shell-history"), "p", "shell-muted", error.message);
    }
  }

  function renderHistory() {
    const target = $("#shell-history");
    target.replaceChildren();
    if (!state.history.length) {
      appendText(target, "p", "shell-muted", "No saved runs yet.");
      renderLibrary();
      return;
    }
    for (const run of state.history) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `shell-history-item ${state.currentRunId === run.run_id ? "selected" : ""}`;
      button.setAttribute("aria-label", `Replay ${run.topic || "research run"}, ${run.mode} mode`);
      appendText(button, "strong", "", run.topic || "Untitled run");
      appendText(button, "span", "shell-history-meta", `${run.mode} · ${run.status}`);
      appendText(button, "small", "", run.run_id);
      button.addEventListener("click", () => replayRun(run.run_id));
      target.append(button);
    }
    renderLibrary();
  }

  function renderContexts() {
    const select = $("#shell-context");
    select.replaceChildren(new Option("Choose topic context", ""));
    for (const context of state.contexts) {
      select.add(new Option(`${context.topic} · ${context.paper_count} papers`, context.context_hash));
    }
    renderLibrary();
  }

  function renderLibrary() {
    const runs = $("#shell-library-runs");
    const contexts = $("#shell-library-contexts");
    if (!runs || !contexts) return;
    runs.replaceChildren();
    contexts.replaceChildren();
    if (!state.history.length) appendText(runs, "p", "shell-muted", "No persisted investigations found.");
    for (const item of state.history) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shell-history-item";
      appendText(button, "strong", "", item.topic || "Untitled investigation");
      appendText(button, "span", "shell-history-meta", `${item.mode} · ${item.status} · ${item.event_count} events`);
      appendText(button, "small", "", item.run_id);
      button.addEventListener("click", () => replayRun(item.run_id));
      runs.append(button);
    }
    if (!state.contexts.length) appendText(contexts, "p", "shell-muted", "No saved research contexts found.");
    for (const item of state.contexts) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shell-context-item";
      appendText(button, "strong", "", item.topic || "Untitled topic");
      appendText(button, "span", "", `${item.paper_count} papers · ${item.abstract_count} abstracts`);
      appendText(button, "small", "", item.context_hash || "Context ID not recorded");
      button.addEventListener("click", () => {
        $("#shell-topic").value = item.topic || "";
        $("#shell-context").value = item.context_hash || "";
        $("#shell-reuse-context").checked = true;
        renderContextControl();
        setView("chat");
        $("#shell-question").focus();
      });
      contexts.append(button);
    }
  }

  function renderContextControl() {
    const select = $("#shell-context");
    select.disabled = !$("#shell-reuse-context").checked;
  }

  function renderProviderReadiness() {
    const target = $("#shell-provider-readiness");
    if (!target || !state.config) return;
    target.replaceChildren();
    for (const [label, role] of [["Planner", "planner"], ["Answer model", "answer"]]) {
      const row = document.createElement("div");
      row.className = "shell-provider-row";
      appendText(row, "strong", "", label);
      appendText(row, "span", "", state.config.models?.[role] || "Not configured");
      appendText(row, "small", "", "Configured · reachability not checked");
      target.append(row);
    }
    const access = document.createElement("p");
    access.className = "shell-muted";
    access.textContent = state.config.gemini_key_configured
      ? "Gemini credential configured on server; its use still follows the FODS opt-in setting."
      : "No Gemini credential configured on server.";
    target.append(access);
  }

  function selectContext() {
    const context = state.contexts.find((item) => item.context_hash === $("#shell-context").value);
    if (!context) return;
    $("#shell-topic").value = context.topic || "";
    $("#shell-reuse-context").checked = true;
    renderContextControl();
  }

  function renderModeNote() {
    const live = $("#shell-mode").value === "live";
    $("#shell-mode-note").textContent = live
      ? "Live research uses the configured planner and academic sources. Provider failures are shown in the run trace."
      : "Simulation uses deterministic fixture papers and answer drafting. No fresh academic retrieval or model call is made.";
    const banner = $("#shell-data-banner");
    banner.hidden = live;
    banner.textContent = live ? "" : "SIMULATION · Fixture papers are not real research results.";
    if (live && $("#shell-fresh-sources").checked) {
      $("#shell-mode-note").textContent = "Fresh live research bypasses the source cache. Configured providers and academic sources are required; failures remain visible.";
    }
  }

  async function submitRun(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      topic: $("#shell-topic").value.trim() || $("#shell-question").value.trim().slice(0, 90),
      question: $("#shell-question").value.trim(),
      mode: $("#shell-mode").value,
      planner: $("#shell-planner").value,
      schedule: $("#shell-schedule").value,
      concurrency: Number($("#shell-concurrency").value),
      source_limit: Number($("#shell-source-limit").value),
      output_name: $("#shell-output-name").value.trim(),
      reuse_context: $("#shell-reuse-context").checked,
      context_id: $("#shell-reuse-context").checked ? $("#shell-context").value : "",
      fresh_sources: $("#shell-fresh-sources").checked,
    };
    try {
      await startRun(payload);
      form.reset();
      renderContextControl();
      renderModeNote();
    } catch (error) {
      $("#shell-error").textContent = error.message;
    }
  }

  async function startRun(payload, onFinished = null) {
    if (state.active) throw new Error("Wait for the current run to finish before starting another.");
    stopPlayback();
    state.active = true;
    state.followLive = true;
    $("#shell-error").textContent = "";
    $("#shell-submit").disabled = true;
    let handle;
    try {
      handle = await request("/api/runs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      state.active = false;
      $("#shell-submit").disabled = false;
      throw error;
    }
    const run = { ...handle, mode: payload.mode, run_kind: payload.mode, events: [], title: payload.topic };
    state.runs.set(run.run_id, run);
    state.currentRunId = run.run_id;
    state.cursor = 0;
    state.selectedTask = null;
    state.onRunFinished = onFinished;
    renderAll();
    setView("trace");
    connectEvents(run.run_id);
    return run;
  }

  function connectEvents(runId) {
    if (state.eventSource) state.eventSource.close();
    const run = state.runs.get(runId);
    const source = new EventSource(run.events_url || `/api/runs/${runId}/events`);
    state.eventSource = source;
    source.onmessage = (message) => {
      let envelope;
      try { envelope = JSON.parse(message.data); } catch { return; }
      const activeRun = state.runs.get(runId);
      if (!activeRun) return;
      if (envelope.run_kind) activeRun.run_kind = envelope.run_kind;
      if (envelope.source_run_id) activeRun.source_run_id = envelope.source_run_id;
      activeRun.events.push(envelope.event);
      if (state.currentRunId === runId) {
        if (state.followLive) state.cursor = activeRun.events.length;
        renderAll();
      }
      if (envelope.event.kind === "run_finished") finishRun(activeRun, envelope.event);
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setConnection("Event stream closed");
    };
  }

  function finishRun(run, event) {
    run.status = run.run_kind === "replay" ? "replayed" : event.payload?.succeeded ? "completed" : "failed";
    if (state.currentRunId === run.run_id) {
      state.active = false;
      $("#shell-submit").disabled = false;
      state.cursor = run.events.length;
      renderAll();
    }
    loadHistory();
    const callback = state.onRunFinished;
    state.onRunFinished = null;
    if (callback) callback(run);
  }

  async function replayRun(sourceRunId) {
    if (state.active) return;
    try {
      stopPlayback();
      const handle = await request("/api/replay", {
        method: "POST",
        body: JSON.stringify({ run_id: sourceRunId, speed_ms: 0 }),
      });
      const run = { ...handle, mode: "replay", run_kind: "replay", events: [], source_run_id: sourceRunId };
      state.runs.set(run.run_id, run);
      state.currentRunId = run.run_id;
      state.cursor = 0;
      state.followLive = true;
      state.active = true;
      connectEvents(run.run_id);
      renderAll();
      setView("trace");
    } catch (error) {
      $("#shell-error").textContent = error.message;
      setView("chat");
    }
  }

  function snapshot() {
    return core.deriveSnapshot(currentEvents(), state.cursor);
  }

  function setCursor(value) {
    state.cursor = core.clampCursor(value, currentEvents().length);
    renderAll();
  }

  function step(direction) {
    stopPlayback();
    state.followLive = false;
    setCursor(core.stepCursor(state.cursor, direction, currentEvents().length));
  }

  function startPlayback() {
    stopPlayback();
    state.followLive = false;
    const delay = Number($("#shell-speed").value) || 350;
    state.playbackTimer = setInterval(() => {
      if (state.cursor >= currentEvents().length) return stopPlayback();
      setCursor(state.cursor + 1);
    }, delay);
  }

  function stopPlayback() {
    if (state.playbackTimer) clearInterval(state.playbackTimer);
    state.playbackTimer = null;
  }

  function toggleFollow() {
    state.followLive = !state.followLive;
    $("#shell-viz-follow").setAttribute("aria-pressed", String(state.followLive));
    $("#shell-viz-follow").textContent = state.followLive ? "Following live events" : "Follow live events";
    if (state.followLive) setCursor(currentEvents().length);
  }

  function renderAll() {
    renderProvenance();
    renderChat();
    renderTrace();
    renderVisualizer();
    renderHistory();
  }

  function renderProvenance() {
    const run = currentRun();
    for (const selector of ["#shell-mode-badge", "#shell-trace-mode", "#shell-viz-mode"]) {
      $(selector).textContent = displayMode(run);
    }
    $("#shell-run-id").textContent = run ? `${run.source_run_id ? `source ${run.source_run_id} · ` : ""}${run.run_id}` : "No run selected";
    $("#shell-trace-count").textContent = `${currentEvents().length} events`;
    const validated = [...currentEvents()].reverse().find((event) => event.kind === "plan_validated");
    $("#shell-viz-schedule").textContent = validated?.payload?.schedule || "—";
  }

  function renderPlan(data) {
    const target = $("#shell-plan-tasks");
    target.replaceChildren();
    if (!data.tasks.length) return appendText(target, "p", "shell-muted", "The runtime plan will appear here.");
    $("#shell-plan-summary").textContent = `${data.tasks.length} tasks · ${data.events.find((event) => event.kind === "plan_validated")?.payload?.levels?.length || "—"} dependency levels`;
    for (const task of data.tasks) {
      const row = document.createElement("div");
      row.className = "shell-plan-row";
      appendText(row, "strong", "", task.id);
      appendText(row, "span", "", task.tool);
      appendText(row, "small", "", task.depends_on?.length ? `waits for ${task.depends_on.join(", ")}` : "independent task");
      target.append(row);
    }
  }

  function renderChat() {
    const run = currentRun();
    const data = snapshot();
    renderPlan(data);
    const target = $("#shell-progress");
    target.replaceChildren();
    if (!run) {
      $("#shell-progress-summary").textContent = "No run selected.";
      appendText(target, "p", "shell-muted", "Task transitions will appear here.");
      $("#shell-answer").innerHTML = "";
      appendText($("#shell-answer"), "p", "shell-muted", "The completed brief answer will appear here.");
      $("#shell-run-question").hidden = true;
      $("#shell-run-question").textContent = "";
      $("#shell-evidence-cards").replaceChildren();
      $("#shell-citation-status").textContent = "Citation validation has not run.";
      $("#shell-answer-model").textContent = "No answer yet";
      $("#shell-brief-link").replaceChildren();
      return;
    }
    const tasks = data.tasks;
    const questionEvent = data.events.find((event) => event.kind === "plan_received");
    const runQuestion = $("#shell-run-question");
    runQuestion.textContent = questionEvent?.payload?.question || "Question not recorded in this run.";
    runQuestion.hidden = false;
    const counts = Object.values(data.taskStates).reduce((out, status) => {
      out[status] = (out[status] || 0) + 1;
      return out;
    }, {});
    $("#shell-progress-summary").textContent = `${counts.completed || 0}/${tasks.length} completed · ${counts.running || 0} running · ${counts.failed || 0} failed`;
    for (const task of tasks) {
      const row = document.createElement("div");
      row.className = "shell-progress-row";
      appendText(row, "code", "", task.id);
      appendText(row, "span", `shell-state ${data.taskStates[task.id] || "planned"}`, data.taskStates[task.id] || "planned");
      target.append(row);
    }
    const answerEvent = [...data.events].reverse().find((event) => event.kind === "answer_ready");
    const answerNode = $("#shell-answer");
    answerNode.replaceChildren();
    if (answerEvent?.payload?.answer) renderAnswer(answerNode, answerEvent.payload.answer, data.evidence);
    else appendText(answerNode, "p", "shell-muted", "The answer appears after evidence selection and drafting.");
    const model = [...data.events].reverse().find((event) => event.kind === "model_call_completed" && event.payload?.stage === "fods_answer");
    $("#shell-answer-model").textContent = model ? `${model.payload.provider || "provider unknown"} · ${model.payload.model || "model unknown"}` : run.run_kind === "replay" ? "Recorded answer · replay" : "Deterministic or no traced model call";
    const validation = data.validation;
    $("#shell-citation-status").textContent = validation
      ? validation.valid ? `Citation IDs verified: ${(validation.found || []).join(", ") || "none"}. This does not establish semantic support.` : `Citation check blocked output: ${(validation.unknown || []).join(", ") || "no supported IDs"}.`
      : "Citation validation has not run.";
    renderEvidence(data.evidence);
    const saved = [...data.events].reverse().find((event) => event.kind === "brief_saved");
    const linkTarget = $("#shell-brief-link");
    linkTarget.replaceChildren();
    if (saved?.payload?.saved && saved.payload.citations_validated) {
      const link = document.createElement("a");
      link.href = `/api/runs/${run.run_id}/brief`;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open validated brief";
      linkTarget.append(link);
    }
  }

  function renderAnswer(target, text, evidence) {
    const regex = /\[(P\d+)\]/g;
    let previous = 0;
    let match;
    while ((match = regex.exec(text))) {
      target.append(document.createTextNode(text.slice(previous, match.index)));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shell-citation-link";
      button.textContent = `[${match[1]}]`;
      button.addEventListener("click", () => revealEvidence(match[1], evidence));
      target.append(button);
      previous = regex.lastIndex;
    }
    target.append(document.createTextNode(text.slice(previous)));
  }

  function renderEvidence(evidence) {
    const target = $("#shell-evidence-cards");
    target.replaceChildren();
    for (const item of evidence) {
      const paper = item.paper || {};
      const card = document.createElement("article");
      card.className = `shell-evidence-card ${state.selectedCitation === item.citation ? "selected" : ""}`;
      card.id = `shell-evidence-${escapeSelector(item.citation)}`;
      appendText(card, "span", "shell-evidence-id", `[${item.citation}] · ${paper.id || "paper id unavailable"}`);
      appendText(card, "h3", "", paper.title || "Untitled paper");
      appendText(card, "p", "", item.excerpt || item.text || paper.abstract || "No excerpt recorded in this evidence card.");
      if (paper.doi) {
        const doi = document.createElement("a");
        doi.href = `https://doi.org/${encodeURIComponent(paper.doi)}`;
        doi.rel = "noopener noreferrer";
        doi.target = "_blank";
        doi.textContent = `DOI: ${paper.doi}`;
        card.append(doi);
      } else if (paper.url) {
        try {
          const parsed = new URL(paper.url);
          if (parsed.protocol === "https:" || parsed.protocol === "http:") {
            const url = document.createElement("a");
            url.href = parsed.href;
            url.rel = "noopener noreferrer";
            url.target = "_blank";
            url.textContent = "Open source record";
            card.append(url);
          }
        } catch { /* Invalid source URLs remain plain text in the event record. */ }
      }
      target.append(card);
    }
  }

  function revealEvidence(citation, evidence) {
    if (!core.findEvidenceByCitation(evidence, citation)) return;
    state.selectedCitation = citation;
    setView("chat");
    renderEvidence(evidence);
    document.getElementById(`shell-evidence-${escapeSelector(citation)}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function renderTrace() {
    const run = currentRun();
    const events = currentEvents();
    const target = $("#shell-trace-events");
    target.replaceChildren();
    if (!events.length) return appendText(target, "p", "shell-muted", "Select or start a run to inspect events.");
    const kinds = [...new Set(events.map((event) => event.kind))].sort();
    const kindSelect = $("#shell-trace-kind");
    const selectedKind = kindSelect.value;
    const kindSignature = kinds.join("\u0000");
    if (kindSelect.dataset.signature !== kindSignature) {
      kindSelect.replaceChildren(new Option("All event types", ""));
      kinds.forEach((kind) => kindSelect.add(new Option(kind, kind)));
      kindSelect.dataset.signature = kindSignature;
      kindSelect.value = kinds.includes(selectedKind) ? selectedKind : "";
    }
    const needle = $("#shell-trace-filter").value.trim().toLowerCase();
    const filtered = events.map((event, index) => ({ event, index })).filter(({ event }) => {
      if (kindSelect.value && event.kind !== kindSelect.value) return false;
      const searchable = [event.kind, event.message, event.payload?.task_id,
        event.payload?.source, event.payload?.provider, event.payload?.model]
        .filter(Boolean).join(" ").toLowerCase();
      return !needle || searchable.includes(needle);
    });
    if (!filtered.length) appendText(target, "p", "shell-muted", "No recorded events match these filters.");
    for (const { event, index } of filtered) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = `shell-trace-row ${state.cursor === index + 1 ? "selected" : ""}`;
      row.dataset.seq = event.seq;
      if (event.payload?.task_id) row.dataset.task = event.payload.task_id;
      appendText(row, "span", "shell-trace-seq", `#${event.seq}`);
      appendText(row, "span", "shell-lane", core.laneForEvent(event.kind));
      appendText(row, "strong", "", event.kind);
      appendText(row, "small", "", event.message || "");
      row.addEventListener("click", () => selectEvent(index));
      target.append(row);
    }
    const selected = snapshot().selectedEvent;
    renderEventDetails($("#shell-event-details"), selected);
    $("#shell-trace-mode").textContent = displayMode(run);
  }

  function renderEventDetails(target, event) {
    target.replaceChildren();
    if (!event) return appendText(target, "p", "shell-muted", "No event selected.");
    appendText(target, "h3", "", `#${event.seq} · ${event.kind}`);
    appendText(target, "p", "", event.message || "");
    appendText(target, "p", "shell-event-meta", `Recorded ${event.timestamp ? new Date(event.timestamp * 1000).toLocaleString() : "time unavailable"}${event.payload?.task_id ? ` · Task ${event.payload.task_id}` : ""}`);
    const disclosure = document.createElement("details");
    const summary = document.createElement("summary"); summary.textContent = "Advanced event payload";
    disclosure.append(summary);
    appendText(disclosure, "pre", "shell-json", JSON.stringify({ timestamp: event.timestamp, payload: event.payload || {} }, null, 2));
    target.append(disclosure);
  }

  function selectEvent(index) {
    state.followLive = false;
    setCursor(index + 1);
  }

  function selectTask(taskId) {
    state.selectedTask = taskId;
    const events = currentEvents();
    const index = core.eventIndexForTask(events, taskId);
    state.followLive = false;
    setCursor(index < 0 ? state.cursor : index + 1);
  }

  function renderDag(data) {
    const svg = $("#shell-dag");
    svg.replaceChildren();
    const tasks = data.tasks;
    $("#shell-task-count").textContent = tasks.length ? `${tasks.length} tasks` : "No plan";
    $("#shell-dag-empty").hidden = Boolean(tasks.length);
    if (!tasks.length) return;
    const levels = [...data.events].reverse().find((event) => event.kind === "plan_validated")?.payload?.levels || [tasks.map((task) => task.id)];
    const byId = new Map(tasks.map((task) => [task.id, task]));
    const positions = new Map();
    const dependencyLine = window.d3.line()
      .x((point) => point.x)
      .y((point) => point.y)
      .curve(window.d3.curveBumpX);
    const width = Math.max(680, levels.length * 205 + 40);
    const rows = Math.max(1, ...levels.map((level) => level.length));
    const height = Math.max(230, rows * 90 + 50);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
    marker.setAttribute("id", "shell-arrow"); marker.setAttribute("markerWidth", "8"); marker.setAttribute("markerHeight", "8"); marker.setAttribute("refX", "7"); marker.setAttribute("refY", "3"); marker.setAttribute("orient", "auto");
    const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
    arrow.setAttribute("d", "M0,0 L0,6 L7,3 z"); arrow.setAttribute("fill", "#9bb0bc"); marker.append(arrow); defs.append(marker); svg.append(defs);
    levels.forEach((level, column) => level.forEach((taskId, row) => positions.set(taskId, { x: 18 + column * 205, y: 30 + row * 88 })));
    const completed = new Set(data.events.filter((event) => event.kind === "task_completed").map((event) => event.payload?.task_id));
    for (const task of tasks) for (const parentId of task.depends_on || []) {
      const from = positions.get(parentId), to = positions.get(task.id);
      if (!from || !to) continue;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", dependencyLine([
        { x: from.x + 160, y: from.y + 29 },
        { x: to.x, y: to.y + 29 },
      ]));
      path.setAttribute("class", `shell-dag-edge ${completed.has(parentId) ? "completed" : ""}`);
      path.setAttribute("marker-end", "url(#shell-arrow)"); svg.append(path);
    }
    for (const task of tasks) {
      const point = positions.get(task.id);
      const node = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const status = data.taskStates[task.id] || "planned";
      node.setAttribute("class", `shell-dag-node ${status} ${state.selectedTask === task.id ? "selected" : ""}`);
      node.setAttribute("transform", `translate(${point.x},${point.y})`);
      node.setAttribute("tabindex", "0"); node.setAttribute("role", "button"); node.setAttribute("aria-label", `${task.id}, ${status}`);
      node.addEventListener("click", () => selectTask(task.id));
      node.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectTask(task.id); } });
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect"); rect.setAttribute("width", "160"); rect.setAttribute("height", "58"); node.append(rect);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", "10"); label.setAttribute("y", "21"); label.textContent = task.id; node.append(label);
      const sub = document.createElementNS("http://www.w3.org/2000/svg", "text"); sub.setAttribute("x", "10"); sub.setAttribute("y", "42"); sub.textContent = `${task.tool} · ${status}`; node.append(sub);
      svg.append(node);
    }
  }

  function makeSelectableRow(parent, taskId, title, detail) {
    const row = document.createElement("button");
    row.type = "button"; row.className = `shell-data-row ${state.selectedTask === taskId ? "selected" : ""}`;
    row.addEventListener("click", () => selectTask(taskId));
    appendText(row, "strong", "", title);
    appendText(row, "span", "", detail);
    parent.append(row);
  }

  function renderVisualizer() {
    const data = snapshot();
    const events = currentEvents();
    const slider = $("#shell-event-cursor");
    slider.max = String(events.length);
    slider.value = String(state.cursor);
    $("#shell-event-position").textContent = `${state.cursor} / ${events.length}`;
    $("#shell-viz-follow").setAttribute("aria-pressed", String(state.followLive));
    $("#shell-viz-follow").textContent = state.followLive ? "Following live events" : "Follow live events";
    renderDag(data);

    const queue = $("#shell-ready-queue"); queue.replaceChildren();
    if (!data.queueRecorded) appendText(queue, "p", "shell-muted", "Queue state not recorded at this event.");
    else if (!data.readyQueue.length) appendText(queue, "p", "shell-muted", "The recorded ready queue is empty at this event.");
    data.readyQueue.forEach((entry, index) => makeSelectableRow(queue, entry.task_id, `${index + 1}. ${entry.task_id}`, entry.priority === undefined ? "FIFO position" : `priority ${entry.priority} · sequence ${entry.sequence ?? "not recorded"}`));

    const workers = $("#shell-workers"); workers.replaceChildren();
    if (!data.activeTasks.length) appendText(workers, "p", "shell-muted", "No tasks were running at this event.");
    data.activeTasks.forEach((task) => makeSelectableRow(workers, task.task_id, task.task_id, `Active since ${new Date(task.started_at * 1000).toLocaleTimeString()} · attempt ${task.attempt ?? "not recorded"}`));

    const states = $("#shell-task-states"); states.replaceChildren();
    if (!data.tasks.length) appendText(states, "p", "shell-muted", "No accepted task plan.");
    data.tasks.forEach((task) => makeSelectableRow(states, task.id, task.id, `${task.tool} · ${data.taskStates[task.id] || "planned"}`));

    const stacks = $("#shell-stacks"); stacks.replaceChildren();
    const stackEntries = Object.entries(data.stacks);
    if (!stackEntries.length) appendText(stacks, "p", "shell-muted", "No stack state recorded at this event.");
    for (const [taskId, frames] of stackEntries) {
      const group = document.createElement("section");
      group.className = `shell-stack ${state.selectedTask === taskId ? "selected" : ""}`;
      appendText(group, "strong", "", `${taskId} · LIFO stack`);
      if (frames.length) appendText(group, "span", "shell-stack-top", "TOP");
      [...frames].reverse().forEach((frame, index) => appendText(group, "code", index === 0 ? "shell-stack-frame top" : "shell-stack-frame", frame));
      stacks.append(group);
    }

    const selected = data.selectedEvent;
    $("#shell-selected-event-label").textContent = selected ? `Event ${selected.seq} of ${events.length}` : "Select an event in Trace.";
    renderEventDetails($("#shell-selected-event"), selected);
  }

  async function compareSchedulers() {
    if (state.active) return;
    const base = {
      topic: "Synthetic frontend scheduler comparison",
      question: "In the synthetic fixture, which tasks become ready and in what order?",
      mode: "simulate",
      planner: "fixture",
      concurrency: Number($("#shell-concurrency").value) || 1,
      source_limit: Number($("#shell-source-limit").value) || 3,
      reuse_context: false,
      output_name: "",
    };
    state.comparison = { fifo: null, priority: null };
    try {
      await startRun({ ...base, schedule: "fifo" }, (run) => {
        state.comparison.fifo = run;
        startRun({ ...base, schedule: "priority" }, (priorityRun) => {
          state.comparison.priority = priorityRun;
          renderComparison();
        }).catch((error) => { $("#shell-error").textContent = error.message; });
      });
    } catch (error) {
      state.comparison = null;
      $("#shell-error").textContent = error.message;
    }
  }

  function renderComparison() {
    const box = $("#shell-queue-comparison");
    box.replaceChildren();
    if (!state.comparison) return appendText(box, "p", "shell-muted", "Run both deterministic schedules to compare dequeue events.");
    for (const [label, run] of [["FIFO", state.comparison.fifo], ["Priority heap", state.comparison.priority]]) {
      const panel = document.createElement("div"); panel.className = "shell-compare-box";
      appendText(panel, "h3", "", label);
      const order = run ? run.events.filter((event) => event.kind === "task_dequeued").map((event) => event.payload?.task_id).filter(Boolean) : [];
      appendText(panel, "p", "", run ? order.join(" → ") || "No dequeue events recorded" : "Waiting for this run");
      box.append(panel);
    }
  }

  async function runControlledScenario(overrides) {
    const payload = {
      topic: "Synthetic frontend runtime demonstration",
      question: "What does the deterministic fixture show about graph attention?",
      mode: "simulate",
      planner: "fixture",
      schedule: "fifo",
      concurrency: 3,
      source_limit: 3,
      output_name: "",
      reuse_context: false,
      delay_ms: 80,
      ...overrides,
    };
    try {
      await startRun(payload);
    } catch (error) {
      $("#shell-error").textContent = error.message;
      setView("chat");
    }
  }

  initialize();
})();
