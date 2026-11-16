function frameKind(frame) {
  const value = String(frame || "");
  const index = value.indexOf(":");
  return index > 0 ? value.slice(0, index) : "frame";
}

function StackFrames({ frames, label }) {
  if (!frames || frames.length === 0) {
    return <p className="lab-empty lab-empty--inline">{label} has no recorded frames.</p>;
  }
  // The recorded array is bottom-to-top; render it top-first, as a stack.
  const topFirst = [...frames].reverse();
  return (
    <ol className="lab-stack-frames" aria-label={`${label} stack, top first`}>
      {topFirst.map((frame, index) => (
        <li
          className="lab-stack-frame"
          key={`${frame}-${index}`}
          data-frame={frameKind(frame)}
          data-top={index === 0 ? "true" : "false"}
        >
          {index === 0 ? <span className="lab-stack-top">TOP</span> : null}
          <code>{frame}</code>
        </li>
      ))}
    </ol>
  );
}

function frameCount(count) {
  return `${count} frame${count === 1 ? "" : "s"}`;
}

/** Per-task task stacks and the run-level stack (design §4.4). */
export default function StackPanel({ model }) {
  const taskStacks = model.tasks
    .map((task) => ({ task, frames: model.stacks.byTask[task.id] }))
    .filter((entry) => Array.isArray(entry.frames) && entry.frames.length > 0);

  return (
    <div className="lab-stacks">
      <section className="lab-subpanel" aria-labelledby="lab-run-stack-title">
        <div className="lab-subpanel-head">
          <h3 id="lab-run-stack-title">Run stack</h3>
          <span className="chip chip--muted">latest recorded frame</span>
          <span className="spacer" />
          <span className="num">{frameCount(model.stacks.latest.length)}</span>
        </div>
        <StackFrames frames={model.stacks.latest} label="The run" />
      </section>

      <section className="lab-subpanel" aria-labelledby="lab-task-stacks-title">
        <div className="lab-subpanel-head">
          <h3 id="lab-task-stacks-title">Task stacks</h3>
          <span className="spacer" />
          <span className="num">
            {taskStacks.length} of {model.tasks.length} tasks recorded frames
          </span>
        </div>

        {taskStacks.length > 0 ? (
          <div className="lab-stack-grid">
            {taskStacks.map(({ task, frames }) => (
              <article className="lab-stack-card" key={task.id}>
                <h4>
                  <code>{task.id}</code>
                  <span className="lab-stack-state" data-state={task.state}>
                    {task.state}
                  </span>
                </h4>
                <StackFrames frames={frames} label={`Task ${task.id}`} />
              </article>
            ))}
          </div>
        ) : (
          <p className="lab-empty lab-empty--inline">No stack frames have been recorded yet.</p>
        )}

        <p className="lab-note">
          The <code>stack</code> array carried by each recorded event is the only source here; frames
          are not replayed from push/pop counts.
        </p>
      </section>
    </div>
  );
}
