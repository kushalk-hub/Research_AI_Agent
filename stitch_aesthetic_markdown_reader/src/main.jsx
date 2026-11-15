import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, Archive, ArrowDown, ArrowRight, BookOpen, Check, ChevronDown,
  CircleAlert, Clock3, Download, ExternalLink, FileText, FlaskConical, GitBranch,
  Layers3, Library, LoaderCircle, Network, Play, Plus, Search, Send, Settings2,
  ShieldCheck, Square, Workflow,
} from "lucide-react";
import "./styles.css";

const core = window.FODSFrontendCore;
const NAV = [
  ["research", "Research", BookOpen],
  ["trace", "Execution Trace", Activity],
  ["lab", "FODS Lab", Workflow],
  ["library", "Library", Library],
];
const LAB_TABS = [["graph", "Dependency Graph"], ["queue", "Queue & Scheduler"], ["stacks", "Task Stacks"]];
const txt = (value, fallback = "—") => String(value ?? fallback);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.error || `Request failed (${response.status})`);
  return body;
}

function statusClass(status = "") {
  const value = status.toLowerCase();
  if (value.includes("complete") || value === "ok" || value === "verified") return "good";
  if (value.includes("partial") || value.includes("running") || value.includes("active") || value.includes("pending")) return "warm";
  if (value.includes("fail") || value.includes("error")) return "bad";
  return "quiet";
}

function badge(label, status = label) {
  return <span className={`badge ${statusClass(status)}`}><i />{label}</span>;
}

function useWorkspace() {
  const [config, setConfig] = useState(null);
  const [history, setHistory] = useState([]);
  const [contexts, setContexts] = useState([]);
  const [connected, setConnected] = useState(false);
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [active, setActive] = useState(false);
  const [error, setError] = useState("");
  const source = useRef(null);

  const refreshHistory = useCallback(async () => {
    const result = await api("/api/history");
    setHistory(result.runs || []);
  }, []);
  const refreshContexts = useCallback(async () => {
    const result = await api("/api/contexts");
    setContexts(result.contexts || []);
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.all([api("/api/health"), api("/api/config"), api("/api/contexts"), api("/api/history")])
      .then(([health, nextConfig, nextContexts, nextHistory]) => {
        if (!mounted) return;
        setConnected(Boolean(health.ok));
        setConfig(nextConfig);
        setContexts(nextContexts.contexts || []);
        setHistory(nextHistory.runs || []);
      })
      .catch((reason) => { if (mounted) { setConnected(false); setError(reason.message); } });
    return () => { mounted = false; source.current?.close(); };
  }, []);

  const watch = useCallback((handle, initial = {}) => {
    source.current?.close();
    const next = { ...handle, ...initial, events: [] };
    setRun(next);
    setEvents([]);
    setActive(true);
    setError("");
    const stream = new EventSource(handle.events_url || `/api/runs/${handle.run_id}/events`);
    source.current = stream;
    stream.onmessage = (message) => {
      let envelope;
      try { envelope = JSON.parse(message.data); } catch { return; }
      if (envelope.run_kind) next.run_kind = envelope.run_kind;
      next.events.push(envelope.event);
      if (envelope.event.kind === "run_finished") {
        const payload = envelope.event.payload || {};
        next.status = payload.termination_reason === "completed_with_partial_sources" ? "partial" : payload.succeeded ? "completed" : payload.termination_reason === "cancelled" ? "cancelled" : "failed";
      }
      setRun({ ...next });
      setEvents([...next.events]);
      if (envelope.event.kind === "run_finished") {
        setActive(false);
        stream.close();
        refreshHistory().catch(() => {});
        refreshContexts().catch(() => {});
      }
    };
    stream.onerror = () => {
      if (stream.readyState === EventSource.CLOSED) setConnected(false);
    };
  }, [refreshHistory, refreshContexts]);

  const start = useCallback(async (payload) => {
    if (active) throw new Error("Wait for the current run to finish before starting another.");
    const handle = await api("/api/runs", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    });
    watch(handle, { ...payload, title: payload.topic, run_kind: payload.mode });
    return handle;
  }, [active, watch]);

  const replay = useCallback(async (runId) => {
    if (active) throw new Error("Wait for the active run to finish before replaying another run.");
    const handle = await api("/api/replay", {
      method: "POST", body: JSON.stringify({ run_id: runId, speed_ms: 0 }),
    });
    watch(handle, { run_kind: "replay", mode: "replay", source_run_id: runId });
    return handle;
  }, [active, watch]);

  return { config, history, contexts, connected, run, events, active, error, setError, start, replay, refreshHistory };
}

function Header({ page, setPage, run, connected }) {
  return <header className="topbar">
    <a className="brand" href="#research" onClick={(event) => { event.preventDefault(); setPage("research"); }}>
      <span className="brand-mark">F</span><span><strong>FODS</strong><em>Research Studio</em></span>
    </a>
    {run && <div className="run-chip"><code>{run.run_id}</code>{badge(run.status || (run.events?.length ? "Active" : "Ready"), run.status || (run.events?.length ? "running" : "ready"))}</div>}
    <nav className="primary-nav" aria-label="Primary navigation">
      {NAV.map(([key, label]) => <button key={key} className={page === key ? "selected" : ""} onClick={() => setPage(key)}>{label}</button>)}
    </nav>
    <div className="connection">{connected ? <><i className="pulse" /> Local runtime ready</> : <><CircleAlert size={15} /> Runtime disconnected</>}</div>
    <button className="button dark top-new" onClick={() => setPage("research")}><Plus size={16} /> New investigation</button>
  </header>;
}

function SideRail({ page, setPage, history, run, replay }) {
  return <aside className="side-rail">
    <div className="rail-caption">WORKSPACE</div>
    {NAV.map(([key, label, Icon]) => <button key={key} className={`rail-link ${page === key ? "active" : ""}`} onClick={() => setPage(key)}><Icon size={17} /><span>{label}</span></button>)}
    <div className="rail-section"><span>RECENT INVESTIGATIONS</span><button title="Refresh history" onClick={() => window.dispatchEvent(new Event("refresh-history"))}>↻</button></div>
    <div className="recent-list">{history.slice(0, 12).map((item) => <button key={item.run_id} className={`recent-run ${run?.source_run_id === item.run_id || run?.run_id === item.run_id ? "chosen" : ""}`} onClick={() => replay(item.run_id)}><span className="recent-title">{item.topic || "Untitled investigation"}</span><span>{item.mode} · {item.status}</span><code>{item.run_id}</code></button>)}</div>
    <div className="rail-foot"><ShieldCheck size={15} /> Event-backed research workspace</div>
  </aside>;
}

function Hero({ kicker, title, children, action }) {
  return <div className="page-hero"><div><div className="eyebrow"><i />{kicker}</div><h1>{title}</h1>{children && <p>{children}</p>}</div>{action && <div className="hero-action">{action}</div>}</div>;
}

function PaperCard({ paper, citation, selected, onSelect }) {
  return <article className={`paper-card ${selected ? "paper-selected" : ""}`} onClick={onSelect}>
    <div className="paper-meta"><code>{citation || paper?.id || "Paper"}</code><span>{paper?.year || "Year not recorded"}</span></div>
    <h3>{paper?.title || "Untitled paper"}</h3>
    <p>{paper?.abstract || "No abstract was recorded for this paper."}</p>
    <div className="paper-footer"><span>{paper?.venue || "Publication details not recorded"}</span>{paper?.doi && <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>DOI <ExternalLink size={12} /></a>}</div>
  </article>;
}

function CiteText({ text, onCitation }) {
  const chunks = String(text || "").split(/(\[(?:P|C)\d+\])/g);
  return <>{chunks.map((part, index) => /^\[(?:P|C)\d+\]$/.test(part)
    ? <button className="cite-chip" key={index} onClick={() => onCitation(part)}>{part}</button>
    : <React.Fragment key={index}>{part}</React.Fragment>)}</>;
}

function ResearchPage({ workspace, selectedEvidence, setSelectedEvidence }) {
  const { config, run, events, active, start, setError, error } = workspace;
  const [topic, setTopic] = useState("");
  const [question, setQuestion] = useState("");
  const [paperLimit, setPaperLimit] = useState(20);
  const [waitSeconds, setWaitSeconds] = useState(300);
  const [budget, setBudget] = useState(100);
  const [engine, setEngine] = useState("rla");
  const [concurrency, setConcurrency] = useState(3);
  const [sourceLimit, setSourceLimit] = useState(3);
  const [schedule, setSchedule] = useState("fifo");
  const [reuseContext, setReuseContext] = useState(false);
  const [contextId, setContextId] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const answerEvent = [...events].reverse().find((event) => ["research_answer", "answer_ready"].includes(event.kind));
  const paperEvent = [...events].reverse().find((event) => ["research_papers", "context_ready"].includes(event.kind));
  const evidenceEvent = [...events].reverse().find((event) => event.kind === "evidence_selected");
  const validationEvent = [...events].reverse().find((event) => event.kind === "citation_validation");
  const runMetadata = events.find((event) => ["run_started", "plan_received"].includes(event.kind))?.payload || {};
  const runTopic = run?.topic || runMetadata.topic || topic;
  const runQuestion = run?.question || runMetadata.question || question;
  const evidence = answerEvent?.payload?.evidence || evidenceEvent?.payload?.evidence || [];
  const papers = paperEvent?.payload?.papers || [];
  const answer = answerEvent?.payload?.answer || "";
  const cited = answerEvent?.payload?.citations || [...new Set((answer.match(/\[(?:P|C)\d+\]/g) || []).map((citation) => citation.slice(1, -1)))];
  const count = new Set(cited).size;
  const effectiveTopic = topic.trim() || question.trim().slice(0, 90);
  const matchingContexts = workspace.contexts.filter((item) => item.topic?.trim().toLowerCase() === effectiveTopic.toLowerCase());

  useEffect(() => {
    if (!config) return;
    setPaperLimit(config.paper_limit || 20);
    setWaitSeconds(config.provider_wait_seconds ?? 300);
    setBudget(Math.max(100, config.llm_request_budget || 100));
  }, [config]);

  async function submit(event) {
    event.preventDefault(); setError("");
    try {
      if (engine === "fods-live" && reuseContext && !matchingContexts.some((item) => item.context_hash === contextId)) {
        throw new Error("Choose a saved context that matches this exact topic, or turn off context reuse to retrieve fresh sources.");
      }
      const common = {
        topic: topic.trim() || question.trim().slice(0, 90), question: question.trim(),
        engine: engine === "rla" ? "rla" : "fods", mode: engine === "fods-demo" ? "simulate" : "live",
      };
      await start(engine === "rla" ? {
        ...common, paper_limit: Number(paperLimit),
        provider_wait_seconds: Number(waitSeconds), llm_request_budget: Number(budget),
      } : engine === "fods-demo" ? {
        ...common, planner: "fixture", source_limit: Number(sourceLimit),
        concurrency: Number(concurrency), schedule, delay_ms: 150,
      } : {
        ...common, planner: "auto", source_limit: Number(sourceLimit),
        concurrency: Number(concurrency), schedule,
        reuse_context: reuseContext, context_id: reuseContext ? contextId : "",
      });
      setSelectedEvidence(null);
    } catch (reason) { setError(reason.message); }
  }
  const inspectCitation = (citation) => setSelectedEvidence(evidence.find((item) => `[${item.citation}]` === citation || item.citation === citation) || null);

  return <div className="research-page">
    {!run && <Hero kicker="QUESTION · EVIDENCE · BRIEF" title="Investigate a research question">Explore peer-reviewed literature, follow the evidence, and keep every claim connected to its source.</Hero>}
    {run && <Hero kicker="RESEARCH BRIEF" title={runTopic || "Research in progress"}>{runQuestion}</Hero>}
    <div className="research-grid">
      <section className="paper-surface composer">
        <div className="section-heading"><div><div className="eyebrow">NEW INVESTIGATION</div><h2>Frame the inquiry</h2></div>{run && badge(run.status || (active ? "Live research" : "Research run"), run.status || (active ? "running" : "quiet"))}</div>
        <form onSubmit={submit}>
          <label htmlFor="research-question">Core hypothesis or inquiry</label>
          <textarea id="research-question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What do you want to learn from the literature?" minLength={3} maxLength={1000} required />
          <div className="char-count">{question.length} / 1000</div>
          <label htmlFor="research-topic">Topic <span className="muted">optional</span></label>
          <input id="research-topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="A short label for this investigation" maxLength={300} />
          <div className="execution-select"><span>Execution mode</span><div className="mode-options">
            <button type="button" className={`mode-card ${engine === "rla" ? "active-mode" : ""}`} onClick={() => setEngine("rla")} aria-pressed={engine === "rla"}><span className="mode-icon"><Search size={18} /></span><strong>Live literature</strong><small>Retrieve papers and run the complete research pipeline.</small></button>
            <button type="button" className={`mode-card ${engine === "fods-live" ? "active-mode" : ""}`} onClick={() => setEngine("fods-live")} aria-pressed={engine === "fods-live"}><span className="mode-icon"><Network size={18} /></span><strong>FODS live research</strong><small>Run the task graph with real providers or reuse a saved topic context.</small></button>
            <button type="button" className={`mode-card mode-card-wide ${engine === "fods-demo" ? "active-mode" : ""}`} onClick={() => setEngine("fods-demo")} aria-pressed={engine === "fods-demo"}><span className="mode-icon"><FlaskConical size={18} /></span><strong>Deterministic demo</strong><small>Exercise the FODS graph, queue, stacks, and replay with fixture data.</small></button>
          </div></div>
          <div className="operational-note"><ShieldCheck size={17} /><span>{engine === "rla" ? "Each source and answer citation is shown with the evidence recorded for this run. Full-text retrieval is not enabled yet; extraction currently uses abstracts." : engine === "fods-demo" ? "The demo uses recorded fixture papers and a deterministic planner. It validates frontend and runtime flows without contacting literature providers." : "Live FODS uses configured literature providers and an Ollama planner. Reuse a saved context to answer a new question from the same topic data."}</span></div>
          <button className="settings-toggle" type="button" onClick={() => setShowSettings(!showSettings)}><Settings2 size={16} /> Advanced agent parameters <ChevronDown className={showSettings ? "rotate" : ""} size={15} /></button>
          {showSettings && engine === "rla" && <div className="form-grid">
            <div><label htmlFor="paper-limit">Papers to keep</label><input id="paper-limit" type="number" min="2" max={config?.paper_limit_max || 20} value={paperLimit} onChange={(e) => setPaperLimit(e.target.value)} /></div>
            <div><label htmlFor="cooldown">Provider cooldown wait (seconds)</label><input id="cooldown" type="number" min="0" max="3600" value={waitSeconds} onChange={(e) => setWaitSeconds(e.target.value)} /></div>
            <div><label htmlFor="request-budget">Model requests for this run</label><input id="request-budget" type="number" min="1" max="1000" value={budget} onChange={(e) => setBudget(e.target.value)} /></div>
          </div>}
          {showSettings && engine === "fods-demo" && <div className="form-grid">
            <div><label htmlFor="source-limit">Demo sources</label><input id="source-limit" type="number" min="2" max="5" value={sourceLimit} onChange={(e) => setSourceLimit(e.target.value)} /></div>
            <div><label htmlFor="concurrency">Concurrent tasks</label><input id="concurrency" type="number" min="1" max="8" value={concurrency} onChange={(e) => setConcurrency(e.target.value)} /></div>
            <div><label htmlFor="schedule">Queue policy</label><select id="schedule" value={schedule} onChange={(e) => setSchedule(e.target.value)}><option value="fifo">First in, first out</option><option value="priority">Priority</option></select></div>
          </div>}
          {showSettings && engine === "fods-live" && <div className="form-grid">
            <div><label htmlFor="live-source-limit">Live sources</label><input id="live-source-limit" type="number" min="2" max="5" value={sourceLimit} onChange={(e) => setSourceLimit(e.target.value)} /></div>
            <div><label htmlFor="live-concurrency">Concurrent tasks</label><input id="live-concurrency" type="number" min="1" max="8" value={concurrency} onChange={(e) => setConcurrency(e.target.value)} /></div>
            <div><label htmlFor="live-schedule">Queue policy</label><select id="live-schedule" value={schedule} onChange={(e) => setSchedule(e.target.value)}><option value="fifo">First in, first out</option><option value="priority">Priority</option></select></div>
            <label className="context-toggle"><input type="checkbox" checked={reuseContext} onChange={(e) => { setReuseContext(e.target.checked); if (!e.target.checked) setContextId(""); else if (matchingContexts[0]) setContextId(matchingContexts[0].context_hash); }} /> Reuse saved context for this exact topic</label>
            {reuseContext && <div className="context-picker"><label htmlFor="context-id">Saved topic context</label><select id="context-id" value={contextId} onChange={(e) => setContextId(e.target.value)}><option value="">Choose a saved context</option>{matchingContexts.map((item) => <option key={item.context_hash} value={item.context_hash}>{item.topic} · {item.paper_count} papers · {new Date(item.built_at).toLocaleDateString()}</option>)}</select>{!matchingContexts.length && <small>No saved context matches this exact topic. Run once with retrieval enabled to create one.</small>}</div>}
          </div>}
          {error && <div role="alert" className="alert error-alert"><CircleAlert size={16} />{error}</div>}
          <div className="form-actions"><span><ShieldCheck size={15} /> Drafting a question does not change saved run history.</span><button className="button dark" disabled={active || question.trim().length < 3}><Play size={15} /> {active ? "Investigation running" : "Initiate investigation"}</button></div>
        </form>
      </section>
      <aside className="side-column">
        <section className="paper-surface provider-card"><div className="eyebrow">AGENT CONFIGURATION</div><h2>Research instruments</h2><div className="provider-row"><span>Structured model</span><code>{config?.models?.structured || "Not configured"}</code></div><div className="provider-row"><span>Answer model</span><code>{config?.models?.answer || "Not configured"}</code></div><div className="provider-row"><span>Paper sources</span><span>{config?.source_names?.length || 0} configured</span></div><p>Provider reachability is confirmed during an actual request.</p></section>
        <section className="paper-surface progress-card"><div className="section-heading"><div><div className="eyebrow">RUN PROGRESS</div><h2>{active ? "Following the investigation" : run ? run.status || "Run ready" : "The research sequence"}</h2></div>{active && <LoaderCircle className="spin" size={19} />}</div>
          <div className="stage-list">{(!run || run?.engine === "rla" ? ["search", "fetch", "score", "fulltext", "extract", "resolve", "graph", "traverse", "answer"] : ["plan_validated", "context_ready", "evidence_selected", "answer_ready", "citation_validation", "brief_saved"]).map((stage) => {
            const item = [...events].reverse().find((event) => event.kind === stage || event.payload?.phase === stage || event.payload?.stage_payload?.phase === stage);
            const label = item?.message || (stage === "fulltext" ? "Full-text stage is a Phase 2 stub" : "Waiting for this recorded stage");
            const state = item ? statusClass(/fail|error|refus/i.test(label) ? "failed" : /pending|scheduled|wait/i.test(label) ? "pending" : active && !["brief_saved", "citation_validation", "answer_ready"].includes(stage) ? "running" : "completed") : "quiet";
            return <div className="stage-row" key={stage}><span className="stage-dot">{state === "good" ? <Check size={12} /> : <i />}</span><span className="stage-name">{stage.replaceAll("_", " ")}</span><span className="stage-detail">{label}</span></div>;
          })}</div>
        </section>
      </aside>
    </div>

    {run && <div className="result-grid">
      <section className="paper-surface brief-card"><div className="section-heading"><div><div className="eyebrow">SYNTHESIS MONOGRAPH</div><h2>Evidence-grounded answer</h2></div><span className="subtle-metric"><BookOpen size={15} /> {count} cited sources</span></div>
        <div className="brief-question">{runQuestion || "Question not recorded in this run."}</div>
        <div className="answer-prose">{answer ? <CiteText text={answer} onCitation={inspectCitation} /> : <div className="placeholder-answer">The cited synthesis will appear here after extraction, graph construction, and answer generation.</div>}</div>
        <div className="citation-state">{validationEvent ? validationEvent.payload?.valid ? validationEvent.payload?.claim_support === "unverified" ? "Citation IDs passed validation. Claim-level support was not verified for this deterministic run." : `Citation IDs passed validation. Claim-level support: ${validationEvent.payload?.claim_support || "not recorded"}.` : `Citation validation failed; output was blocked. Unknown IDs: ${(validationEvent.payload?.unknown || []).join(", ") || "none recorded"}.` : answerEvent?.payload?.stripped_citations ? `Citation check complete · ${count} citations retained · ${answerEvent.payload.stripped_citations.length} unsupported IDs stripped.` : "Citation validation status was not recorded for this answer."}</div>
        {events.some((event) => event.kind === "brief_saved" && event.payload?.saved) && <a className="brief-link" href={`/api/runs/${run.source_run_id || run.run_id}/brief`} target="_blank" rel="noreferrer"><FileText size={15} /> Open cited research brief <ExternalLink size={13} /></a>}
      </section>
      <aside className="paper-surface evidence-panel"><div className="section-heading"><div><div className="eyebrow">EVIDENCE INSPECTOR</div><h2>Selected sources</h2></div>{badge(String(evidence.length || papers.length), "verified")}</div>
        {(evidence.length ? evidence : papers).slice(0, 10).map((item, index) => <PaperCard key={item.paper?.id || item.id || index} paper={item.paper || item} citation={item.citation || `P${index + 1}`} selected={selectedEvidence?.citation === (item.citation || `P${index + 1}`)} onSelect={() => setSelectedEvidence(item)} />)}
        {!evidence.length && !papers.length && <div className="empty-state"><BookOpen size={20} /><p>Paper evidence appears here as retrieval completes.</p></div>}
      </aside>
    </div>}
  </div>;
}

function TracePage({ events, active }) {
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState("all");
  const [selected, setSelected] = useState(null);
  const [cursor, setCursor] = useState(events.length);
  useEffect(() => { if (active) setCursor(events.length); }, [events.length, active]);
  const shown = useMemo(() => events.slice(0, cursor).filter((event) => (kind === "all" || event.kind === kind) && `${event.kind} ${event.phase || ""} ${event.message}`.toLowerCase().includes(filter.toLowerCase())), [events, cursor, filter, kind]);
  const kinds = [...new Set(events.map((event) => event.kind))];
  return <div><Hero kicker="RECORDED RUNTIME ACTIVITY" title="Execution trace">Inspect the ordered event stream recorded by the runtime. Select an event to see its full payload.</Hero>
    <section className="paper-surface trace-toolbar"><div className="trace-control"><button className="button light" onClick={() => setCursor(Math.max(0, cursor - 1))}>Previous event</button><input aria-label="Event timeline" type="range" min="0" max={events.length} value={Math.min(cursor, events.length)} onChange={(e) => setCursor(Number(e.target.value))} /><button className="button light" onClick={() => setCursor(Math.min(events.length, cursor + 1))}>Next event</button><span>{cursor} / {events.length}</span></div><div className="form-grid trace-filters"><label>Filter events<input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search messages" /></label><label>Event type<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="all">All recorded types</option>{kinds.map((value) => <option key={value}>{value}</option>)}</select></label></div></section>
    <div className="trace-layout"><section className="paper-surface trace-list">{shown.map((event, index) => <button key={`${event.seq || index}-${event.kind}`} className={`trace-row ${selected === event ? "trace-active" : ""}`} onClick={() => setSelected(event)}><span className="trace-seq">{String(event.seq || index + 1).padStart(3, "0")}</span><span className="trace-type">{event.phase || event.kind}</span><span className="trace-message">{event.message}</span><code>{event.timestamp ? new Date(Number(event.timestamp) * 1000).toLocaleTimeString() : "time not recorded"}</code></button>)}{!shown.length && <div className="empty-state">No recorded events match the current filter.</div>}</section>
      <aside className="paper-surface payload-card"><div className="eyebrow">SELECTED EVENT PAYLOAD</div>{selected ? <><h2>{selected.kind}</h2><pre>{JSON.stringify(selected, null, 2)}</pre></> : <p>Select an event to inspect its recorded fields.</p>}</aside></div>
  </div>;
}

function graphLayout(tasks) {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const depths = new Map();
  function depth(id, seen = new Set()) {
    if (depths.has(id)) return depths.get(id);
    if (seen.has(id)) return 0;
    const nextSeen = new Set(seen).add(id);
    const value = Math.max(0, ...(byId.get(id)?.depends_on || []).filter((parent) => byId.has(parent)).map((parent) => depth(parent, nextSeen) + 1));
    depths.set(id, value); return value;
  }
  const rows = new Map();
  const positions = new Map();
  tasks.forEach((task) => { const level = depth(task.id); const row = rows.get(level) || 0; rows.set(level, row + 1); positions.set(task.id, { x: 54 + level * 260, y: 48 + row * 174 }); });
  return { positions, width: Math.max(700, ...[...positions.values()].map((point) => point.x + 230)), height: Math.max(360, ...[...positions.values()].map((point) => point.y + 144)) };
}

function GraphView({ tasks, snapshot, selected, setSelected }) {
  const { positions, width, height } = useMemo(() => graphLayout(tasks), [tasks]);
  const edges = tasks.flatMap((task) => (task.depends_on || []).filter((id) => positions.has(id)).map((parent) => [parent, task.id]));
  return <div className="graph-scroll">
    <svg className="graph-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Recorded task dependency graph"><defs><marker id="arrow-teal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="#0f766e" /></marker><marker id="arrow-amber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="#b45309" /></marker></defs>
      {edges.map(([from, to]) => { const a = positions.get(from); const b = positions.get(to); const state = snapshot.taskStates[to]; const activeEdge = state === "running" || state === "ready"; return <path key={`${from}-${to}`} className={`graph-edge ${activeEdge ? "edge-live" : ""}`} d={`M ${a.x + 205} ${a.y + 54} C ${a.x + 250} ${a.y + 54}, ${b.x - 42} ${b.y + 54}, ${b.x - 10} ${b.y + 54}`} markerEnd={`url(#${activeEdge ? "arrow-amber" : "arrow-teal"})`} />; })}
      {tasks.map((task) => { const state = snapshot.taskStates[task.id] || "planned"; const point = positions.get(task.id); return <foreignObject key={task.id} x={point.x} y={point.y} width="215" height="145"><button className={`task-card ${statusClass(state)} ${selected === task.id ? "task-selected" : ""}`} onClick={() => setSelected(task.id)}><div className="task-card-top"><code>{task.id}</code>{badge(state, state)}</div><strong>{task.tool}</strong><p>{task.args?.query || task.args?.topic || task.tool}</p><small>{(task.depends_on || []).length ? `Depends on ${(task.depends_on || []).join(", ")}` : "Entry task"}</small></button></foreignObject>; })}
    </svg>
    {!tasks.length && <div className="empty-state">No validated task plan was recorded for this run.</div>}
  </div>;
}

function LabPage({ events, run }) {
  const [tab, setTab] = useState("graph");
  const [selected, setSelected] = useState(null);
  const [cursor, setCursor] = useState(events.length);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setCursor(events.length); }, [events.length]);
  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => setCursor((value) => {
      if (value >= events.length) { setPlaying(false); return events.length; }
      return value + 1;
    }), 650);
    return () => window.clearInterval(timer);
  }, [playing, events.length]);
  const snapshot = useMemo(() => core?.deriveSnapshot(events, cursor) || { tasks: [], taskStates: {}, readyQueue: [], activeTasks: [], stacks: {}, events: [] }, [events, cursor]);
  const selectedTask = snapshot.tasks.find((task) => task.id === selected) || snapshot.tasks[0];
  useEffect(() => { if (!selected && snapshot.tasks.length) setSelected(snapshot.tasks[0].id); }, [selected, snapshot.tasks]);
  return <div><Hero kicker="RUNTIME LABORATORY" title="Execution observatory">Explore only the dependency, scheduler, and stack state present in the selected run’s event history.</Hero>
    <div className="lab-tabs">{LAB_TABS.map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>)}<span>{run ? <><code>{run.run_id}</code> · {run.run_kind || run.mode || "Recorded run"}</> : "Select a run to inspect recorded state"}</span></div>
    <section className="paper-surface lab-timeline"><button className="button light" aria-label="Previous recorded event" onClick={() => { setPlaying(false); setCursor((value) => Math.max(0, value - 1)); }}><ArrowDown className="flip-arrow" size={14} /></button><button className="button light" onClick={() => setPlaying(!playing)}>{playing ? <Square size={13} /> : <Play size={13} />}{playing ? "Pause" : "Play"}</button><button className="button light" aria-label="Next recorded event" onClick={() => { setPlaying(false); setCursor((value) => Math.min(events.length, value + 1)); }}><ArrowRight size={14} /></button><input aria-label="Recorded event timeline" type="range" min="0" max={events.length} value={Math.min(cursor, events.length)} onChange={(event) => { setPlaying(false); setCursor(Number(event.target.value)); }} /><code>{cursor} / {events.length} recorded events</code></section>
    {tab === "graph" && <div className="lab-grid"><section className="paper-surface lab-main"><div className="section-heading"><div><div className="eyebrow">VALIDATED EXECUTION PLAN</div><h2>Dependency graph</h2><p>{snapshot.tasks.length} recorded tasks · {snapshot.tasks.reduce((sum, task) => sum + (task.depends_on || []).length, 0)} declared dependencies</p></div><div className="state-legend"><span><i className="good-dot" />Completed</span><span><i className="warm-dot" />In flight</span><span><i className="quiet-dot" />Queued</span></div></div><GraphView tasks={snapshot.tasks} snapshot={snapshot} selected={selectedTask?.id} setSelected={setSelected} /></section><aside className="paper-surface inspector">{selectedTask ? <><div className="eyebrow">TASK INSPECTOR</div><h2>{selectedTask.tool}</h2><code>{selectedTask.id}</code>{badge(snapshot.taskStates[selectedTask.id] || "planned", snapshot.taskStates[selectedTask.id] || "planned")}<h3>Declared dependencies</h3>{(selectedTask.depends_on || []).map((id) => <div className="dep-item" key={id}><GitBranch size={14} />{id}</div>)}{!(selectedTask.depends_on || []).length && <div className="missing-data">No dependencies recorded for this task.</div>}<pre>{JSON.stringify(selectedTask.args || {}, null, 2)}</pre></> : <div className="missing-data">No task plan recorded.</div>}</aside></div>}
    {tab === "queue" && <div className="metric-grid"><section className="paper-surface metric-card"><span>QUEUE POLICY</span><strong>{snapshot.queueRecorded ? "Recorded" : "Not recorded"}</strong><small>Scheduler policy is shown only if present in the selected run.</small></section><section className="paper-surface metric-card"><span>READY QUEUE</span><strong>{snapshot.queueRecorded ? snapshot.readyQueue.length : "—"}</strong><small>{snapshot.queueRecorded ? `${snapshot.activeTasks.length} active task(s)` : "Queue events were not recorded"}</small></section><section className="paper-surface metric-card"><span>DISPATCH TIMING</span><strong>—</strong><small>Latency not recorded</small></section><section className="paper-surface queue-panel"><div className="section-heading"><div><div className="eyebrow">SCHEDULER SNAPSHOT</div><h2>Ready queue</h2></div>{snapshot.queueRecorded ? badge(`${snapshot.readyQueue.length} queued`, "running") : badge("Not recorded", "quiet")}</div>{snapshot.queueRecorded ? snapshot.readyQueue.map((item, index) => <div className="queue-item" key={item.task_id || item.id || index}><span>{String(index + 1).padStart(2, "0")}</span><code>{item.task_id || item.id || JSON.stringify(item)}</code>{item.priority != null && <span>Priority {item.priority}</span>}</div>) : <div className="missing-data">This run did not record queue updates. No queue order is inferred.</div>}</section><section className="paper-surface queue-panel"><div className="eyebrow">ACTIVE TASKS</div><h2>Execution lanes</h2>{snapshot.activeTasks.length ? snapshot.activeTasks.map((item) => <div className="queue-item" key={item.task_id}><Activity size={14} /><code>{item.task_id}</code><span>Attempt {item.attempt ?? "not recorded"}</span></div>) : <div className="missing-data">No active task assignment was recorded at this event cursor.</div>}</section></div>}
    {tab === "stacks" && <div className="stack-layout"><section className="paper-surface task-dictionary"><div className="eyebrow">TASK STATE DICTIONARY</div><h2>Recorded tasks</h2>{snapshot.tasks.map((task) => <button key={task.id} className={`dictionary-row ${selected === task.id ? "dictionary-selected" : ""}`} onClick={() => setSelected(task.id)}><code>{task.id}</code><span>{task.tool}</span>{badge(snapshot.taskStates[task.id] || "planned", snapshot.taskStates[task.id] || "planned")}</button>)}</section><section className="paper-surface stack-inspector"><div className="eyebrow">EXECUTION STACK INSPECTOR</div><h2>{selectedTask?.tool || "No task selected"}</h2>{selectedTask ? (snapshot.stacks[selectedTask.id] || []).length ? [...snapshot.stacks[selectedTask.id]].reverse().map((frame, index) => <div className={`frame-card ${index === 0 ? "frame-top" : ""}`} key={index}><span>{index === 0 ? "TOP FRAME" : "FRAME"}</span><code>{typeof frame === "string" ? frame : frame.name || JSON.stringify(frame)}</code></div>) : <div className="missing-data">No stack frames were recorded for this task. Stack data is not inferred.</div> : <div className="missing-data">Select a recorded task to inspect its stack.</div>}</section></div>}
  </div>;
}

function LibraryPage({ history, replay, refreshHistory, busy }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("all");
  const results = history.filter((item) => `${item.topic} ${item.run_id}`.toLowerCase().includes(query.toLowerCase()) && (mode === "all" || item.mode === mode));
  return <div><Hero kicker="EPISTEMIC LEDGER" title="Investigation library">A searchable record of research runs, simulations, and replays with persisted event provenance.</Hero><section className="paper-surface library-shell"><div className="library-metrics"><div><span>TOTAL INVESTIGATIONS</span><strong>{history.length}</strong></div><div><span>LIVE RESEARCH</span><strong>{history.filter((item) => item.engine === "rla" || item.mode === "live").length}</strong></div><div><span>COMPLETED</span><strong>{history.filter((item) => item.status === "completed" || item.status === "partial").length}</strong></div></div><div className="library-toolbar"><label className="search-field"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search inquiry or run ID" /></label><select value={mode} onChange={(e) => setMode(e.target.value)}><option value="all">All modes</option><option value="live">Live research</option><option value="simulate">Simulation</option><option value="replay">Replay</option></select><button className="button light" onClick={refreshHistory}><Archive size={15} /> Refresh</button></div><div className="library-list">{results.map((item) => <article className="library-row" key={item.run_id}><div><div className="library-mode">{badge(item.engine === "rla" ? "Full literature pipeline" : item.mode, item.mode)} <code>{item.run_id}</code></div><h3>{item.topic || "Untitled investigation"}</h3><small>{item.event_count} recorded events · {item.models_used?.length || 0} model calls recorded</small></div><div className="library-provenance">{badge(item.status, item.status)}<span>{item.elapsed_ms != null ? `${(item.elapsed_ms / 1000).toFixed(1)}s` : "Duration not recorded"}</span><button className="button light" disabled={busy} onClick={() => replay(item.run_id)}><Play size={14} /> Inspect / replay</button></div></article>)}{!results.length && <div className="empty-state">No saved investigations match this search.</div>}</div></section></div>;
}

function App() {
  const workspace = useWorkspace();
  const [page, setPage] = useState("research");
  const [selectedEvidence, setSelectedEvidence] = useState(null);
  const snapshot = useMemo(() => core?.deriveSnapshot(workspace.events, workspace.events.length) || { events: [], tasks: [], taskStates: {} }, [workspace.events]);
  useEffect(() => { const refresh = () => workspace.refreshHistory().catch(() => {}); window.addEventListener("refresh-history", refresh); return () => window.removeEventListener("refresh-history", refresh); }, [workspace.refreshHistory]);
  useEffect(() => { if (workspace.run && workspace.events.length) setPage("research"); }, [workspace.run?.run_id]);
  const doReplay = async (id) => { try { await workspace.replay(id); setPage("research"); } catch (reason) { workspace.setError(reason.message); } };
  return <div className="app-frame"><Header page={page} setPage={setPage} run={workspace.run} connected={workspace.connected} /><SideRail page={page} setPage={setPage} history={workspace.history} run={workspace.run} replay={doReplay} /><main className="main-content">
    {workspace.error && page !== "research" && <div role="alert" className="alert error-alert"><CircleAlert size={16} />{workspace.error}</div>}
    {page === "research" && <ResearchPage workspace={workspace} selectedEvidence={selectedEvidence} setSelectedEvidence={setSelectedEvidence} />}
    {page === "trace" && <TracePage events={workspace.events} active={workspace.active} />}
    {page === "lab" && <LabPage events={workspace.events} run={workspace.run} />}
    {page === "library" && <LibraryPage history={workspace.history} replay={doReplay} refreshHistory={workspace.refreshHistory} busy={workspace.active} />}
    <footer className="page-footer"><span><ShieldCheck size={14} /> Claims remain tied to recorded source evidence.</span><span>{snapshot.events?.length || workspace.events.length} events in current view</span></footer>
  </main></div>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
