/** One SSE connection manager for the whole app.
 *
 *  Only the currently viewed run is streamed. Events are batched so a burst of
 *  114 events (a deterministic demo) causes one render, not 114. The stream is
 *  closed as soon as the terminal event arrives: a finished run must not keep a
 *  socket open, and the UI must never imply live progress after it ended.
 */

const TERMINAL_KIND = "run_finished";

const nextFrame =
  typeof requestAnimationFrame === "function"
    ? (callback) => requestAnimationFrame(callback)
    : (callback) => setTimeout(callback, 16);

const cancelFrame =
  typeof cancelAnimationFrame === "function" ? (id) => cancelAnimationFrame(id) : (id) => clearTimeout(id);

/**
 * @param {object} options
 * @param {string} options.runId
 * @param {number} [options.after] resume cursor (`?after=` is supported by the server)
 * @param {(events: object[]) => void} options.onBatch
 * @param {(state: "live" | "reconnecting" | "error" | "unsupported") => void} [options.onState]
 * @param {() => void} [options.onTerminal]
 * @param {typeof EventSource} [options.EventSourceImpl] injectable for tests
 */
export function openRunStream({
  runId,
  after = 0,
  onBatch,
  onState,
  onTerminal,
  EventSourceImpl = globalThis.EventSource,
}) {
  if (!EventSourceImpl) {
    onState?.("unsupported");
    return { close() {} };
  }

  const query = after > 0 ? `?after=${encodeURIComponent(after)}` : "";
  const source = new EventSourceImpl(`/api/runs/${runId}/events${query}`);

  let buffer = [];
  let frame = 0;
  let closed = false;
  let cursor = after;

  const flush = () => {
    frame = 0;
    if (!buffer.length) return;
    const batch = buffer;
    buffer = [];
    onBatch?.(batch);
  };

  const schedule = () => {
    if (!frame) frame = nextFrame(flush);
  };

  const close = () => {
    if (closed) return;
    closed = true;
    if (frame) cancelFrame(frame);
    frame = 0;
    source.close();
  };

  source.onopen = () => {
    if (!closed) onState?.("live");
  };

  source.onmessage = (message) => {
    if (closed) return;
    let envelope;
    try {
      envelope = JSON.parse(message.data);
    } catch {
      return;
    }
    const event = envelope?.event;
    if (!event || typeof event.kind !== "string") return;
    if (Number.isFinite(Number(event.seq))) cursor = Number(event.seq);
    buffer.push(event);

    if (event.kind === TERMINAL_KIND) {
      // Flush synchronously so the terminal state is applied before closing.
      if (frame) cancelFrame(frame);
      flush();
      close();
      onTerminal?.();
      return;
    }
    schedule();
  };

  source.onerror = () => {
    if (closed) return;
    // 0 = CONNECTING (browser will retry), 2 = CLOSED (gave up).
    onState?.(source.readyState === 2 ? "error" : "reconnecting");
  };

  return {
    close,
    cursor: () => cursor,
  };
}
