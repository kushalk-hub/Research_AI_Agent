import { formatDuration } from "../../lib/format.js";
import { formatCounts } from "../../lib/lab.js";

/** The RLA phase rail (design §4.1).
 *
 *  This is not a task graph: the phases run in order, and the rail says so.
 *  Arrows are drawn only when the backend declared the stage order in
 *  `run_started.pipeline_stages`; an old log is shown in the order it was
 *  recorded, without arrows, and the note explains why. */
export default function PhaseRail({ rail }) {
  return (
    <section className="panel lab-rail-panel" aria-labelledby="lab-rail-title">
      <div className="panel-head">
        <h2 id="lab-rail-title">Pipeline phases</h2>
        <span className="chip chip--muted">sequential</span>
        <span className="spacer" />
        <span className="num">
          {rail.stages.filter((stage) => stage.recorded).length} of {rail.stages.length} stages
          recorded
        </span>
      </div>

      <p className="lab-banner">
        RLA pipeline phases · sequential · not a task DAG. Each stage below ran once, in order;
        the counts are the ones the stage recorded.
      </p>

      <ol
        className="lab-rail"
        data-declared={rail.declared ? "true" : "false"}
        aria-label="Recorded pipeline phases"
      >
        {rail.stages.map((stage) => (
          <li
            className="lab-rail-stage"
            key={stage.id}
            data-recorded={stage.recorded ? "true" : "false"}
            data-stub={stage.stub ? "true" : "false"}
            data-class={stage.class}
          >
            <span className="lab-rail-order num">{stage.order + 1}</span>
            <h3>
              {stage.label}
              {stage.stub ? <span className="lab-stub">Phase 2 stub</span> : null}
            </h3>
            <p className="lab-rail-counts">
              {stage.stub
                ? "Not implemented yet."
                : stage.counts.length > 0
                  ? formatCounts(stage.counts)
                  : stage.recorded
                    ? "counts not recorded"
                    : "stage not recorded"}
            </p>
            <p className="lab-rail-time">
              {stage.timing
                ? `at ${formatDuration(stage.timing.started_ms)} · ${formatDuration(
                    stage.timing.duration_ms,
                  )}`
                : "timing not recorded"}
            </p>
          </li>
        ))}
      </ol>

      {rail.note ? <p className="panel-foot lab-note">{rail.note}</p> : null}
    </section>
  );
}
