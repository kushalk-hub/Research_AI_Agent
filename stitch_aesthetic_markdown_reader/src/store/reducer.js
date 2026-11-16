import { finishReason, isTerminal, statusFromFinish } from "../lib/events.js";

export const MAX_EVENTS_PER_RUN = 5000;

export const initialState = {
  /* server facts */
  config: null,
  history: [],
  contexts: [],
  connection: "connecting", // connecting | ready | down

  /* runs known to this tab, keyed by run id */
  runs: {},
  order: [], // opened runs, newest first
  activeRunId: null,

  /* view state */
  page: "research",
  theme: "system", // system | light | dark
  error: null, // { message, code, fields }

  /* composer state (per session, survives navigation) */
  composer: {
    mode: null, // null = follow live availability; "live" | "demo"
    topic: "", // "" = derive from the question
    menuOpen: false,
    advancedOpen: false,
    overrides: {
      paper_limit: null,
      provider_wait_seconds: null,
      llm_request_budget: null,
      concurrency: null,
      source_limit: null,
    },
    allowBudgetOverride: false,
  },
};

function upsertOrder(order, runId) {
  if (order.includes(runId)) return order;
  return [runId, ...order];
}

export function reducer(state, action) {
  switch (action.type) {
    case "bootstrap/succeeded": {
      const { config, history, contexts } = action;
      return {
        ...state,
        config,
        history: history || [],
        contexts: contexts || [],
        connection: "ready",
        error: null,
      };
    }

    case "bootstrap/failed": {
      return {
        ...state,
        connection: "down",
        error: { message: action.message || "Cannot reach the local runtime.", code: "network", fields: [] },
      };
    }

    case "history/loaded": {
      return { ...state, history: action.history || [] };
    }

    case "run/opened": {
      const { handle, request } = action;
      const id = handle?.run_id;
      if (!id) return state;
      const previous = state.runs[id];
      const run = {
        id,
        sourceRunId: handle.source_run_id || "",
        engine: handle.engine || request?.engine || "fods",
        kind: handle.run_kind || request?.mode || "live",
        mode: request?.mode || handle.run_kind || "live",
        planner: request?.planner || "",
        topic: handle.topic || request?.topic || "",
        question: request?.question || "",
        status: handle.status || "starting",
        statusReason: "",
        stream: "connecting",
        openedAt: previous?.openedAt || Date.now(),
        endedAt: null,
        events: previous?.events || [],
      };
      return {
        ...state,
        runs: { ...state.runs, [id]: run },
        order: upsertOrder(state.order, id),
        activeRunId: id,
        error: null,
      };
    }

    case "run/events": {
      const run = state.runs[action.runId];
      if (!run) return state;
      return {
        ...state,
        runs: { ...state.runs, [action.runId]: applyEvents(run, action.events) },
      };
    }

    case "run/stream": {
      const run = state.runs[action.runId];
      if (!run) return state;
      return {
        ...state,
        runs: { ...state.runs, [action.runId]: { ...run, stream: action.stream } },
      };
    }

    case "run/selected": {
      if (!action.runId) return { ...state, activeRunId: null };
      if (!state.runs[action.runId]) return state;
      return { ...state, activeRunId: action.runId };
    }

    case "ui/page":
      return { ...state, page: action.page };

    case "ui/theme":
      return { ...state, theme: action.theme };

    case "composer/mode":
      return {
        ...state,
        composer: { ...state.composer, mode: action.mode, menuOpen: false },
      };

    case "composer/topic":
      return {
        ...state,
        composer: { ...state.composer, topic: action.topic },
      };

    case "composer/menu":
      return {
        ...state,
        composer: {
          ...state.composer,
          menuOpen: typeof action.open === "boolean" ? action.open : !state.composer.menuOpen,
        },
      };

    case "composer/advanced":
      return {
        ...state,
        composer: {
          ...state.composer,
          advancedOpen:
            typeof action.open === "boolean" ? action.open : !state.composer.advancedOpen,
        },
      };

    case "composer/override": {
      const overrides = { ...state.composer.overrides, [action.field]: action.value };
      return { ...state, composer: { ...state.composer, overrides } };
    }

    case "composer/allow-budget-override":
      return {
        ...state,
        composer: { ...state.composer, allowBudgetOverride: Boolean(action.value) },
      };

    case "composer/reset":
      return {
        ...state,
        composer: {
          ...state.composer,
          topic: "",
          advancedOpen: false,
          overrides: {
            paper_limit: null,
            provider_wait_seconds: null,
            llm_request_budget: null,
            concurrency: null,
            source_limit: null,
          },
          allowBudgetOverride: false,
        },
      };

    case "ui/error":
      return {
        ...state,
        error: { message: action.message, code: action.code || "", fields: action.fields || [] },
      };

    case "ui/clear-error":
      return { ...state, error: null };

    case "ui/new-investigation":
      return { ...state, activeRunId: null, error: null, page: "research" };

    default:
      return state;
  }
}

/** Append a batch of events and derive the terminal status, if any. */
export function applyEvents(run, incoming) {
  const events = incoming?.length ? run.events.concat(incoming) : run.events;
  let next = run;

  if (events.length !== run.events.length) {
    next = {
      ...run,
      events:
        events.length > MAX_EVENTS_PER_RUN
          ? events.slice(events.length - MAX_EVENTS_PER_RUN)
          : events,
      status: run.status === "starting" ? "running" : run.status,
    };
  }

  for (const event of incoming || []) {
    if (isTerminal(event)) {
      const payload = event.payload || {};
      next = {
        ...next,
        status: statusFromFinish(payload),
        statusReason: finishReason(payload),
        endedAt: event.timestamp ? Math.round(event.timestamp * 1000) : Date.now(),
        stream: "idle",
      };
    }
  }

  return next;
}
