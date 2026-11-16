import { cycleTasks, layoutGraph, TASK_STATES } from "../../lib/lab.js";
import { formatDuration, shorten } from "../../lib/format.js";

/** State label and tone for a task, from the fold in `lib/lab.js`. */
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

function stateOf(model, id) {
  return model?.byId?.get(id) || null;
}

function edgeSet(pairs) {
  const set = new Set();
  for (let index = 0; index < pairs.length; index += 1) {
    const first = pairs[index];
    const second = pairs[(index + 1) % pairs.length];
    if (!first || !second) continue;
    // Edges are drawn parent -> child, while the cycle walk follows
    // `dependsOn`; record both directions so the highlighted ring closes.
    set.add(`${first}->${second}`);
    set.add(`${second}->${first}`);
  }
  return set;
}

/** The dependency DAG, laid out on the levels the runtime validated.
 *
 *  Column = recorded level, row = index inside that level, so a replay lays out
 *  identically. Node state comes from the fold at the current playhead; an edge
 *  is `done` once its parent completed and `hot` while its child waits in the
 *  ready queue. Nothing is inferred about edges the plan did not declare.
 */
export default function PlanGraph({ plan, model, selected, onSelect }) {
  const tasks = plan?.tasks || [];
  if (tasks.length === 0) {
    return (
      <div className="lab-empty">
        <p>No task plan has been recorded at this point in the run.</p>
      </div>
    );
  }

  const layout = layoutGraph(plan);
  const cycle = plan.rejected ? cycleTasks(plan.rejectedTasks) : [];
  const hotEdges = edgeSet([]);
  for (const task of tasks) {
    const state = stateOf(model, task.id)?.state;
    if (state !== "ready") continue;
    for (const parentId of task.dependsOn) {
      if (stateOf(model, parentId)?.state === "completed") hotEdges.add(`${parentId}->${task.id}`);
    }
  }

  const selectedTask = selected ? tasks.find((task) => task.id === selected) : null;
  const selectedState = selectedTask ? stateOf(model, selectedTask.id) : null;

  return (
    <div className="lab-graph">
      {plan.rejected ? (
        <div className="lab-cycle" role="status">
          <strong>Cycle detected by replay analysis of the recorded plan</strong>
          <p>
            The runtime rejected it, so no task executed.
            {cycle.length > 0 ? (
              <>
                {" "}
                Rejected path: <code>{cycle.join(" → ")}</code>
              </>
            ) : null}
          </p>
          {plan.rejectionMessage ? <p className="lab-cycle-message">{plan.rejectionMessage}</p> : null}
        </div>
      ) : null}

      {plan.levels.length > 3 ? (
        <p className="lab-note">
          The graph is laid out in {plan.levels.length} columns — scroll sideways to follow every
          level.
        </p>
      ) : null}

      <div className="lab-graph-scroll" tabIndex={0} aria-label="Dependency graph, scrollable">        <svg
          className="lab-svg"
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-label={`Recorded dependency graph: ${tasks.length} tasks across ${plan.levels.length} levels`}
        >
          <defs>
            <marker
              id="lab-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" className="lab-arrow-head" />
            </marker>
          </defs>

          {layout.edges.map((edge) => {
            const done = stateOf(model, edge.from)?.state === "completed";
            const hot = hotEdges.has(edge.id);
            const inCycle = cycle.length > 0 && cycle.includes(edge.from) && cycle.includes(edge.to);
            return (
              <path
                key={edge.id}
                className="lab-edge"
                data-done={done ? "true" : "false"}
                data-hot={hot ? "true" : "false"}
                data-cycle={inCycle ? "true" : "false"}
                d={edge.path}
                markerEnd="url(#lab-arrow)"
              />
            );
          })}

          {layout.nodes.map((id) => {
            const task = plan.byId.get(id);
            const position = layout.positions.get(id);
            const record = stateOf(model, id);
            const state = record?.state || "planned";
            const attempt = record?.attempt ?? null;
            const duration = record?.durationMs ?? null;
            const isSelected = id === selected;
            const showAttempt = attempt !== null && attempt > 1;
            return (
              <g
                key={id}
                className="lab-node"
                transform={`translate(${position.x} ${position.y})`}
                data-state={state}
                data-selected={isSelected ? "true" : "false"}
                data-cycle={cycle.includes(id) ? "true" : "false"}
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                aria-label={`${task.tool}, task ${id}, ${STATE_LABEL[state] || state}`}
                onClick={() => onSelect?.(id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect?.(id);
                  }
                }}
              >
                <rect width="216" height="76" rx="10" className="lab-node-box" />
                <text x="12" y="21" className="lab-node-tool">
                  {shorten(task.tool, 26)}
                </text>
                <text x="12" y="38" className="lab-node-id">
                  {shorten(id, 24)}
                </text>
                <circle cx="16" cy="57" r="4" className="lab-node-dot" />
                <text x="26" y="61" className="lab-node-state">
                  {STATE_LABEL[state] || state}
                </text>
                {duration !== null ? (
                  <text x="204" y="61" textAnchor="end" className="lab-node-meta">
                    {formatDuration(duration)}
                  </text>
                ) : showAttempt ? (
                  <text x="204" y="61" textAnchor="end" className="lab-node-meta">
                    attempt {attempt}
                    {model?.workers?.maxAttempts ? `/${model.workers.maxAttempts}` : ""}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      {selectedTask && selectedState ? (
        <div className="lab-task-facts" aria-live="polite">
          <h3>Selected task</h3>
          <dl>
            <div>
              <dt>Task</dt>
              <dd>
                <code>{selectedTask.id}</code>
              </dd>
            </div>
            <div>
              <dt>Tool</dt>
              <dd>
                <code>{selectedTask.tool}</code>
              </dd>
            </div>
            <div>
              <dt>State</dt>
              <dd>{STATE_LABEL[selectedState.state] || selectedState.state}</dd>
            </div>
            <div>
              <dt>Dependencies</dt>
              <dd>
                {selectedTask.dependsOn.length > 0
                  ? selectedTask.dependsOn.join(", ")
                  : "none recorded"}
              </dd>
            </div>
            <div>
              <dt>Attempt</dt>
              <dd>
                {selectedState.attempt === null
                  ? "not recorded"
                  : `${selectedState.attempt}${
                      model?.workers?.maxAttempts ? ` of ${model.workers.maxAttempts}` : ""
                    }`}
              </dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>
                {selectedState.durationMs === null
                  ? "not recorded"
                  : formatDuration(selectedState.durationMs)}
              </dd>
            </div>
            <div>
              <dt>Ready reason</dt>
              <dd>
                {selectedState.readyReason
                  ? selectedState.readyReason.replace(/_/g, " ")
                  : "not recorded"}
              </dd>
            </div>
            <div>
              <dt>Remaining prerequisites</dt>
              <dd>
                {selectedState.remaining === null
                  ? "not recorded"
                  : String(selectedState.remaining)}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}

      <div className="lab-legend" aria-label="Graph legend">
        <span className="lab-legend-group">
          {TASK_STATES.map((state) => (
            <span className="lab-legend-item" key={state} data-state={state}>
              <span className="lab-legend-dot" aria-hidden="true" />
              {STATE_LABEL[state]}
            </span>
          ))}
        </span>
        <span className="lab-legend-group">
          <span className="lab-legend-item" data-edge="done">
            <span className="lab-legend-line" aria-hidden="true" />
            prerequisite completed
          </span>
          <span className="lab-legend-item" data-edge="hot">
            <span className="lab-legend-line" aria-hidden="true" />
            child ready
          </span>
        </span>
      </div>

      {plan.levelsComputed ? (
        <p className="lab-note">
          Levels computed from the dependencies recorded in the plan; the log carries no validated
          levels.
        </p>
      ) : null}
    </div>
  );
}
