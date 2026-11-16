import { selectPlan } from "../store/selectors.js";
import { modeLabel, statusLabel } from "../lib/events.js";
import NoRun from "../ui/NoRun.jsx";

/** Slice 1 shows the recorded plan as levels. The labelled phase graph, queue,
 *  workers and stack views arrive in slice 8; nothing here is inferred beyond
 *  what `plan_validated` / `plan_received` actually recorded. */
export default function LabView({ state, run, onFocusComposer }) {
  if (!run) {
    return (
      <NoRun
        title="No plan recorded"
        action={
          <button type="button" className="btn btn--primary" onClick={onFocusComposer}>
            Start a run
          </button>
        }
      >
        The Lab renders the plan the runtime accepted: task levels, dependencies and scheduler
        state. Start a run to record one.
      </NoRun>
    );
  }

  const plan = selectPlan(state, run);
  const levels = plan.levels;
  const hasPlan = levels.length > 0 || plan.tasks.length > 0;
  const taskCount =
    plan.tasks.length ||
    levels.reduce((total, level) => total + (Array.isArray(level) ? level.length : 0), 0);

  return (
    <div className="view-inner">
      <section className="panel" aria-labelledby="lab-title">
        <div className="panel-head">
          <h2 id="lab-title">Plan</h2>
          <span className="badge">{modeLabel(run.mode)}</span>
          <code className="mono">{run.id}</code>
          <span className="spacer" />
          <span className="num">
            {taskCount} tasks · {levels.length} levels · {statusLabel(run.status)}
          </span>
        </div>

        {!hasPlan ? (
          <p className="panel-note">
            This run has not recorded a plan yet. The full Lab (dependency graph, queue and stacks)
            reads only recorded plan and scheduler events.
          </p>
        ) : (
          <div className="plan-levels">
            {levels.map((level, index) => (
              <section className="plan-level" key={`level-${index}`} aria-label={`Level ${index}`}>
                <h3>
                  Level {index}
                  <span className="num">{Array.isArray(level) ? level.length : 0} tasks</span>
                </h3>
                <ul>
                  {(Array.isArray(level) ? level : []).map((taskId) => (
                    <li key={String(taskId)}>
                      <code>{String(taskId)}</code>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
