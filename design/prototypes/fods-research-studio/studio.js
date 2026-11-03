"use strict";

// Synthetic-only prototype content. No requests are made to the FODS backend.
const demoEvents = [
  { seq: 1, lane: "Run", kind: "run_started", detail: "Synthetic investigation started", time: "00.00", status: "Started", task: null },
  { seq: 2, lane: "Planning", kind: "plan_received", detail: "Validated teaching plan received", time: "00.03", status: "Recorded", task: null },
  { seq: 3, lane: "FODS", kind: "plan_validated", detail: "Dependency graph accepted", time: "00.05", status: "Passed", task: null },
  { seq: 4, lane: "FODS", kind: "queue_updated", operation: "enqueue", ready: ["search_alpha"], detail: "search_alpha enqueued · FIFO", time: "00.06", status: "Enqueued", task: "search_alpha" },
  { seq: 5, lane: "FODS", kind: "queue_updated", operation: "enqueue", ready: ["search_alpha", "search_beta"], detail: "search_beta enqueued · FIFO", time: "00.07", status: "Enqueued", task: "search_beta" },
  { seq: 6, lane: "FODS", kind: "queue_updated", operation: "dequeue", ready: ["search_beta"], detail: "search_alpha dequeued from the front", time: "00.08", status: "Dequeued", task: "search_alpha" },
  { seq: 7, lane: "FODS", kind: "task_started", detail: "search_alpha started · attempt 1", time: "00.08", status: "Running", task: "search_alpha" },
  { seq: 8, lane: "FODS", kind: "stack_push", stack: ["task:search_alpha", "tool:synthetic_search"], detail: "synthetic_search pushed on search_alpha stack", time: "00.08", status: "Pushed", task: "search_alpha" },
  { seq: 9, lane: "FODS", kind: "queue_updated", operation: "dequeue", ready: [], detail: "search_beta dequeued from the front", time: "00.09", status: "Dequeued", task: "search_beta" },
  { seq: 10, lane: "FODS", kind: "task_started", detail: "search_beta started · attempt 1", time: "00.09", status: "Running", task: "search_beta" },
  { seq: 11, lane: "FODS", kind: "stack_pop", stack: ["task:search_alpha"], detail: "synthetic_search popped from search_alpha stack", time: "00.31", status: "Popped", task: "search_alpha" },
  { seq: 12, lane: "FODS", kind: "task_completed", detail: "search_alpha completed", time: "00.34", status: "Completed", task: "search_alpha" },
  { seq: 13, lane: "FODS", kind: "task_completed", detail: "search_beta completed", time: "00.38", status: "Completed", task: "search_beta" },
  { seq: 14, lane: "FODS", kind: "dependency_updated", detail: "merge is ready after prerequisites completed", time: "00.39", status: "Ready", task: "merge" },
  { seq: 15, lane: "Evidence", kind: "evidence_selected", detail: "Two synthetic evidence cards selected", time: "00.43", status: "Selected", task: "select_evidence" },
  { seq: 16, lane: "Answer", kind: "answer_ready", detail: "Illustrative answer prepared", time: "00.47", status: "Ready", task: "draft_answer" },
  { seq: 17, lane: "Output", kind: "citation_validation", detail: "Citation identifiers match synthetic card IDs", time: "00.49", status: "Valid IDs", task: "citation_check" },
  { seq: 18, lane: "Output", kind: "brief_saved", detail: "Synthetic brief saved in prototype fixture", time: "00.51", status: "Saved", task: "write_brief" },
  { seq: 19, lane: "Run", kind: "run_finished", detail: "Synthetic walkthrough completed", time: "00.52", status: "Finished", task: null },
];
const syntheticPapers = {
  P1: { title: "Synthetic Example: Local Neighbor Attention", year: "2024", excerpt: "Synthetic evidence: attention weights neighboring nodes." },
  P2: { title: "Synthetic Example: Global Graph Mixing", year: "2023", excerpt: "Synthetic evidence: information is mixed across the graph." },
};
const byId = (id) => document.getElementById(id);
let selectedEvent = 0;
let filterLane = "all";
let playback = null;
const playbackRates = [0.5, 1, 2];
let playbackRateIndex = 1;

function openScreen(name) {
  document.querySelectorAll(".screen").forEach((screen) => screen.classList.toggle("active", screen.id === `screen-${name}`));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.screen === name));
  const labels = { research: "Research", trace: "Trace", lab: "FODS Lab", library: "Library" };
  byId("crumb-title").textContent = labels[name] || "Research";
}
function renderTrace() {
  const text = (byId("trace-search").value || "").toLowerCase();
  const host = byId("trace-events"); host.replaceChildren();
  demoEvents.filter((event) => (filterLane === "all" || event.lane === filterLane) && `${event.kind} ${event.detail} ${event.task || ""}`.toLowerCase().includes(text)).forEach((event) => {
    const row = document.createElement("button"); row.className = `trace-row ${selectedEvent === event.seq - 1 ? "selected" : ""}`;
    for (const value of [event.lane, event.detail, `#${String(event.seq).padStart(2, "0")}`, `${event.time}s`, event.status]) {
      const cell = document.createElement("span"); cell.textContent = value;
      if (value === event.lane) { cell.className = "trace-lane"; const mark = document.createElement("i"); mark.className = "lane-mark"; cell.prepend(mark); }
      if (value === event.detail) cell.className = "trace-kind";
      if (value === `#${String(event.seq).padStart(2, "0")}` || value === `${event.time}s`) cell.className = "trace-seq";
      row.append(cell);
    }
    row.addEventListener("click", () => { setEvent(event.seq - 1); openScreen("trace"); }); host.append(row);
  });
}
function renderTraceDetail() {
  const event = demoEvents[selectedEvent];
  byId("trace-detail").innerHTML = `<b>${event.kind}</b> · ${event.detail}<br><span>Sequence ${event.seq} · ${event.time}s · ${event.lane}${event.task ? ` · task ${event.task}` : " · no task ID recorded"}</span>`;
  byId("trace-raw").textContent = JSON.stringify({ seq: event.seq, kind: event.kind, synthetic: true, lane: event.lane, timestamp: event.time, task_id: event.task, message: event.detail, status: event.status }, null, 2);
}
function setEvent(index) {
  selectedEvent = Math.max(0, Math.min(demoEvents.length - 1, index));
  const event = demoEvents[selectedEvent];
  byId("event-slider").value = String(selectedEvent);
  byId("event-position").textContent = `${String(selectedEvent + 1).padStart(2, "0")} / ${demoEvents.length}`;
  byId("event-description").textContent = `#${event.seq} ${event.kind} · ${event.detail}`;
  byId("lesson-copy").textContent = lessonFor(event);
  const activeTask = event.task || "search_alpha";
  byId("selected-task-name").textContent = activeTask;
  const prerequisites = { merge: "search_alpha, search_beta", select_evidence: "merge", draft_answer: "select_evidence", citation_check: "draft_answer", write_brief: "citation_check" };
  byId("task-prereqs").textContent = prerequisites[activeTask] || "None recorded";
  byId("task-state").textContent = taskStatesAt(event.seq)[activeTask] || "Not recorded";
  document.querySelectorAll(".dag-node").forEach((node) => node.classList.toggle("active-node", node.dataset.task === activeTask));
  renderDagStates(event.seq);
  renderDictionary(event.seq);
  renderStacks(event);
  renderQueue(event.seq);
  renderTraceDetail(); renderTrace();
}
function lessonFor(event) {
  const lessons = {
    plan_received: "The plan defines dependencies before tasks run. The DAG topology is a synthetic teaching plan, not a live FODS run.",
    queue_updated: "Enqueue records change the ready queue. Follow the recorded order; do not infer a heap array when the trace lacks it.",
    task_started: "A task start moves its recorded state to running. Overlap across tasks does not identify actual worker slots.",
    stack_push: "A push adds a frame to this task's LIFO stack. TOP identifies the next frame to pop.",
    stack_pop: "A pop removes the top frame from this task's stack. The event fixture records the resulting stack.",
    dependency_updated: "The merge becomes eligible after its prerequisites complete: fan-out meets fan-in at this edge.",
    evidence_selected: "Evidence selection links answer citations to stored synthetic records. It does not establish real-world support.",
    citation_validation: "The check verifies citation IDs exist. It does not evaluate whether claims are entailed by sources.",
    run_finished: "At the terminal event, no task remains active. Use the cursor to revisit queue and task activity; this is view history, not rollback.",
  };
  return lessons[event.kind] || `${event.kind} is the event that changes this view. Inspect the selected event and compare its task and recorded state.`;
}
function renderDictionary(sequence) {
  const host = byId("dictionary"); host.querySelectorAll(".dict-row").forEach((row) => row.remove());
  const states = taskStatesAt(sequence);
  Object.entries(states).forEach(([key, value]) => {
    const row = document.createElement("div"); row.className = "dict-row";
    const a = document.createElement("span"); a.textContent = key;
    const b = document.createElement("span"); b.textContent = value;
    row.append(a, b); host.append(row);
  });
}
function taskStatesAt(sequence) {
  return {
    search_alpha: sequence >= 12 ? "completed" : sequence >= 7 ? "running" : sequence >= 4 ? "ready" : "planned",
    search_beta: sequence >= 13 ? "completed" : sequence >= 10 ? "running" : sequence >= 5 ? "ready" : "planned",
    merge: sequence >= 14 ? "ready" : "blocked",
    select_evidence: sequence >= 15 ? "completed" : "blocked",
    draft_answer: sequence >= 16 ? "completed" : "blocked",
    citation_check: sequence >= 17 ? "completed" : "blocked",
    write_brief: sequence >= 18 ? "completed" : "blocked",
  };
}
function renderDagStates(sequence) {
  const states = taskStatesAt(sequence);
  document.querySelectorAll(".dag-node").forEach((node) => {
    const state = states[node.dataset.task] || "not recorded";
    node.classList.toggle("done", state === "completed");
    const label = node.querySelector("span");
    if (label) label.textContent = state;
  });
}
function renderStacks(event) {
  const host = byId("stack-columns"); host.replaceChildren();
  const operations = new Map();
  demoEvents.slice(0, selectedEvent + 1).filter((item) => ["stack_push", "stack_pop"].includes(item.kind)).forEach((item) => operations.set(item.task, item));
  for (const task of ["search_alpha", "search_beta"]) {
    const col = document.createElement("div"); col.className = "stack-column";
    const operation = operations.get(task);
    if (operation?.stack?.length) {
      operation.stack.forEach((value) => { const item = document.createElement("div"); item.className = "stack-item"; item.textContent = value; col.append(item); });
      const top = document.createElement("span"); top.className = "stack-top"; top.textContent = "← TOP"; col.append(top);
    } else {
      const missing = document.createElement("div"); missing.className = "stack-item"; missing.textContent = "No stack event recorded"; col.append(missing);
    }
    const label = document.createElement("span"); label.className = "stack-name"; label.textContent = task; col.append(label); host.append(col);
  }
  const stackEvent = event.kind.startsWith("stack_");
  byId("stack-event-title").textContent = stackEvent ? `${event.kind} · ${event.task || "task not recorded"}` : "No stack operation at this event";
  byId("stack-event-copy").textContent = stackEvent ? `${event.detail}. The stack shown is illustrative synthetic lesson data.` : "The cursor is not on a recorded stack operation. Stacks remain shown as the known synthetic lesson state.";
}
function renderQueue(sequence) {
  const host = byId("queue-items"); host.replaceChildren();
  const snapshot = demoEvents.slice(0, sequence).reverse().find((item) => item.kind === "queue_updated");
  const items = snapshot?.ready || [];
  items.forEach((name) => { const item = document.createElement("span"); item.className = "queue-item"; item.textContent = name; host.append(item); });
  byId("queue-note").textContent = !snapshot ? "Queue state not recorded at this event." : items.length ? `Recorded ${snapshot.operation} snapshot from event ${snapshot.seq}.` : `Empty in recorded event ${snapshot.seq}; no tasks are waiting in this synthetic sequence.`;
}
function renderLibrary(kind = "investigations", search = "") {
  const host = byId("library-items"); host.replaceChildren();
  const records = kind === "contexts" ? [{ kind: "SAVED CONTEXT", title: "Graph attention · synthetic topic context", detail: "2 synthetic papers · prototype-only record", status: "Synthetic" }] : [
    { kind: "SIMULATION", title: "How graph attention methods use neighboring nodes?", detail: "INV-SYN-0042 · 2 synthetic evidence cards", status: "Completed" },
    { kind: "REPLAY", title: "What trade-offs appear in retrieval-augmented generation?", detail: "INV-SYN-0037 · original mode not recorded", status: "Replay" },
  ];
  records.filter((record) => `${record.title} ${record.detail}`.toLowerCase().includes(search)).forEach((record) => {
    const row = document.createElement("div"); row.className = "library-row";
    const a = document.createElement("span"); a.className = "kind"; a.textContent = record.kind;
    const b = document.createElement("span"); const title = document.createElement("b"); title.textContent = record.title; const detail = document.createElement("small"); detail.textContent = record.detail; b.append(title, detail);
    const c = document.createElement("span"); c.textContent = record.status; c.className = "lib-state";
    const d = document.createElement("span"); d.textContent = "Synthetic"; d.className = "lib-state";
    const e = document.createElement("button"); e.textContent = kind === "contexts" ? "Inspect" : "Open"; e.addEventListener("click", () => {
      if (kind === "contexts") return showNotice("Saved contexts are illustrative prototype records only.");
      if (record.kind === "REPLAY") return showNotice("Replay is not fabricated here: no saved event trace is bundled for this example.");
      openScreen("research"); showCompleted();
    });
    row.append(a, b, c, d, e); host.append(row);
  });
}
function showCompleted() { byId("research-empty").classList.add("hidden"); byId("research-result").classList.remove("hidden"); }
document.querySelectorAll("[data-screen]").forEach((button) => button.addEventListener("click", () => openScreen(button.dataset.screen)));
document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => openScreen(button.dataset.go)));
document.querySelectorAll("[data-open-sample]").forEach((button) => button.addEventListener("click", () => { openScreen("research"); showCompleted(); }));
document.querySelectorAll("[data-mode-choice]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-mode-choice]").forEach((option) => option.classList.toggle("selected", option === button));
}));
document.querySelectorAll("[data-labtab]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-labtab]").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll("[data-labpanel]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.labpanel !== button.dataset.labtab));
}));
document.querySelectorAll(".dag-node").forEach((node) => node.addEventListener("click", () => {
  const taskEvents = demoEvents.map((event, index) => ({ event, index })).filter(({ event }) => event.task === node.dataset.task);
  const firstRelevantEvent = (taskEvents.find(({ event }) => ["task_started", "dependency_updated", "evidence_selected", "answer_ready"].includes(event.kind)) || taskEvents[0])?.index ?? -1;
  if (firstRelevantEvent >= 0) setEvent(firstRelevantEvent);
}));
document.querySelectorAll("[data-library]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-library]").forEach((item) => item.classList.toggle("active", item === button));
  byId("library-items").classList.toggle("contexts-view", button.dataset.library === "contexts");
  byId("library-title").textContent = button.dataset.library === "contexts" ? "Saved contexts" : "Library";
  renderLibrary(button.dataset.library, byId("library-search-input")?.value.toLowerCase() || "");
}));
document.querySelectorAll("[data-cite]").forEach((button) => button.addEventListener("click", () => {
  const paper = syntheticPapers[button.dataset.cite]; if (!paper) return;
  byId("drawer-cite").textContent = button.dataset.cite; byId("drawer-title").textContent = paper.title;
  byId("drawer-meta").textContent = `${paper.year} · synthetic demonstration record`;
  byId("drawer-excerpt").textContent = paper.excerpt; byId("evidence-drawer").classList.add("open");
}));
byId("close-drawer").addEventListener("click", () => byId("evidence-drawer").classList.remove("open"));
document.querySelectorAll(".filter-chip").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".filter-chip").forEach((item) => item.classList.toggle("active", item === button)); filterLane = button.dataset.filter; renderTrace();
}));
byId("trace-search").addEventListener("input", renderTrace);
byId("library-search-input").addEventListener("input", (event) => {
  const active = document.querySelector("[data-library].active")?.dataset.library || "investigations";
  renderLibrary(active, event.target.value.toLowerCase());
});
byId("event-slider").addEventListener("input", (event) => setEvent(Number(event.target.value)));
byId("next-event").addEventListener("click", () => setEvent(selectedEvent + 1));
byId("back-event").addEventListener("click", () => setEvent(selectedEvent - 1));
byId("reset-events").addEventListener("click", () => { stopPlayback(); setEvent(0); });
byId("play-events").addEventListener("click", () => { stopPlayback(); playback = setInterval(() => selectedEvent >= demoEvents.length - 1 ? stopPlayback() : setEvent(selectedEvent + 1), 850 / playbackRates[playbackRateIndex]); });
byId("pause-events").addEventListener("click", stopPlayback);
byId("speed-chip").addEventListener("click", () => {
  playbackRateIndex = (playbackRateIndex + 1) % playbackRates.length;
  byId("speed-chip").textContent = `${playbackRates[playbackRateIndex]}×`;
  if (playback) byId("play-events").click();
});
function stopPlayback() { if (playback) clearInterval(playback); playback = null; }
byId("lesson-select").addEventListener("change", (event) => {
  const lesson = event.target.value;
  const lessonCursors = { dag: 2, queue: 3, concurrency: 7, state: 9, stack: 6, recovery: 15 };
  setEvent(lessonCursors[lesson]);
  if (lesson === "recovery") byId("lesson-copy").textContent = "No failure or retry is recorded in this walkthrough. A recovery lesson requires a separate synthetic trace with explicit failure and retry events.";
});
byId("new-investigation").addEventListener("click", () => { byId("research-empty").classList.remove("hidden"); byId("research-result").classList.add("hidden"); openScreen("research"); });
byId("follow-up").addEventListener("click", () => { byId("new-investigation").click(); byId("question-input").focus(); });
document.querySelectorAll(".suggestions>button").forEach((button) => button.addEventListener("click", () => { byId("question-input").value = button.textContent.trim(); byId("question-input").focus(); }));
byId("question-form").addEventListener("submit", (event) => {
  event.preventDefault();
  showNotice("This is a static prototype; it did not start a research run. Open the saved synthetic investigation in Recent investigations to view a completed brief.");
});
function showNotice(message) {
  const notice = byId("prototype-notice"); notice.textContent = message; notice.classList.add("visible");
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => notice.classList.remove("visible"), 5000);
}
byId("library-title").textContent = "Library";
renderLibrary(); renderTrace(); setEvent(0);
const query = new URLSearchParams(location.search);
if (query.get("view") === "completed") { openScreen("research"); showCompleted(); }
else if (["trace", "lab", "library"].includes(query.get("view"))) openScreen(query.get("view"));
if (["dag", "scheduler", "state"].includes(query.get("lab"))) {
  openScreen("lab");
  document.querySelector(`[data-labtab="${query.get("lab")}"]`).click();
}
if (query.has("event")) setEvent(Number(query.get("event")) - 1);
if (["dag", "queue", "concurrency", "state", "stack", "recovery"].includes(query.get("lesson"))) {
  byId("lesson-select").value = query.get("lesson");
  byId("lesson-select").dispatchEvent(new Event("change"));
}
let noticeTimer = null;
