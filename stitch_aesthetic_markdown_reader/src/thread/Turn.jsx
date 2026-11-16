import { Activity } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { modeLabel, phaseLabel } from "../lib/events.js";
import StatusChip from "../ui/StatusChip.jsx";
import AnswerCard from "./AnswerCard.jsx";

/** Design §5.1: the in-thread working list updates at most twice a second, so a
 *  burst of events cannot flood a screen reader. */
export const WORKING_THROTTLE_MS = 500;

function workedForLabel(workedFor) {
  const steps = workedFor.steps;
  const unit = steps === 1 ? "step" : "steps";
  if (!workedFor.duration) return `Worked for an unrecorded duration · ${steps} ${unit}`;
  return `Worked for ${workedFor.duration} · ${steps} ${unit}`;
}

/** One question and the evidence-backed state of the run that answers it.
 *
 *  Working lines are the recorded one-liners (`describeEvent()`), capped at six
 *  plus "and N more". On the terminal event the list collapses to the recorded
 *  duration and step count; a missing duration is stated, never guessed. The
 *  answer card shows only what a recorded answer event actually contains. */
export default function Turn({ turn, onOpenTrace }) {
  const live = !turn.finished && (turn.stream === "live" || turn.stream === "connecting");
  const [snapshot, setSnapshot] = useState(turn.working);
  const latest = useRef(turn.working);
  latest.current = turn.working;

  useEffect(() => {
    if (!live) {
      setSnapshot(turn.working);
      return undefined;
    }
    const timer = setInterval(() => setSnapshot(latest.current), WORKING_THROTTLE_MS);
    return () => clearInterval(timer);
    // `turn.working` is a fresh object each render; the effect must key on the
    // run identity and liveness, not on object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, turn.id]);

  const working = snapshot || { lines: [], more: 0 };

  return (
    <article className="turn" aria-label={`Run ${turn.id}`}>
      <p className="turn-question">{turn.question}</p>

      <div className="turn-card">
        <div className="turn-head">
          <strong>{turn.engineLabel}</strong>
          <StatusChip
            status={turn.stopping ? "stopping" : turn.status}
            reason={
              turn.stopping
                ? "Stop requested; waiting for the recorded outcome."
                : turn.statusReason
            }
          />
          <span className="badge">{modeLabel(turn.mode)}</span>
          <code className="mono">{turn.id}</code>
          <span className="num">{turn.eventCount} events</span>
        </div>

        {turn.eventCount === 0 ? (
          <p className="turn-note">Waiting for the first recorded event…</p>
        ) : !turn.finished ? (
          <div className="working" aria-live={live ? "polite" : "off"}>
            <ol className="working-list" aria-label="Recent recorded events">
              {working.lines.map((line) => (
                <li key={line.seq} data-phase={line.phase}>
                  <span className="working-phase">{phaseLabel(line.phase)}</span>
                  <span className="working-text">{line.text}</span>
                </li>
              ))}
            </ol>
            {working.more > 0 && (
              <p className="working-more">and {working.more} more</p>
            )}
          </div>
        ) : null}

        {turn.answer && <AnswerCard answer={turn.answer} />}

        {turn.stream === "error" && (
          <p className="turn-note" role="status">
            The event stream disconnected. Recorded events are still shown; reload to reconnect.
          </p>
        )}

        {turn.warnings > 0 && (
          <p className="turn-note">
            {turn.warnings} unreadable log line{turn.warnings === 1 ? " was" : "s were"} skipped;
            the rest of the record is shown.
          </p>
        )}

        {turn.statusReason && <p className="turn-note">{turn.statusReason}</p>}

        {turn.finished && (
          <div className="turn-actions">
            {turn.workedFor ? (
              <button
                type="button"
                className="btn btn--sm worked-for"
                onClick={onOpenTrace}
                aria-label={`${workedForLabel(turn.workedFor)} — open execution trace`}
              >
                <Activity size={14} aria-hidden="true" />
                <span>{workedForLabel(turn.workedFor)}</span>
              </button>
            ) : (
              <button type="button" className="btn btn--sm" onClick={onOpenTrace}>
                <Activity size={14} aria-hidden="true" />
                Open execution trace
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
