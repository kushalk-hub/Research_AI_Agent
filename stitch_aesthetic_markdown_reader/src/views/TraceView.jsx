import { useMemo, useState } from "react";
import { describeEvent, phaseOf, statusLabel } from "../lib/events.js";
import StatusChip from "../ui/StatusChip.jsx";
import NoRun from "../ui/NoRun.jsx";

const PAGE = 250;

/** Slice 1 keeps the trace readable, not clever: every row is a recorded event.
 *  The waterfall, filters and detail pane arrive in slice 7. */
export default function TraceView({ run, onFocusComposer }) {
  const [shown, setShown] = useState(PAGE);
  const events = useMemo(() => run?.events || [], [run]);

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

  const visible = events.slice(0, shown);

  return (
    <div className="view-inner">
      <section className="panel" aria-labelledby="trace-title">
        <div className="panel-head">
          <h2 id="trace-title">Execution trace</h2>
          <StatusChip status={run.status} reason={run.statusReason} />
          <code className="mono">{run.id}</code>
          <span className="spacer" />
          <span className="num">
            {visible.length} of {events.length} events
          </span>
        </div>

        {events.length === 0 ? (
          <p className="panel-note">No events recorded yet.</p>
        ) : (
          <table className="data-table">
            <caption className="visually-hidden">
              Recorded runtime events, oldest first, with sequence number, kind, phase and summary.
            </caption>
            <thead>
              <tr>
                <th scope="col">Seq</th>
                <th scope="col">Kind</th>
                <th scope="col">Phase</th>
                <th scope="col">Summary</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((event) => (
                <tr key={event.seq}>
                  <td className="num">{event.seq}</td>
                  <td className="mono">{event.kind}</td>
                  <td>{phaseOf(event)}</td>
                  <td className="wrap">{describeEvent(event)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {events.length > shown && (
          <div className="panel-foot">
            <span className="num">
              Showing the first {shown} events ({statusLabel(run.status)}).
            </span>
            <button type="button" className="btn btn--sm" onClick={() => setShown(shown + PAGE)}>
              Show {Math.min(PAGE, events.length - shown)} more
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
