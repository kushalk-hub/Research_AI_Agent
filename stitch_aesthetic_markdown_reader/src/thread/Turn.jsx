import { Activity } from "lucide-react";
import { modeLabel } from "../lib/events.js";
import StatusChip from "../ui/StatusChip.jsx";

/** One question and the evidence-backed state of the run that answers it.
 *  The working lines are the last recorded events, verbatim through
 *  `describeEvent()`; they are not a spinner with invented copy. */
export default function Turn({ turn, onOpenTrace }) {
  const live = turn.stream === "live" || turn.stream === "connecting";

  return (
    <article className="turn" aria-label={`Run ${turn.id}`}>
      <p className="turn-question">{turn.question}</p>

      <div className="turn-card">
        <div className="turn-head">
          <strong>{turn.engineLabel}</strong>
          <StatusChip status={turn.status} reason={turn.statusReason} />
          <span className="badge">{modeLabel(turn.mode)}</span>
          <code className="mono">{turn.id}</code>
          <span className="num">{turn.eventCount} events</span>
        </div>

        {turn.eventCount === 0 ? (
          <p className="turn-note">Waiting for the first recorded event…</p>
        ) : (
          <ol className="working-list" aria-live={live ? "polite" : "off"} aria-label="Recent recorded events">
            {turn.recent.map((line) => (
              <li key={line.seq}>{line.text}</li>
            ))}
          </ol>
        )}

        {turn.stream === "error" && (
          <p className="turn-note" role="status">
            The event stream disconnected. Recorded events are still shown; reload to reconnect.
          </p>
        )}

        {turn.statusReason && <p className="turn-note">{turn.statusReason}</p>}

        {turn.finished && (
          <div className="turn-actions">
            <button type="button" className="btn btn--sm" onClick={onOpenTrace}>
              <Activity size={14} aria-hidden="true" />
              Open execution trace
            </button>
          </div>
        )}
      </div>
    </article>
  );
}
