import { formatDuration } from "../lib/format.js";
import { previousRow, relatedFor, SEVERITY_LABEL } from "../lib/trace.js";

const TABS = [
  ["summary", "Summary"],
  ["payload", "Payload"],
  ["timing", "Timing"],
  ["related", "Related"],
];

function Rows({ entries }) {
  return (
    <dl className="trace-facts">
      {entries.map(([term, value]) => (
        <div key={term} className="trace-fact">
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Everything the record says about one selected event (design §5).
 *
 *  Tabs never invent a value: an absent duration says so, an empty payload says
 *  so, and "Related" lists only events that share a recorded task, provider or
 *  paper id. */
export default function TraceDetail({ row, rows, tab, onTab, onSelect }) {
  if (!row) {
    return (
      <aside className="trace-detail" aria-label="Event detail">
        <p className="panel-note">Select an event to read its record.</p>
      </aside>
    );
  }

  const payload = row.event?.payload || {};
  const previous = previousRow(row, rows);
  const gap =
    previous && previous.offsetMs !== null && row.offsetMs !== null
      ? row.offsetMs - previous.offsetMs
      : null;
  const related = relatedFor(row, rows);

  return (
    <aside className="trace-detail" aria-label="Event detail">
      <div className="trace-detail-head">
        <h3>Event #{row.seq}</h3>
        <span className="trace-status" data-sev={row.severity}>
          {SEVERITY_LABEL[row.severity]}
        </span>
      </div>

      <div className="trace-tabs" role="tablist" aria-label="Event detail sections">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`trace-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`trace-panel-${key}`}
            className="trace-tab"
            onClick={() => onTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div
        className="trace-tab-panel"
        role="tabpanel"
        id={`trace-panel-${tab}`}
        aria-labelledby={`trace-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "summary" && (
          <Rows
            entries={[
              ["Summary", row.summary],
              ["Kind", <code className="mono">{row.kind}</code>],
              ["Phase", row.phase],
              ["Class", row.className],
              ["Status", SEVERITY_LABEL[row.severity]],
              [
                "Duration",
                row.durationMs === null
                  ? "not recorded for this event"
                  : formatDuration(row.durationMs),
              ],
            ]}
          />
        )}

        {tab === "payload" && (
          <details className="trace-payload" open={false}>
            <summary>
              Payload JSON
              {Object.keys(payload).length ? ` (${Object.keys(payload).length} keys)` : ""}
            </summary>
            {Object.keys(payload).length === 0 ? (
              <p className="panel-note">No payload was recorded for this event.</p>
            ) : (
              <pre className="trace-json">{JSON.stringify(payload, null, 2)}</pre>
            )}
          </details>
        )}

        {tab === "timing" && (
          <Rows
            entries={[
              [
                "Start offset",
                row.offsetMs === null ? "no timestamp recorded" : formatDuration(row.offsetMs),
              ],
              [
                "Duration",
                row.durationMs === null ? "not recorded" : formatDuration(row.durationMs),
              ],
              [
                "Gap since previous",
                gap === null
                  ? "no adjacent timestamps recorded"
                  : formatDuration(Math.max(0, gap)),
              ],
              ["Previous event", previous ? `#${previous.seq} ${previous.summary}` : "none"],
            ]}
          />
        )}

        {tab === "related" && (
          <div className="trace-related">
            {related.length === 0 ? (
              <p className="panel-note">
                No related events were recorded for this event.
              </p>
            ) : (
              <>
                <p className="trace-related-note">
                  Recorded links only: same task, provider or paper id.
                </p>
                <ul className="trace-related-list">
                  {related.map(({ row: other, reason }) => (
                    <li key={`${other.seq}`}>
                      <button
                        type="button"
                        className="trace-related-link"
                        onClick={() => onSelect(other.seq)}
                      >
                        <span className="num">#{other.seq}</span>
                        <span>{other.summary}</span>
                        <span className="trace-related-reason">{reason}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
