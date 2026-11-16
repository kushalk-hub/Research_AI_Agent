import { Play, Sparkles } from "lucide-react";
import { useStartRun } from "../composer/useStartRun.js";

/** The first screen: one sentence about what the tool does, one demo action, and
 *  the composer below. No invented examples, no fake progress. */
export default function EmptyThread({ onFocusComposer }) {
  const { startDemo, busy, error, clearError } = useStartRun();

  return (
    <div className="empty-thread">
      <span className="chip" data-tone="live">
        Event-backed workspace
      </span>
      <h1>What should we investigate?</h1>
      <p>Every panel on this page reads from the events a run records.</p>

      <div className="demo-row">
        <button
          type="button"
          className="btn btn--primary"
          onClick={startDemo}
          disabled={busy}
          title="Runs the fixed fixture plan. No provider calls."
        >
          <Play size={16} aria-hidden="true" />
          {busy ? "Starting…" : "Run the deterministic demo"}
        </button>
        <button type="button" className="btn" onClick={onFocusComposer}>
          <Sparkles size={16} aria-hidden="true" />
          Write my own question
        </button>
      </div>
      <p className="demo-hint">
        The demo uses a fixed 8-task plan and the fixture planner. It makes no network calls.
      </p>

      {error && (
        <div className="composer-error" role="alert">
          <div>
            <strong>{error.message}</strong>
          </div>
          <button type="button" className="btn btn--ghost btn--sm" onClick={clearError}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
