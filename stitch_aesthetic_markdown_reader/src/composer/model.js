/** Composer rules, in one place and free of React.
 *
 *  Two invariants drive this file:
 *  - The server is the only authority on bounds. `LIMITS` is a *fallback* for
 *    the first paint and for tests; at runtime the bounds come from
 *    `/api/config.limits`, which mirrors `webapp.NewRun`.
 *  - A field the user did not touch is **omitted** from the request. The
 *    runtime then applies its own default, so the UI can never silently raise a
 *    cap above the operator's configuration (A-06).
 */

import { shorten } from "../lib/format.js";

/** Mirrors `fods.webapp.NewRun`. `tests/test_fods_composer_bounds.py` asserts
 *  this table against the pydantic model, so drift fails the Python gate. */
export const LIMITS = Object.freeze({
  topic_min: 3,
  topic_max: 300,
  question_min: 3,
  question_max: 1000,
  paper_limit_min: 2,
  paper_limit_max: 20,
  provider_wait_seconds_min: 0,
  provider_wait_seconds_max: 3600,
  llm_request_budget_min: 1,
  llm_request_budget_max: 1000,
  concurrency_min: 1,
  concurrency_max: 8,
  source_limit_min: 2,
  source_limit_max: 5,
  delay_ms_min: 0,
  delay_ms_max: 5000,
});

/** Advanced fields the composer can override, in display order. */
export const ADVANCED_FIELDS = Object.freeze([
  {
    name: "paper_limit",
    label: "Papers to keep",
    hint: "Upper bound on retained papers.",
    integer: true,
  },
  {
    name: "provider_wait_seconds",
    label: "Provider wait",
    hint: "Longest automatic wait for a rate-limited source, in seconds.",
    integer: false,
    unit: "s",
  },
  {
    name: "llm_request_budget",
    label: "Model requests for this run",
    hint: "Local per-run cap. Never above the operator's daily budget without an override.",
    integer: true,
  },
  {
    name: "concurrency",
    label: "Concurrent source tasks",
    hint: "How many sources the scheduler queries at once.",
    integer: true,
  },
  {
    name: "source_limit",
    label: "Sources per query",
    hint: "Number of enabled sources a single query may use.",
    integer: true,
  },
]);

export function bounds(config) {
  const remote = config?.limits || {};
  const merged = { ...LIMITS };
  for (const [key, value] of Object.entries(remote)) {
    if (typeof value === "number" && Number.isFinite(value)) merged[key] = value;
  }
  return merged;
}

/** The value the runtime will apply when the field is omitted, plus where that
 *  number comes from. Displaying anything else would describe a run that will
 *  not happen.
 *
 *  `llm_request_budget` is the one field whose effective default comes from the
 *  operator's configuration (`/api/config`), because `NewRun` resolves `None`
 *  to `settings.llm_daily_budget`. Everything else is the pydantic default. */
const RUNTIME_DEFAULTS = Object.freeze({
  paper_limit: 20,
  provider_wait_seconds: 300,
  concurrency: 3,
  source_limit: 3,
});

export function fieldDefault(config, name) {
  if (name === "llm_request_budget") {
    const configured = Number(config?.llm_request_budget);
    if (Number.isFinite(configured) && configured > 0) {
      return { value: configured, source: "from /api/config" };
    }
    return { value: null, source: "runtime default" };
  }
  if (name === "paper_limit" && Number(config?.paper_limit_max)) {
    return { value: Number(config.paper_limit_max), source: "runtime default" };
  }
  if (name in RUNTIME_DEFAULTS) {
    return { value: RUNTIME_DEFAULTS[name], source: "runtime default" };
  }
  return { value: null, source: "runtime default" };
}

/** Whether live research can actually run here, and why not.
 *
 *  The backend computes `capabilities.rla_live` with the same rule the run
 *  endpoint enforces, so this function reads that fact first and only falls
 *  back to composing one when an older server omits it. */
export function liveBlocker(config) {
  if (!config) return "Waiting for the local runtime.";
  const capabilities = config.capabilities || {};
  const planner = config.providers?.planner || "";
  const answer = config.providers?.answer || "";
  const keyPresent =
    typeof capabilities.gemini === "boolean"
      ? capabilities.gemini
      : config.gemini_key_configured === true;
  const plannerIsLocal =
    typeof capabilities.ollama_planner === "boolean"
      ? capabilities.ollama_planner
      : planner === "ollama";
  const available =
    typeof capabilities.rla_live === "boolean"
      ? capabilities.rla_live
      : plannerIsLocal && (keyPresent || answer !== "gemini");

  if (available) return "";
  if (!plannerIsLocal) {
    const named = config.models?.planner || planner || "an unknown planner";
    return `Live runs need an Ollama planner. This runtime is configured for ${named}.`;
  }
  if (!keyPresent && answer === "gemini") {
    return "Live runs need GEMINI_API_KEY, and this runtime does not have one.";
  }
  return "The local runtime cannot start live research with its current configuration.";
}

/** The mode the composer should start in: demo whenever live cannot run, so the
 *  first send is never a known-to-fail request. */
export function defaultMode(config) {
  return liveBlocker(config) ? "demo" : "live";
}

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.NaN;
}

function within(errors, name, number, limits, integer) {
  const min = limits[`${name}_min`];
  const max = limits[`${name}_max`];
  if (Number.isNaN(number)) {
    errors[name] = "Enter a number.";
    return;
  }
  if (integer && !Number.isInteger(number)) {
    errors[name] = "Enter a whole number.";
    return;
  }
  if (min !== undefined && number < min) {
    errors[name] = `Must be at least ${min}.`;
    return;
  }
  if (max !== undefined && number > max) {
    errors[name] = `Must be at most ${max}.`;
  }
}

/** Validate everything the user can see. `values` are the raw input strings;
 *  `overrides` holds only the fields the user edited. */
export function validate({ question = "", topic = "", mode = "demo", overrides = {}, allowBudgetOverride = false }, config) {
  const limits = bounds(config);
  const errors = {};
  const trimmed = question.trim();

  if (trimmed.length < limits.question_min) {
    errors.question = `Type at least ${limits.question_min} characters.`;
  } else if (trimmed.length > limits.question_max) {
    errors.question = `Keep the question under ${limits.question_max} characters.`;
  }

  const topicText = topic.trim();
  if (topicText && topicText.length < limits.topic_min) {
    errors.topic = `Type at least ${limits.topic_min} characters, or leave it blank.`;
  } else if (topicText.length > limits.topic_max) {
    errors.topic = `Keep the topic under ${limits.topic_max} characters.`;
  }

  const numbers = {};
  for (const field of ADVANCED_FIELDS) {
    const raw = overrides[field.name];
    if (raw === undefined || raw === null || raw === "") continue;
    const number = asNumber(raw);
    within(errors, field.name, number, limits, field.integer);
    if (!errors[field.name]) numbers[field.name] = number;
  }

  // A-06: the configured cap is a ceiling. Raising it is allowed, but only with
  // an explicit opt-in, and the message must name the cap.
  const configured = Number(config?.llm_request_budget);
  const requested = numbers.llm_request_budget;
  if (
    Number.isFinite(configured) &&
    configured > 0 &&
    requested !== undefined &&
    requested > configured &&
    !allowBudgetOverride
  ) {
    errors.llm_request_budget = `Above the configured cap of ${configured}. Tick the override to raise it for this run.`;
  }

  if (mode === "live") {
    const blocker = liveBlocker(config);
    if (blocker) errors.mode = blocker;
  }

  return { errors, ok: Object.keys(errors).length === 0, limits, numbers };
}

/** Build the POST body. Untouched advanced fields are omitted on purpose: the
 *  runtime's own default then applies unchanged. */
export function buildRequest({ question, topic = "", mode, overrides = {}, allowBudgetOverride = false }, config) {
  const trimmed = question.trim();
  const { numbers } = validate({ question, topic, mode, overrides, allowBudgetOverride }, config);
  const body = {
    engine: mode === "demo" ? "fods" : "rla",
    mode: mode === "demo" ? "simulate" : "live",
    planner: mode === "demo" ? "fixture" : "auto",
    topic: topic.trim() || topicFromQuestion(trimmed),
    question: trimmed,
  };
  for (const field of ADVANCED_FIELDS) {
    if (numbers[field.name] !== undefined) body[field.name] = numbers[field.name];
  }
  const configured = Number(config?.llm_request_budget);
  if (
    allowBudgetOverride &&
    Number.isFinite(configured) &&
    body.llm_request_budget > configured
  ) {
    body.allow_budget_override = true;
  }
  return body;
}

/** Mirrors `useStartRun.topicFromQuestion`; kept here so the menu can show the
 *  label that will be sent before anything is submitted. */
export function topicFromQuestion(question) {
  return shorten(String(question || "").trim(), 80) || "Untitled investigation";
}

/** Turn a server `fields` array into `{ byField, summary }`.
 *
 *  FastAPI/pydantic uses `loc: ["body", "paper_limit"]`; the webapp's own
 *  `BudgetOverrideRequired` uses the same shape. Unknown shapes fall back to the
 *  summary list so nothing is silently dropped. */
export function mapServerFields(fields) {
  const byField = {};
  const summary = [];
  for (const field of Array.isArray(fields) ? fields : []) {
    const message = field?.msg || "invalid value";
    const parts = Array.isArray(field?.loc) ? field.loc.filter((part) => part !== "body") : [];
    const name = parts.join(".");
    if (name) byField[name] = message;
    else summary.push(message);
  }
  return { byField, summary };
}
