import { beforeEach, describe, expect, it, vi } from "vitest";
import { openRunStream } from "./sse.js";

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.closed = false;
    FakeEventSource.instances.push(this);
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  emit(event) {
    this.onmessage?.({ data: JSON.stringify({ run_kind: "simulate", event }) });
  }

  emitRaw(data) {
    this.onmessage?.({ data });
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  static last() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 40));

describe("openRunStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });

  it("batches a burst into a single render", async () => {
    const batches = [];
    const stream = openRunStream({
      runId: "abcdefabcdef",
      onBatch: (events) => batches.push(events),
      EventSourceImpl: FakeEventSource,
    });
    const source = FakeEventSource.last();
    source.emit({ seq: 1, kind: "run_started", payload: {} });
    source.emit({ seq: 2, kind: "task_started", payload: {} });
    await flush();

    expect(batches).toHaveLength(1);
    expect(batches[0].map((event) => event.seq)).toEqual([1, 2]);
    expect(stream.cursor()).toBe(2);
    stream.close();
  });

  it("closes on the terminal event and applies it before closing", () => {
    const batches = [];
    const terminal = vi.fn();
    const stream = openRunStream({
      runId: "abcdefabcdef",
      onBatch: (events) => batches.push(events),
      onTerminal: terminal,
      EventSourceImpl: FakeEventSource,
    });
    const source = FakeEventSource.last();
    source.emit({ seq: 1, kind: "task_started", payload: {} });
    source.emit({
      seq: 2,
      kind: "run_finished",
      payload: { succeeded: true, termination_reason: "completed" },
    });

    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(2);
    expect(source.closed).toBe(true);
    expect(terminal).toHaveBeenCalledTimes(1);
    stream.close();
    expect(terminal).toHaveBeenCalledTimes(1);
  });

  it("resumes with ?after= when a cursor is supplied", () => {
    openRunStream({
      runId: "abcdefabcdef",
      after: 41,
      onBatch: () => {},
      EventSourceImpl: FakeEventSource,
    });
    expect(FakeEventSource.last().url).toBe("/api/runs/abcdefabcdef/events?after=41");
  });

  it("ignores malformed frames instead of crashing the stream", async () => {
    const batches = [];
    openRunStream({
      runId: "abcdefabcdef",
      onBatch: (events) => batches.push(events),
      EventSourceImpl: FakeEventSource,
    });
    const source = FakeEventSource.last();
    source.emitRaw("{not json");
    source.emitRaw(JSON.stringify({ event: { kind: 3 } }));
    await flush();
    expect(batches).toHaveLength(0);
  });

  it("reports an unsupported browser rather than pretending to stream", () => {
    const states = [];
    const stream = openRunStream({
      runId: "abcdefabcdef",
      onBatch: () => {},
      onState: (state) => states.push(state),
      EventSourceImpl: null,
    });
    expect(states).toEqual(["unsupported"]);
    expect(() => stream.close()).not.toThrow();
  });
});
