import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { formatDuration } from "../lib/format.js";
import {
  barGeometry,
  filterRows,
  SEVERITY_LABEL,
  TRACE_CLASSES,
  TRACE_ROW_HEIGHT,
  traceItems,
  traceRows,
  traceSpan,
  traceSummary,
  virtualWindow,
} from "../lib/trace.js";
import NoRun from "../ui/NoRun.jsx";
import StatusChip from "../ui/StatusChip.jsx";
import TraceDetail from "./TraceDetail.jsx";

const SCALES = [
  ["fit", "Fit"],
  ["10000", "10 s"],
  ["1000", "1 s"],
];

const FALLBACK_HEIGHT = 480;
const SEVERITY_ORDER = ["error", "warn", "ok", "info"];

/** The recorded execution trace (UI-11).
 *
 *  Rows come from `lib/trace.js`, which uses the backend's phase/class/severity
 *  fields and falls back to the event kind for older logs. The waterfall only
 *  draws a bar where a duration was recorded; otherwise it draws a 2 px tick at
 *  the recorded offset. The body is virtualised, so a 381-event run renders a
 *  window of ~60 rows, not 381. */
export default function TraceView({ run, onFocusComposer }) {
  const events = useMemo(() => run?.events || [], [run]);
  const rows = useMemo(() => traceRows(events), [events]);
  const summary = useMemo(() => traceSummary(events, rows), [events, rows]);

  const [query, setQuery] = useState("");
  const [classes, setClasses] = useState([]);
  const [severities, setSeverities] = useState([]);
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [grouped, setGrouped] = useState(false);
  const [collapsed, setCollapsed] = useState([]);
  const [scale, setScale] = useState("fit");
  const [selectedSeq, setSelectedSeq] = useState(null);
  const [tab, setTab] = useState("summary");
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(FALLBACK_HEIGHT);

  const scrollRef = useRef(null);
  const tableRef = useRef(null);

  const presentClasses = useMemo(
    () => TRACE_CLASSES.filter((name) => rows.some((row) => row.className === name)),
    [rows],
  );

  const presentSeverities = useMemo(
    () => SEVERITY_ORDER.filter((name) => rows.some((row) => row.severity === name)),
    [rows],
  );

  const filtered = useMemo(
    () => filterRows(rows, { query, classes, severities, failuresOnly }),
    [rows, query, classes, severities, failuresOnly],
  );

  const items = useMemo(
    () => traceItems(filtered, { grouped, collapsed }),
    [filtered, grouped, collapsed],
  );

  // Keyboard navigation only visits rows that are actually rendered: a
  // collapsed phase group must not swallow ↑/↓ presses.
  const navigable = useMemo(
    () => items.filter((item) => item.type === "event").map((item) => item.row),
    [items],
  );

  const virtual = virtualWindow(items.length, scrollTop, height, TRACE_ROW_HEIGHT);
  const visible = items.slice(virtual.start, virtual.end);
  const scaleMs = scale === "fit" ? traceSpan(rows) : Number(scale);
  const selectedRow = rows.find((row) => row.seq === selectedSeq) || null;

  useEffect(() => {
    setQuery("");
    setClasses([]);
    setSeverities([]);
    setFailuresOnly(false);
    setGrouped(false);
    setCollapsed([]);
    setScale("fit");
    setSelectedSeq(null);
    setTab("summary");
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [run?.id]);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const measured = element.clientHeight;
    if (measured > 0 && measured !== height) setHeight(measured);
  }, [height]);

  useLayoutEffect(() => {
    const table = tableRef.current;
    if (!table) return;
    table.style.setProperty("--pad-top", `${virtual.topPad}px`);
    table.style.setProperty("--pad-bottom", `${virtual.bottomPad}px`);
    for (const bar of table.querySelectorAll("[data-bar-seq]")) {
      const seq = Number(bar.getAttribute("data-bar-seq"));
      const item = visible.find((entry) => entry.type === "event" && entry.row.seq === seq);
      if (!item) continue;
      const geometry = barGeometry(item.row, scaleMs);
      bar.style.setProperty("--bar-left", `${geometry.left}%`);
      bar.style.setProperty("--bar-width", `${geometry.width ?? 0}%`);
    }
  }, [virtual.topPad, virtual.bottomPad, visible, scaleMs]);

  useEffect(() => {
    if (selectedSeq === null) return;
    const index = items.findIndex(
      (entry) => entry.type === "event" && entry.row.seq === selectedSeq,
    );
    const element = scrollRef.current;
    if (index < 0 || !element) return;
    const viewport = element.clientHeight || height;
    const first = Math.floor(element.scrollTop / TRACE_ROW_HEIGHT);
    const shown = Math.ceil(viewport / TRACE_ROW_HEIGHT);
    if (index < first || index >= first + shown) {
      element.scrollTop = Math.max(
        0,
        index * TRACE_ROW_HEIGHT - Math.floor(shown / 2) * TRACE_ROW_HEIGHT,
      );
      setScrollTop(element.scrollTop);
    }
  }, [selectedSeq, items, height]);

  if (!run) {
    return (
      <NoRun
        title="No run is open"
        action={
          <button type="button" className="btn btn--primary" onClick={onFocusComposer}>
            Start a run
          </button>
        }
      >
        The execution trace lists exactly what the runtime recorded. Start a run, or open one from
        the Library, to see its events here.
      </NoRun>
    );
  }

  function toggleClass(name) {
    setClasses((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  }

  function toggleSeverity(name) {
    setSeverities((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  }

  function togglePhase(phase) {
    setCollapsed((current) =>
      current.includes(phase) ? current.filter((item) => item !== phase) : [...current, phase],
    );
  }

  function clearFilters() {
    setQuery("");
    setClasses([]);
    setSeverities([]);
    setFailuresOnly(false);
  }

  function jumpTo(seq) {
    const row = rows.find((item) => item.seq === seq);
    setQuery("");
    setClasses([]);
    setSeverities([]);
    setFailuresOnly(false);
    if (row && grouped) {
      setCollapsed((current) => current.filter((phase) => phase !== row.phase));
    }
    setSelectedSeq(seq);
    setTab("summary");
  }

  function onKeyDown(event) {
    if (navigable.length === 0) return;
    const index = navigable.findIndex((row) => row.seq === selectedSeq);
    let next = index;
    if (event.key === "ArrowDown") {
      next = index < 0 ? 0 : Math.min(navigable.length - 1, index + 1);
    } else if (event.key === "ArrowUp") {
      next = index < 0 ? navigable.length - 1 : Math.max(0, index - 1);
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = navigable.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    setSelectedSeq(navigable[next].seq);
  }

  const summaryDuration =
    summary.durationMs === null ? "duration not recorded" : formatDuration(summary.durationMs);

  return (
    <div className="view-inner">
      <section className="panel trace-panel" aria-labelledby="trace-title">
        <div className="panel-head">
          <h2 id="trace-title">Execution trace</h2>
          <StatusChip status={run.status} reason={run.statusReason} />
          <code className="mono">{run.id}</code>
          <span className="spacer" />
          <span className="num">
            {filtered.length} of {rows.length} events
          </span>
        </div>

        <div className="trace-toolbar">
          <label className="trace-search">
            <span className="visually-hidden">Filter events</span>
            <input
              type="search"
              value={query}
              placeholder="Filter by summary, phase, class or seq…"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>

          <div className="trace-chips" role="group" aria-label="Filter by class">
            {presentClasses.map((name) => (
              <button
                key={name}
                type="button"
                className="chip trace-class-chip"
                data-class={name}
                aria-pressed={classes.includes(name)}
                onClick={() => toggleClass(name)}
              >
                {name}
              </button>
            ))}
          </div>

          <div className="trace-chips" role="group" aria-label="Filter by status">
            {presentSeverities.map((name) => (
              <button
                key={name}
                type="button"
                className="chip trace-status-chip"
                data-sev={name}
                aria-pressed={severities.includes(name)}
                onClick={() => toggleSeverity(name)}
              >
                {SEVERITY_LABEL[name]}
              </button>
            ))}
          </div>

          <label className="trace-toggle">
            <input
              type="checkbox"
              checked={failuresOnly}
              onChange={(event) => setFailuresOnly(event.target.checked)}
            />
            Failures only
          </label>

          <label className="trace-toggle">
            <input
              type="checkbox"
              checked={grouped}
              onChange={(event) => setGrouped(event.target.checked)}
            />
            Group by phase
          </label>

          <div className="trace-scale" role="group" aria-label="Waterfall scale">
            {SCALES.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="btn btn--ghost btn--sm"
                aria-pressed={scale === value}
                onClick={() => setScale(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {rows.length === 0 ? (
          <p className="panel-note">No events recorded yet.</p>
        ) : filtered.length === 0 ? (
          <p className="panel-note">
            No events match these filters.{" "}
            <button type="button" className="trace-inline-link" onClick={clearFilters}>
              Clear filters
            </button>
          </p>
        ) : (
          <div className="trace-main">
            <div
              className="trace-scroll"
              ref={scrollRef}
              tabIndex={0}
              role="region"
              aria-label="Recorded events, oldest first"
              onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
              onKeyDown={onKeyDown}
            >
              <table className="trace-table" ref={tableRef}>
                <caption className="visually-hidden">
                  Recorded runtime events, oldest first. Select a row for its summary, payload,
                  timing and related events.
                </caption>
                <thead>
                  <tr>
                    <th scope="col" className="trace-col-seq">
                      #
                    </th>
                    <th scope="col" className="trace-col-phase">
                      Phase
                    </th>
                    <th scope="col" className="trace-col-class">
                      Class
                    </th>
                    <th scope="col">Summary</th>
                    <th scope="col" className="trace-col-status">
                      Status
                    </th>
                    <th scope="col" className="trace-col-duration">
                      Duration
                    </th>
                    <th scope="col" className="trace-col-waterfall">
                      Waterfall
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="trace-spacer trace-spacer--top" aria-hidden="true">
                    <td colSpan={7} />
                  </tr>

                  {visible.map((item) =>
                    item.type === "group" ? (
                      <tr key={`group-${item.phase}`} className="trace-group-row">
                        <td colSpan={7}>
                          <button
                            type="button"
                            className="trace-group-toggle"
                            aria-expanded={!item.collapsed}
                            onClick={() => togglePhase(item.phase)}
                          >
                            <span>{item.phase}</span>
                            <span className="num">{item.count} events</span>
                          </button>
                        </td>
                      </tr>
                    ) : (
                      <tr
                        key={`event-${item.row.seq}`}
                        className="trace-row"
                        data-selected={selectedSeq === item.row.seq ? "true" : undefined}
                        data-severity={item.row.severity}
                        onClick={() => setSelectedSeq(item.row.seq)}
                      >
                        <td className="num">
                          <button
                            type="button"
                            className="trace-seq"
                            aria-pressed={selectedSeq === item.row.seq}
                            aria-label={`Select event ${item.row.seq}: ${item.row.summary}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedSeq(item.row.seq);
                            }}
                          >
                            {item.row.seq}
                          </button>
                        </td>
                        <td>{item.row.phase}</td>
                        <td>
                          <span className="trace-class" data-class={item.row.className}>
                            {item.row.className}
                          </span>
                        </td>
                        <td className="wrap">{item.row.summary}</td>
                        <td>
                          <span className="trace-status" data-sev={item.row.severity}>
                            {SEVERITY_LABEL[item.row.severity]}
                          </span>
                        </td>
                        <td className="trace-duration">
                          {item.row.durationMs === null ? (
                            <span aria-label="duration not recorded">—</span>
                          ) : (
                            formatDuration(item.row.durationMs)
                          )}
                        </td>
                        <td>
                          <span className="trace-track">
                            <span
                              className="trace-bar"
                              data-tick={item.row.durationMs === null ? "true" : undefined}
                              data-sev={item.row.severity}
                              data-bar-seq={item.row.seq}
                            />
                          </span>
                        </td>
                      </tr>
                    ),
                  )}

                  <tr className="trace-spacer trace-spacer--bottom" aria-hidden="true">
                    <td colSpan={7} />
                  </tr>
                </tbody>
              </table>
            </div>

            <TraceDetail
              row={selectedRow}
              rows={rows}
              tab={tab}
              onTab={setTab}
              onSelect={jumpTo}
            />
          </div>
        )}

        <p className="trace-summary">
          <span className="num">{summary.events}</span> events ·{" "}
          <span className="num">{summary.phases}</span> phases ·{" "}
          <span className="num">{summary.failed}</span> failed · {summaryDuration}
        </p>
      </section>
    </div>
  );
}
