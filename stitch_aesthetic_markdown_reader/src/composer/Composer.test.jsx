import { createRef } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client.js";
import { StoreProvider } from "../store/store.jsx";
import Composer from "./Composer.jsx";

const NO_LIVE = {
  models: {
    planner: "gemini/gemini-2.5-flash",
    structured: "gemini/gemini-2.5-flash",
    answer: "gemini/gemini-2.5-flash",
    embedding: "gemini/gemini-embedding-001",
  },
  providers: { planner: "gemini", structured: "gemini", answer: "gemini", embedding: "gemini" },
  gemini_key_configured: true,
  gemini_opted_in: false,
  source_names: ["arxiv", "openalex"],
  paper_limit: 20,
  paper_limit_max: 20,
  provider_wait_seconds: 300,
  llm_request_budget: 15,
  source_quorum: 2,
  modes: ["live", "simulate", "replay"],
  capabilities: {
    ollama_planner: false,
    gemini: true,
    gemini_opted_in: false,
    rla_live: false,
  },
};

const LIVE = {
  ...NO_LIVE,
  models: { ...NO_LIVE.models, planner: "ollama/qwen3:4b", structured: "ollama/qwen3:4b" },
  providers: { ...NO_LIVE.providers, planner: "ollama", structured: "ollama" },
  capabilities: { ...NO_LIVE.capabilities, ollama_planner: true, rla_live: true },
};

const handle = {
  run_id: "0123456789ab",
  engine: "fods",
  run_kind: "simulate",
  source_run_id: null,
  topic: "T",
  status: "starting",
  event_count: 0,
  error: "",
  output_path: "",
  events_url: "/api/runs/0123456789ab/events",
};

function renderComposer(config) {
  const inputRef = createRef();
  return render(
    <StoreProvider>
      <Composer config={config} inputRef={inputRef} />
    </StoreProvider>,
  );
}

function type(value) {
  fireEvent.change(screen.getByLabelText(/research question/i), { target: { value } });
}

function sendButton() {
  return screen.getByRole("button", { name: /start the run/i });
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: /run settings/i }));
  return screen.getByRole("dialog", { name: /run settings/i });
}

function openAdvanced() {
  fireEvent.click(screen.getByRole("button", { name: /advanced/i }));
  return screen.getByLabelText(/papers to keep/i);
}

beforeEach(() => {
  vi.spyOn(api, "createRun").mockResolvedValue(handle);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("default mode", () => {
  it("starts on the deterministic demo when live cannot run", async () => {
    renderComposer(NO_LIVE);
    expect(screen.getByText(/deterministic demo · fods scheduler/i)).toBeTruthy();
    expect(screen.queryByText(/live unavailable/i)).toBeNull();

    type("How do schedulers work?");
    expect(sendButton().disabled).toBe(false);
    fireEvent.click(sendButton());

    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    const body = api.createRun.mock.calls[0][0];
    expect(body).toMatchObject({ engine: "fods", mode: "simulate", planner: "fixture" });
    // Untouched advanced fields are omitted, so the runtime default stands.
    expect(body).not.toHaveProperty("llm_request_budget");
    expect(body).not.toHaveProperty("paper_limit");
  });

  it("starts on live when the runtime reports it can run", () => {
    renderComposer(LIVE);
    expect(screen.getByText(/live · literature pipeline/i)).toBeTruthy();
  });
});

describe("the + menu", () => {
  it("opens with focus inside, closes on Escape and returns focus to the trigger", async () => {
    renderComposer(LIVE);
    const trigger = screen.getByRole("button", { name: /run settings/i });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    const dialog = openMenu();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(within(dialog).getByRole("radio", { checked: true }));

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("toggles with Mod+period", async () => {
    renderComposer(LIVE);
    fireEvent.keyDown(document, { key: ".", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: /run settings/i })).toBeTruthy();
    fireEvent.keyDown(document, { key: ".", ctrlKey: true });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the agent configuration as read-only facts from /api/config", () => {
    renderComposer(LIVE);
    const dialog = openMenu();
    // Planner and structured share one model in this fixture, so allow repeats.
    expect(within(dialog).getAllByText("ollama/qwen3:4b").length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getAllByText("gemini/gemini-2.5-flash").length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getByText("arxiv, openalex")).toBeTruthy();
    expect(within(dialog).getByText("15 model requests")).toBeTruthy();
  });

  it("keeps advanced settings collapsed until asked, then shows the defaults and their source", () => {
    renderComposer(LIVE);
    openMenu();
    expect(screen.queryByLabelText(/papers to keep/i)).toBeNull();

    openAdvanced();
    expect(screen.getByLabelText(/papers to keep/i).value).toBe("20");
    expect(screen.getByLabelText(/model requests for this run/i).value).toBe("15");
    expect(screen.getAllByText(/from \/api\/config/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/runtime default/i).length).toBeGreaterThanOrEqual(3);
  });
});

describe("live gating", () => {
  it("disables send in live mode, states the reason and offers the demo", async () => {
    renderComposer(NO_LIVE);
    openMenu();
    fireEvent.click(screen.getByRole("radio", { name: /literature pipeline/i }));

    const note = await screen.findByRole("status");
    expect(note.textContent).toMatch(/live research is unavailable/i);
    expect(note.textContent).toMatch(/ollama planner/i);

    type("How do schedulers work?");
    expect(sendButton().disabled).toBe(true);
    expect(sendButton().title).toMatch(/ollama planner/i);

    fireEvent.click(screen.getByRole("button", { name: /run as deterministic demo/i }));
    await waitFor(() => expect(sendButton().disabled).toBe(false));
    expect(screen.getByText(/deterministic demo · fods scheduler/i)).toBeTruthy();

    fireEvent.click(sendButton());
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(api.createRun.mock.calls[0][0]).toMatchObject({ mode: "simulate", engine: "fods" });
  });
});

describe("validation", () => {
  it("blocks submit on an out-of-range advanced value and does not POST", () => {
    renderComposer(LIVE);
    type("How do schedulers work?");
    openMenu();
    openAdvanced();

    fireEvent.change(screen.getByLabelText(/model requests for this run/i), {
      target: { value: "0" },
    });
    expect(screen.getByText(/must be at least 1/i)).toBeTruthy();

    fireEvent.click(sendButton());
    expect(api.createRun).not.toHaveBeenCalled();
  });

  it("renders a server field error next to the field that caused it", async () => {
    api.createRun.mockRejectedValue(
      new ApiError("invalid run request", {
        status: 400,
        code: "validation",
        fields: [
          {
            loc: ["body", "llm_request_budget"],
            msg: "above the configured daily cap of 15",
            type: "value_error",
          },
        ],
      }),
    );
    renderComposer(LIVE);
    type("How do schedulers work?");
    openMenu();
    openAdvanced();
    fireEvent.change(screen.getByLabelText(/model requests for this run/i), {
      target: { value: "12" },
    });

    fireEvent.click(sendButton());

    await waitFor(() =>
      expect(
        document.getElementById("advanced-llm_request_budget-error")?.textContent,
      ).toMatch(/above the configured daily cap of 15/i),
    );
    expect(screen.getByText(/invalid run request/i)).toBeTruthy();
  });

  it("requires an explicit override above the configured cap, then sends it", async () => {
    renderComposer(LIVE);
    type("How do schedulers work?");
    openMenu();
    openAdvanced();
    const budget = screen.getByLabelText(/model requests for this run/i);
    fireEvent.change(budget, { target: { value: "40" } });

    const inlineError = () => document.getElementById("advanced-llm_request_budget-error");
    expect(inlineError()?.textContent).toMatch(/above the configured cap of 15/i);
    fireEvent.click(sendButton());
    expect(api.createRun).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(inlineError()).toBeNull();

    fireEvent.click(sendButton());
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(api.createRun.mock.calls[0][0]).toMatchObject({
      llm_request_budget: 40,
      allow_budget_override: true,
    });
  });

  it("sends a typed topic label instead of the question", async () => {
    renderComposer(LIVE);
    type("How do schedulers work?");
    openMenu();
    fireEvent.change(screen.getByRole("textbox", { name: /topic label/i }), {
      target: { value: "Scheduler internals" },
    });

    fireEvent.click(sendButton());
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(api.createRun.mock.calls[0][0].topic).toBe("Scheduler internals");
  });
});
