import { useCallback, useEffect, useState } from "react";
import { modeLabel, statusLabel } from "../lib/events.js";
import {
  formatCounts,
  LAB_PIPELINES,
  LAB_TABS,
  labCaption,
  labPipeline,
  phaseRail,
  schedulerModel,
} from "../lib/lab.js";
import NoRun from "../ui/NoRun.jsx";
import PhaseRail from "./lab/PhaseRail.jsx";
import PlanGraph from "./lab/PlanGraph.jsx";
import PlaybackBar from "./lab/PlaybackBar.jsx";
import QueuePanel from "./lab/QueuePanel.jsx";
import StackPanel from "./lab/StackPanel.jsx";
import StateTable from "./lab/StateTable.jsx";

const DEFAULT_LAB = Object.freeze({
  tab: "plan",
  cursor: null, // null = follow the head of the run
  playing: false,
  speed: 1,
});

const CAPTION_KEY = "fods.lab.captions.dismissed";
const CAPTION_LIMIT = 60;

function readDismissed() {
  try {
    const raw = globalThis.sessionStorage?.getItem(CAPTION_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(Number(value) || 0, high));
}

/** The FODS Lab (UI-07).
 *
 *  Two recorded structures share one page and the page says which one it is:
 *  a FODS/demo run has a plan, a queue, task stacks and worker concurrency; an
 *  RLA run has the phase rail and no task DAG. Playback always reads the log at
 *  the playhead, so scrubbing back cannot show a state the run had not reached.
 */
export default function LabView({ state, run, onFocusComposer, onLab }) {
  const [localLab, setLocalLab] = useState(() => ({ ...DEFAULT_LAB, ...(state?.lab || {}) }));
  const [selected, setSelected] = useState(null);
  const [dismissed, setDismissed] = useState(readDismissed);

  const updateLab = useCallback(
    (patch) => {
      setLocalLab((previous) => ({ ...previous, ...patch }));
      onLab?.(patch);
    },
    [onLab],
  );

  const events = run?.events || [];
  const total = events.length;
  const lab = localLab;
  const at = lab.cursor === null ? total : clamp(lab.cursor, 0, total);
  const pipeline = run ? labPipeline(run) : "unknown";

  useEffect(() => {
    if (!lab.playing) return undefined;
    if (at >= total) {
      updateLab({ playing: false });
      return undefined;
    }
    const delay = 1000 / (4 * (lab.speed || 1));
    const timer = setTimeout(() => {
      const next = at + 1;
      updateLab(next >= total ? { cursor: null, playing: false } : { cursor: next });
    }, delay);
    return () => clearTimeout(timer);
  }, [lab.playing, lab.speed, at, total, updateLab]);

  if (!run) {
    return (
      <NoRun
        title="No run to show"
        action={
          <button type="button" className="btn btn--primary" onClick={onFocusComposer}>
            Start a run
          </button>
        }
      >
        The Lab renders the structure a run actually recorded. Start a run, or replay one from the
        Library, to see its phases, plan, queue, stacks and states.
      </NoRun>
    );
  }

  if (pipeline === "unknown") {
    return (
      <NoRun title="No recorded structure">
        This log records no plan and no pipeline phases, so there is nothing to draw. Open the trace
        to read the events themselves.
      </NoRun>
    );
  }

  if (pipeline === LAB_PIPELINES.phases) {
    const rail = phaseRail(run);
    const withCounts = rail.stages.filter((stage) => stage.counts.length > 0);
    return (
      <div className="view-inner lab-view">
        <header className="lab-header">
          <div className="lab-heading">
            <h2>Recorded structure</h2>
            <span className="chip chip--muted">RLA pipeline phases</span>
            <span className="chip" data-tone="live">
              {modeLabel(run.mode)}
            </span>
          </div>
          <p className="lab-topic">{run.topic || run.question || "Untitled run"}</p>
          <p className="lab-summary num">
            {rail.stages.filter((stage) => stage.recorded).length} recorded phases ·{" "}
            {withCounts.length} with counts · {total} events · {statusLabel(run.status)}
          </p>
        </header>

        <PhaseRail rail={rail} />

        <section className="panel lab-rla-foot" aria-labelledby="lab-rla-foot-title">
          <div className="panel-head">
            <h2 id="lab-rla-foot-title">What this run recorded</h2>
          </div>
          <p>
            The phase rail is the whole structure: this run records sequential literature phases,
            not a dependency plan. Counts above are copied from each phase's recorded payload
            {withCounts.length > 0 ? "" : "; this log recorded no stage counts"}.
          </p>
          {withCounts.length > 0 ? (
            <ul className="lab-count-list">
              {withCounts.map((stage) => (
                <li key={stage.id}>
                  <strong>{stage.label}</strong> <span className="num">{formatCounts(stage.counts)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
    );
  }

  const visible = events.slice(0, at);
  const model = schedulerModel(visible);
  const tab = LAB_TABS.some((item) => item.id === lab.tab) ? lab.tab : "plan";
  const selectedId = selected && model.byId.has(selected) ? selected : null;
  const caption = labCaption(run, at);
  const visibleCaption = caption && !dismissed.has(caption.id) ? caption : null;
  const live = run.stream === "live" && at >= total;

  function dismissCaption(id) {
    setDismissed((previous) => {
      const next = new Set(previous);
      next.add(id);
      const kept = [...next].slice(-CAPTION_LIMIT);
      try {
        globalThis.sessionStorage?.setItem(CAPTION_KEY, JSON.stringify(kept));
      } catch {
        /* storage is optional */
      }
      return new Set(kept);
    });
  }

  function scrub(value) {
    const next = clamp(value, 0, total);
    updateLab({ cursor: next >= total ? null : next, playing: false });
  }

  return (
    <div className="view-inner lab-view">
      <header className="lab-header">
        <div className="lab-heading">
          <h2>Recorded structure</h2>
          <span className="chip chip--muted">Dependency plan</span>
          <span className="chip" data-tone={live ? "live" : "muted"}>
            {modeLabel(run.mode)}
          </span>
          {model.plan.rejected ? (
            <span className="chip" data-tone="err">
              Plan rejected
            </span>
          ) : null}
        </div>
        <p className="lab-topic">{run.topic || run.question || "Untitled run"}</p>
        <p className="lab-summary num">
          {model.counts.total} tasks · {model.counts.completed} completed
          {model.counts.cancelled > 0 ? ` · ${model.counts.cancelled} cancelled` : ""}
          {model.counts.failed > 0 ? ` · ${model.counts.failed} failed or blocked` : ""} ·{" "}
          {model.plan.levels.length} levels · {statusLabel(run.status)}
        </p>
      </header>

      <PlaybackBar
        run={run}
        cursor={lab.cursor}
        playing={lab.playing}
        speed={lab.speed}
        caption={visibleCaption}
        onScrub={scrub}
        onPlaying={(playing) => updateLab({ playing })}
        onSpeed={(speed) => updateLab({ speed })}
        onDismissCaption={dismissCaption}
      />

      <div className="lab-tabs" role="tablist" aria-label="Lab views">
        {LAB_TABS.map((item, index) => {
          const active = item.id === tab;
          return (
            <button
              type="button"
              role="tab"
              key={item.id}
              id={`lab-tab-${item.id}`}
              aria-selected={active}
              aria-controls={`lab-panel-${item.id}`}
              tabIndex={active ? 0 : -1}
              className="lab-tab"
              onClick={() => updateLab({ tab: item.id })}
              onKeyDown={(event) => {
                const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                event.preventDefault();
                const nextIndex = (index + step + LAB_TABS.length) % LAB_TABS.length;
                const next = LAB_TABS[nextIndex];
                updateLab({ tab: next.id });
                globalThis.document?.getElementById(`lab-tab-${next.id}`)?.focus();
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div
        className="lab-panel"
        role="tabpanel"
        id={`lab-panel-${tab}`}
        aria-labelledby={`lab-tab-${tab}`}
      >
        {tab === "plan" ? (
          <PlanGraph
            plan={model.plan}
            model={model}
            selected={selectedId}
            onSelect={setSelected}
          />
        ) : null}
        {tab === "queue" ? <QueuePanel model={model} /> : null}
        {tab === "stacks" ? <StackPanel model={model} /> : null}
        {tab === "state" ? (
          <StateTable model={model} selected={selectedId} onSelect={setSelected} />
        ) : null}
      </div>
    </div>
  );
}
