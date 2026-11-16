import { formatDuration } from "../../lib/format.js";

function policyLabel(policy) {
  if (policy === "fifo") return "FIFO";
  if (policy === "priority") return "Priority";
  return "Policy not recorded";
}

function QueueItem({ item, index, total, showPriority }) {
  const position = index === 0 ? "head" : index === total - 1 ? "tail" : "body";
  return (
    <li className="lab-queue-item" data-position={position}>
      <span className="lab-queue-slot num">{index + 1}</span>
      <code>{item.taskId}</code>
      {showPriority && item.priority !== null ? (
        <span className="lab-queue-meta num">
          priority {item.priority}
          {item.sequence !== null ? ` · seq ${item.sequence}` : ""}
        </span>
      ) : null}
    </li>
  );
}

/** The ready queue, worker slots and concurrency meter (design §4.3). */
export default function QueuePanel({ model }) {
  const queue = model.queue;
  const capacity = model.workers.concurrency;
  const occupied = model.tasks.filter(
    (task) => task.state === "dispatched" || task.state === "running",
  );
  const slots = capacity === null ? Math.max(occupied.length, 1) : Math.max(capacity, occupied.length);
  const showPriority = queue.priorityRecorded;

  return (
    <div className="lab-queue">
      <section className="lab-subpanel" aria-labelledby="lab-queue-title">
        <div className="lab-subpanel-head">
          <h3 id="lab-queue-title">Ready queue</h3>
          <span className="chip chip--muted">{policyLabel(queue.policy)}</span>
          <span className="spacer" />
          <span className="num">
            {queue.items.length} item{queue.items.length === 1 ? "" : "s"} recorded
          </span>
        </div>

        {queue.items.length > 0 ? (
          <ol className="lab-queue-list" aria-label="Recorded ready queue">
            {queue.items.map((item, index) => (
              <QueueItem
                key={`${item.taskId}-${index}`}
                item={item}
                index={index}
                total={queue.items.length}
                showPriority={showPriority}
              />
            ))}
          </ol>
        ) : (
          <div className="lab-empty lab-empty--inline">
            <p>Queue empty at the playhead.</p>
            {queue.lastNonEmpty ? (
              <>
                <p className="lab-note">
                  Last recorded non-empty snapshot at event {queue.lastNonEmpty.seq}
                  {queue.lastNonEmpty.operation
                    ? ` (${queue.lastNonEmpty.operation.replace(/_/g, " ")})`
                    : ""}
                  :
                </p>
                <ol className="lab-queue-list" aria-label="Last recorded non-empty queue">
                  {queue.lastNonEmpty.items.map((item, index) => (
                    <QueueItem
                      key={`${item.taskId}-${index}`}
                      item={item}
                      index={index}
                      total={queue.lastNonEmpty.items.length}
                      showPriority={showPriority}
                    />
                  ))}
                </ol>
              </>
            ) : null}
          </div>
        )}

        {queue.priorityRecorded ? (
          <>
            <div className="lab-heap" aria-hidden="true">
              {queue.items.slice(0, 7).map((item, index) => (
                <span className="lab-heap-node" key={`${item.taskId}-${index}`}>
                  {item.priority}
                </span>
              ))}
            </div>
            <p className="lab-note">
              Heap array in recorded order: the highest priority leaves first; equal priorities
              leave in insertion order.
            </p>
          </>
        ) : queue.recorded ? (
          <p className="lab-note">
            {queue.policy === "fifo"
              ? "Priority not recorded in FIFO mode: the queue snapshot carries task ids only."
              : "Priority not recorded in this snapshot."}
          </p>
        ) : null}
      </section>

      <section className="lab-subpanel" aria-labelledby="lab-workers-title">
        <div className="lab-subpanel-head">
          <h3 id="lab-workers-title">Worker pool</h3>
          <span className="chip chip--muted">
            {capacity === null ? "capacity not recorded" : `${capacity} slots`}
          </span>
          <span className="spacer" />
          <span className="num">
            {model.concurrency.active} / {capacity === null ? "?" : capacity} active
          </span>
        </div>

        <ol className="lab-slots" aria-label="Worker slots, filled in display order">
          {Array.from({ length: slots }, (_, index) => {
            const task = occupied[index] || null;
            return (
              <li
                className="lab-slot"
                key={slotKey(index)}
                data-filled={task ? "true" : "false"}
                data-state={task ? task.state : "idle"}
              >
                <span className="lab-slot-name num">slot {index + 1}</span>
                {task ? (
                  <>
                    <code>{task.id}</code>
                    <span className="lab-slot-state">{task.state}</span>
                  </>
                ) : (
                  <span className="lab-slot-idle">idle</span>
                )}
              </li>
            );
          })}
        </ol>

        <p className="lab-note">
          Slot order is display order — the runtime records which tasks run concurrently, not which
          worker id.
        </p>
        {occupied.length > slots ? (
          <p className="lab-warn">
            {occupied.length} tasks are in flight but only {slots} slots are accounted for; the
            recorded snapshot is shown uncollapsed.
          </p>
        ) : null}

        {model.concurrency.peak.length > 0 ? (
          <p className="lab-note">
            Peak in-flight per provider, from the run summary:{" "}
            {model.concurrency.peak
              .map(({ provider, count }) => `${provider} ${count}`)
              .join(" · ")}
          </p>
        ) : null}
      </section>

      <section className="lab-subpanel" aria-labelledby="lab-throughput-title">
        <div className="lab-subpanel-head">
          <h3 id="lab-throughput-title">Concurrency meter</h3>
        </div>
        <dl className="lab-stats">
          <div>
            <dt>Active</dt>
            <dd>{model.concurrency.active}</dd>
          </div>
          <div>
            <dt>Capacity</dt>
            <dd>{capacity === null ? "not recorded" : capacity}</dd>
          </div>
          <div>
            <dt>Completed</dt>
            <dd>{model.counts.completed}</dd>
          </div>
          <div>
            <dt>Cancelled</dt>
            <dd>{model.counts.cancelled}</dd>
          </div>
          <div>
            <dt>Failed / blocked</dt>
            <dd>{model.counts.failed}</dd>
          </div>
          <div>
            <dt>Longest recorded task</dt>
            <dd>{longestTask(model.tasks)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function slotKey(index) {
  return `slot-${index}`;
}

function longestTask(tasks) {
  let winner = null;
  for (const task of tasks) {
    if (task.durationMs === null) continue;
    if (!winner || task.durationMs > winner.durationMs) winner = task;
  }
  return winner ? `${winner.id} · ${formatDuration(winner.durationMs)}` : "duration not recorded";
}
