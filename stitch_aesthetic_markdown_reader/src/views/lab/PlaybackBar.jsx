import { Pause, Play, StepBack, StepForward, X } from "lucide-react";
import { classOf } from "../../lib/trace.js";
import { LAB_PLAYBACK_SPEEDS } from "../../lib/lab.js";

const BASE_EVENTS_PER_SECOND = 4;

function speedLabel(speed) {
  return `${BASE_EVENTS_PER_SECOND * speed} ev/s`;
}

/** Playback over the recorded events, with a LIVE/REPLAY badge (design §4.5).
 *
 *  Speed is events per second, not wall-clock: the caption says so, because a
 *  replay is a serial render of a log and must not imply live concurrency. */
export default function PlaybackBar({
  run,
  cursor,
  playing,
  speed,
  caption,
  onScrub,
  onPlaying,
  onSpeed,
  onDismissCaption,
}) {
  const events = run?.events || [];
  const total = events.length;
  const head = Math.max(0, Math.min(Number(cursor) || 0, total));
  const at = cursor === null || cursor === undefined ? total : head;
  const live = run?.stream === "live" && at >= total;
  const historical = Boolean(run?.historical) || run?.kind === "replay";
  const percent = total > 0 ? Math.round((at / total) * 100) : 0;
  const remaining = total - at;

  return (
    <section className="lab-playback" aria-label="Playback">
      <div className="lab-playback-head">
        <span className="lab-mode" data-mode={live ? "live" : "replay"}>
          {live ? "LIVE" : "REPLAY"}
        </span>
        <span className="num">
          {at} of {total} events · {percent}%
        </span>
        <span className="spacer" />
        <div className="lab-transport" role="group" aria-label="Playback controls">
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            onClick={() => onScrub(Math.max(0, at - 1))}
            disabled={at <= 0}
            aria-label="Step back one event"
          >
            <StepBack size={16} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="btn btn--primary btn--icon"
            onClick={() => {
              if (playing) {
                onPlaying(false);
                return;
              }
              if (at >= total) onScrub(0);
              onPlaying(true);
            }}
            aria-label={playing ? "Pause playback" : at >= total ? "Replay from the start" : "Play"}
          >
            {playing ? (
              <Pause size={16} aria-hidden="true" />
            ) : (
              <Play size={16} aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            onClick={() => onScrub(Math.min(total, at + 1))}
            disabled={at >= total}
            aria-label="Step forward one event"
          >
            <StepForward size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="lab-scrub">
        <div className="lab-scrub-track" aria-hidden="true">
          {events.map((event, index) => (
            <span
              className="lab-scrub-tick"
              key={event?.seq ?? index}
              data-class={classOf(event)}
              data-played={index < at ? "true" : "false"}
            />
          ))}
        </div>
        <input
          className="lab-scrub-input"
          type="range"
          min="0"
          max={total}
          step="1"
          value={at}
          onChange={(event) => onScrub(Number(event.target.value))}
          aria-label="Playback position"
          aria-valuetext={`${at} of ${total} events`}
        />
      </div>

      <div className="lab-playback-foot">
        <div className="lab-speeds" role="group" aria-label="Playback speed, events per second">
          {LAB_PLAYBACK_SPEEDS.map((value) => (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              key={value}
              aria-pressed={speed === value}
              onClick={() => onSpeed(value)}
            >
              {speedLabel(value)}
            </button>
          ))}
        </div>
        <p className="lab-playback-note">
          {speedLabel(speed)} — recorded order, not wall-clock.
          {historical
            ? " Serial render of a saved log — this is not live concurrency."
            : live
              ? " Following the live event stream."
              : " Reviewing recorded events — not live concurrency."}
        </p>
        <span className="spacer" />
        <span className="num">{remaining} remaining</span>
      </div>

      {caption ? (
        <figure className="lab-caption" aria-live="polite">
          <figcaption>Concept caption</figcaption>
          <p>{caption.text}</p>
          <button
            type="button"
            className="btn btn--ghost btn--icon lab-caption-dismiss"
            onClick={() => onDismissCaption?.(caption.id)}
            aria-label="Dismiss caption"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </figure>
      ) : null}
    </section>
  );
}
