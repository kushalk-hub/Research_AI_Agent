import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client.js";
import { StoreProvider } from "../store/store.jsx";
import App from "./App.jsx";

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.closed = false;
    FakeEventSource.instances.push(this);
  }

  emit(event) {
    this.onmessage?.({ data: JSON.stringify({ run_kind: "simulate", event }) });
  }

  close() {
    this.closed = true;
  }

  static last() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }
}

const handle = {
  run_id: "0123456789ab",
  engine: "fods",
  run_kind: "simulate",
  source_run_id: null,
  topic: "Deterministic demo",
  status: "starting",
  event_count: 0,
  error: "",
  output_path: "data/fods/briefs/0123456789ab.md",
  events_url: "/api/runs/0123456789ab/events",
};

function renderApp() {
  return render(
    <StoreProvider>
      <App />
    </StoreProvider>,
  );
}

function typeQuestion(value) {
  fireEvent.change(screen.getByLabelText(/research question/i), { target: { value } });
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.spyOn(api, "config").mockResolvedValue({
    llm_request_budget: 15,
    gemini_key_configured: true,
    modes: ["live", "simulate", "replay"],
  });
  vi.spyOn(api, "history").mockResolvedValue({ runs: [] });
  vi.spyOn(api, "contexts").mockResolvedValue({ contexts: [] });
  vi.spyOn(api, "createRun").mockResolvedValue(handle);
  vi.spyOn(api, "replayRun").mockResolvedValue({ ...handle, run_kind: "replay" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("boots from the local runtime and says so", async () => {
    renderApp();
    expect(await screen.findByText("Local runtime ready")).toBeTruthy();
    expect(api.config).toHaveBeenCalledTimes(1);
  });

  it("reports an unreachable runtime instead of showing an empty workspace as ready", async () => {
    api.config.mockRejectedValue(new Error("boom"));
    renderApp();
    expect((await screen.findAllByText("Runtime unreachable")).length).toBeGreaterThanOrEqual(1);
  });

  it("starts the deterministic demo with the fixture planner and no network providers", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /run the deterministic demo/i }));

    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(api.createRun.mock.calls[0][0]).toMatchObject({
      engine: "fods",
      mode: "simulate",
      planner: "fixture",
      topic: "Deterministic demo",
    });

    await waitFor(() => expect(FakeEventSource.last().onmessage).toBeTypeOf("function"));
    expect(FakeEventSource.last().url).toBe("/api/runs/0123456789ab/events");
  });

  it("shows recorded progress, then the terminal status the runtime actually reported", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /run the deterministic demo/i }));
    await waitFor(() => expect(FakeEventSource.last().onmessage).toBeTypeOf("function"));

    const source = FakeEventSource.last();
    source.emit({ seq: 1, kind: "run_started", payload: { phase: "plan" } });
    source.emit({ seq: 2, kind: "task_started", message: "search_alpha started", payload: {} });

    const turn = await screen.findByRole("article");
    expect(await within(turn).findByText(/search_alpha started/)).toBeTruthy();

    source.emit({
      seq: 3,
      kind: "run_finished",
      payload: {
        succeeded: false,
        termination_reason: "completed_with_partial_sources",
        unavailable_sources: ["arxiv"],
      },
    });

    expect(await within(turn).findByText("Partial")).toBeTruthy();
    expect(within(turn).getByText(/1 source unavailable \(arxiv\)/)).toBeTruthy();
    expect(source.closed).toBe(true);
  });

  it("submits a typed question through the live literature pipeline", async () => {
    renderApp();
    await screen.findByLabelText(/research question/i);
    typeQuestion("How do graph stores age out nodes?");
    fireEvent.click(screen.getByRole("button", { name: /start the run/i }));

    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(api.createRun.mock.calls[0][0]).toMatchObject({
      engine: "rla",
      mode: "live",
      question: "How do graph stores age out nodes?",
      topic: "How do graph stores age out nodes?",
    });
  });

  it("surfaces a validation failure next to the composer and keeps the text", async () => {
    api.createRun.mockRejectedValue(
      new ApiError("invalid run request", {
        status: 400,
        code: "validation",
        fields: [{ loc: ["body", "topic"], msg: "String should have at least 3 characters" }],
      }),
    );
    renderApp();
    const box = await screen.findByLabelText(/research question/i);
    typeQuestion("Why?");
    fireEvent.click(screen.getByRole("button", { name: /start the run/i }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/invalid run request/)).toBeTruthy();
    expect(within(alert).getByText(/topic: String should have at least 3 characters/)).toBeTruthy();
    expect(box.value).toBe("Why?");
  });

  it("New investigation clears the open run but keeps it in recents", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /run the deterministic demo/i }));
    await waitFor(() => expect(FakeEventSource.last().onmessage).toBeTypeOf("function"));
    FakeEventSource.last().emit({ seq: 1, kind: "run_started", payload: {} });

    await screen.findByRole("article");
    fireEvent.click(screen.getByRole("button", { name: /new investigation/i }));

    expect(await screen.findByText(/what should we investigate/i)).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.getByTitle(/Deterministic demo/)).toBeTruthy();
  });

  it("cycles the theme on the document element, never through an inline style", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /system theme/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
    fireEvent.click(screen.getByRole("button", { name: /light theme/i }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: /dark theme/i }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("ignores the N shortcut while typing or when a modifier is held", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /run the deterministic demo/i }));
    await waitFor(() => expect(FakeEventSource.last().onmessage).toBeTypeOf("function"));
    FakeEventSource.last().emit({ seq: 1, kind: "run_started", payload: {} });
    await screen.findByRole("article");

    const box = screen.getByLabelText(/research question/i);
    box.focus();
    fireEvent.keyDown(box, { key: "n" });
    expect(screen.queryByRole("article")).toBeTruthy();

    for (const modifier of ["ctrlKey", "metaKey", "altKey"]) {
      fireEvent.keyDown(document.body, { key: "n", [modifier]: true });
      expect(screen.queryByRole("article")).toBeTruthy();
    }

    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    Object.defineProperty(editable, "isContentEditable", { value: true });
    document.body.appendChild(editable);
    fireEvent.keyDown(editable, { key: "n" });
    expect(screen.queryByRole("article")).toBeTruthy();
    editable.remove();

    fireEvent.keyDown(document.body, { key: "n" });
    expect(await screen.findByText(/what should we investigate/i)).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
  });
});
