import { formatDuration } from "../../lib/format.js";

const STATE_LABEL = Object.freeze({
  planned: "Planned",
  ready: "Ready",
  dispatched: "Dispatched",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
  cancelled: "Cancelled",
});

const READY_REASON = Object.freeze({
  source_task: "source task",
  prerequisites_satisfied: "prerequisites satisfied",
});

function reasonLabel(value) {
  if (!value) return "not recorded";
  return READY_REASON[value] || value.replace(/_/g, " ");
}

/** The accessible alternative to the SVG: task, state, attempts, readiness. */
export default function StateTable({ model, selected, onSelect }) {
  if (model.tasks.length === 0) {
    return (
      <div className="lab-empty">
        <p>No task plan has been recorded at this point in the run.</p>
      </div>
    );
  }

  return (
    <div className="lab-state">
      <div className="lab-state-scroll">
        <table className="lab-state-table">
          <caption className="visually-hidden">
            Recorded task states, attempts, readiness reasons and durations
          </caption>
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">State</th>
              <th scope="col">Attempt</th>
              <th scope="col">Ready reason</th>
              <th scope="col">Remaining</th>
              <th scope="col">Duration</th>
            </tr>
          </thead>
          <tbody>
            {model.tasks.map((task) => (
              <tr
                key={task.id}
                data-state={task.state}
                data-selected={task.id === selected ? "true" : "false"}
              >
                <th scope="row">
                  <button
                    type="button"
                    className="lab-task-link"
                    onClick={() => onSelect?.(task.id)}
                    aria-pressed={task.id === selected}
                  >
                    <code>{task.id}</code>
                  </button>
                </th>
                <td>
                  <span className="lab-state-chip" data-state={task.state}>
                    {STATE_LABEL[task.state] || task.state}
                  </span>
                </td>
                <td className="num">
                  {task.attempt === null
                    ? "not recorded"
                    : `${task.attempt}${
                        model.workers.maxAttempts ? `/${model.workers.maxAttempts}` : ""
                      }`}
                </td>
                <td>{reasonLabel(task.readyReason)}</td>
                <td className="num">
                  {task.remaining === null ? "not recorded" : String(task.remaining)}
                </td>
                <td className="num">
                  {task.durationMs === null ? "not recorded" : formatDuration(task.durationMs)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="lab-note">
        A dash of “not recorded” means the log carries no value for that field at the playhead; it
        is never filled in with zero.
      </p>
    </div>
  );
}
