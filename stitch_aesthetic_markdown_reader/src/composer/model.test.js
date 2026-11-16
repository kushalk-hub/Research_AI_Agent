import { describe, expect, it } from "vitest";
import {
  LIMITS,
  buildRequest,
  defaultMode,
  fieldDefault,
  liveBlocker,
  mapServerFields,
  validate,
} from "./model.js";

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

const KEYLESS = {
  ...LIVE,
  gemini_key_configured: false,
  capabilities: { ...LIVE.capabilities, gemini: false, rla_live: false },
};

describe("live availability", () => {
  it("says why live cannot run, naming the actual cause", () => {
    expect(liveBlocker(LIVE)).toBe("");
    expect(liveBlocker(NO_LIVE)).toMatch(/ollama planner.*gemini\/gemini-2\.5-flash/i);
    expect(liveBlocker(KEYLESS)).toMatch(/gemini_api_key/i);
  });

  it("starts on the mode that can actually run", () => {
    expect(defaultMode(LIVE)).toBe("live");
    expect(defaultMode(NO_LIVE)).toBe("demo");
    expect(defaultMode(KEYLESS)).toBe("demo");
    // Before /api/config arrives nothing is known, so the safe default is demo.
    expect(defaultMode(null)).toBe("demo");
  });

  it("falls back to the planner rule when an older server omits capabilities", () => {
    const { capabilities, ...legacy } = LIVE;
    expect(capabilities).toBeTruthy();
    expect(liveBlocker(legacy)).toBe("");
  });
});

describe("validation", () => {
  it("blocks a question shorter than the server minimum", () => {
    const { errors, ok } = validate({ question: "ab", mode: "demo" }, LIVE);
    expect(ok).toBe(false);
    expect(errors.question).toMatch(/at least 3/i);
  });

  it("accepts an empty topic but rejects a one-character one", () => {
    expect(validate({ question: "What works?", mode: "demo", topic: "" }, LIVE).ok).toBe(true);
    const { errors } = validate({ question: "What works?", mode: "demo", topic: "x" }, LIVE);
    expect(errors.topic).toMatch(/at least 3/i);
  });

  it("rejects advanced values outside the NewRun bounds", () => {
    const { errors } = validate(
      {
        question: "What works?",
        mode: "demo",
        overrides: { paper_limit: 999, llm_request_budget: 0, concurrency: 9, source_limit: 1 },
      },
      LIVE,
    );
    expect(errors.paper_limit).toBe(`Must be at most ${LIMITS.paper_limit_max}.`);
    expect(errors.llm_request_budget).toMatch(/at least 1/i);
    expect(errors.concurrency).toMatch(/at most 8/i);
    expect(errors.source_limit).toMatch(/at least 2/i);
  });

  it("requires an explicit opt-in above the configured daily cap, and names it", () => {
    const over = { llm_request_budget: 40 };
    const blocked = validate({ question: "What works?", mode: "demo", overrides: over }, LIVE);
    expect(blocked.ok).toBe(false);
    expect(blocked.errors.llm_request_budget).toMatch(/cap of 15/i);

    const allowed = validate(
      { question: "What works?", mode: "demo", overrides: over, allowBudgetOverride: true },
      LIVE,
    );
    expect(allowed.ok).toBe(true);
  });

  it("blocks live mode when the runtime cannot run it", () => {
    const { errors } = validate({ question: "What works?", mode: "live" }, NO_LIVE);
    expect(errors.mode).toMatch(/ollama planner/i);
  });

  it("reads bounds from /api/config when the server sends them", () => {
    const narrowed = { ...LIVE, limits: { ...LIMITS, paper_limit_max: 8 } };
    const { errors } = validate(
      { question: "What works?", mode: "demo", overrides: { paper_limit: 9 } },
      narrowed,
    );
    expect(errors.paper_limit).toMatch(/at most 8/i);
  });
});

describe("request building", () => {
  it("omits every untouched advanced field so the runtime default applies unchanged", () => {
    const body = buildRequest({ question: " How do schedulers work? ", mode: "demo" }, LIVE);
    expect(body).toEqual({
      engine: "fods",
      mode: "simulate",
      planner: "fixture",
      topic: "How do schedulers work?",
      question: "How do schedulers work?",
    });
  });

  it("sends only the fields the user edited", () => {
    const body = buildRequest(
      {
        question: "How do schedulers work?",
        mode: "live",
        overrides: { paper_limit: "7", concurrency: "", llm_request_budget: null },
      },
      LIVE,
    );
    expect(body.paper_limit).toBe(7);
    expect(body).not.toHaveProperty("concurrency");
    expect(body).not.toHaveProperty("llm_request_budget");
    expect(body.engine).toBe("rla");
    expect(body.mode).toBe("live");
    expect(body.planner).toBe("auto");
  });

  it("uses the typed topic label and falls back to the question", () => {
    expect(buildRequest({ question: "Explain X", mode: "demo", topic: "My topic" }, LIVE).topic).toBe(
      "My topic",
    );
    expect(buildRequest({ question: "Explain X", mode: "demo" }, LIVE).topic).toBe("Explain X");
  });

  it("sends the override flag only when it is needed", () => {
    const raised = buildRequest(
      {
        question: "How do schedulers work?",
        mode: "demo",
        overrides: { llm_request_budget: 40 },
        allowBudgetOverride: true,
      },
      LIVE,
    );
    expect(raised.llm_request_budget).toBe(40);
    expect(raised.allow_budget_override).toBe(true);

    const atCap = buildRequest(
      { question: "How do schedulers work?", mode: "demo", overrides: { llm_request_budget: 15 } },
      LIVE,
    );
    expect(atCap.llm_request_budget).toBe(15);
    expect(atCap).not.toHaveProperty("allow_budget_override");
  });
});

describe("defaults shown in the menu", () => {
  it("reports the value the runtime will use when the field is omitted", () => {
    expect(fieldDefault(LIVE, "llm_request_budget")).toEqual({
      value: 15,
      source: "from /api/config",
    });
    expect(fieldDefault(LIVE, "paper_limit")).toEqual({ value: 20, source: "runtime default" });
    expect(fieldDefault(LIVE, "provider_wait_seconds")).toEqual({
      value: 300,
      source: "runtime default",
    });
    expect(fieldDefault(LIVE, "concurrency")).toEqual({ value: 3, source: "runtime default" });
    expect(fieldDefault(LIVE, "source_limit")).toEqual({ value: 3, source: "runtime default" });
  });
});

describe("server field mapping", () => {
  it("maps pydantic loc tuples to field names and keeps the rest as a summary", () => {
    const mapped = mapServerFields([
      { loc: ["body", "llm_request_budget"], msg: "above the configured daily cap of 15" },
      { loc: ["body", "topic"], msg: "too short" },
      { msg: "invalid run request" },
    ]);
    expect(mapped.byField).toEqual({
      llm_request_budget: "above the configured daily cap of 15",
      topic: "too short",
    });
    expect(mapped.summary).toEqual(["invalid run request"]);
  });
});
