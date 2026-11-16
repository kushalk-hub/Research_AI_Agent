import { Play, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { formatDuration, shortId } from "../lib/format.js";
import { modeLabel, statusLabel, statusTone } from "../lib/events.js";
import StatusChip from "../ui/StatusChip.jsx";

/** Every recorded run the server can list. Opening one replays its recorded
 *  events; it never re-runs the research. */
export default function LibraryView({ history = [], onReplay, busy = false, liveActive = false }) {
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return history;
    return history.filter((item) =>
      [item.topic, item.run_id, item.mode, item.status]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [history, query]);

  return (
    <div className="view-inner">
      <section className="panel" aria-labelledby="library-title">
        <div className="panel-head">
          <h2 id="library-title">Library</h2>
          <span className="num">
            {query.trim()
              ? `${rows.length} of ${history.length} recorded runs`
              : `${history.length} recorded runs`}
          </span>
          <span className="spacer" />
          <label className="search-box">
            <Search size={14} aria-hidden="true" />
            <span className="visually-hidden">Filter runs</span>
            <input
              type="search"
              value={query}
              placeholder="Filter runs…"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>

        {rows.length === 0 ? (
          <p className="panel-note">
            {history.length === 0 ? "No runs recorded yet." : "No run matches this filter."}
          </p>
        ) : (
          <table className="data-table">
            <caption className="visually-hidden">
              Recorded runs with mode, status, event count and duration, and a replay action.
            </caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Topic</th>
                <th scope="col">Mode</th>
                <th scope="col">Status</th>
                <th scope="col">Events</th>
                <th scope="col">Duration</th>
                <th scope="col">
                  <span className="visually-hidden">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.run_id}>
                  <td className="mono">{shortId(item.run_id)}</td>
                  <td className="wrap">{item.topic || "Untitled investigation"}</td>
                  <td>{modeLabel(item.mode)}</td>
                  <td>
                    <StatusChip status={item.status} />
                  </td>
                  <td className="num">{item.event_count ?? 0}</td>
                  <td className="num">
                    {item.elapsed_ms ? formatDuration(item.elapsed_ms) : "not recorded"}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => onReplay(item.run_id)}
                      disabled={busy || liveActive}
                      title={
                        liveActive
                          ? "A run is already open. Finish or stop it before replaying."
                          : `Replay ${item.run_id}`
                      }
                    >
                      <Play size={13} aria-hidden="true" />
                      Replay
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="panel-foot">
          <span className="num">
            Replay reads the recorded event log. It does not re-execute providers or models.
          </span>
          {rows.length > 0 && (
            <span className={`badge`} data-tone={statusTone(rows[0].status)}>
              Newest: {statusLabel(rows[0].status)}
            </span>
          )}
        </div>
      </section>
    </div>
  );
}
