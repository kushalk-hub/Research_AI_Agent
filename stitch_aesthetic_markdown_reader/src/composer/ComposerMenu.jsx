import { useEffect, useRef } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import { engineLabel, modeLabel } from "../lib/events.js";
import {
  ADVANCED_FIELDS,
  bounds,
  fieldDefault,
  liveBlocker,
  topicFromQuestion,
} from "./model.js";

function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p className="field-error" id={id} role="alert">
      {message}
    </p>
  );
}

/** The `+` popover. Four sections, in the order the owner specified: execution
 *  mode, agent configuration (read-only), topic label, advanced (collapsed).
 *
 *  It is a non-modal dialog: focus moves in on open, Tab cycles inside, Escape
 *  closes and returns focus to the trigger. No value is invented; every number
 *  shown is either the runtime default or comes from `/api/config`. */
export default function ComposerMenu({
  config,
  mode,
  onMode,
  topic,
  onTopic,
  advancedOpen,
  onAdvanced,
  overrides,
  onOverride,
  allowBudgetOverride,
  onAllowBudgetOverride,
  question,
  errors = {},
  onClose,
}) {
  const panelRef = useRef(null);
  const advancedRef = useRef(null);
  const blocker = liveBlocker(config);
  const limits = bounds(config);
  const derivedTopic = topicFromQuestion(question);
  const configuredBudget = Number(config?.llm_request_budget);
  const budget = Number(overrides.llm_request_budget);
  const needsOverride =
    Number.isFinite(configuredBudget) &&
    configuredBudget > 0 &&
    Number.isFinite(budget) &&
    budget > configuredBudget;

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return undefined;
    const first = panel.querySelector("input:checked") || panel.querySelector("input, button");
    first?.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        panel.querySelectorAll("button, input, select, textarea, [href]"),
      ).filter((element) => !element.disabled);
      if (focusable.length === 0) return;
      const firstItem = focusable[0];
      const lastItem = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }

    panel.addEventListener("keydown", onKeyDown);
    return () => panel.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // The panel scrolls, so expanding Advanced must bring the fields into view;
  // otherwise the click looks like it did nothing (found in the 1280 capture).
  useEffect(() => {
    if (!advancedOpen) return;
    advancedRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [advancedOpen]);

  return (
    <div
      className="composer-popover"
      role="dialog"
      aria-label="Run settings"
      ref={panelRef}
    >
      <div className="popover-head">
        <h2 className="popover-title">Run settings</h2>
        <button
          type="button"
          className="btn btn--ghost btn--icon btn--sm"
          onClick={onClose}
          aria-label="Close run settings"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      <section className="popover-section" aria-labelledby="run-mode-heading">
        <h3 className="popover-heading" id="run-mode-heading">
          Execution mode
        </h3>

        <label className="mode-option">
          <input
            type="radio"
            name="run-mode"
            value="live"
            checked={mode === "live"}
            onChange={() => onMode("live")}
          />
          <span className="mode-copy">
            <strong>{modeLabel("live")}</strong>
            <span>{engineLabel("rla")} against the configured providers.</span>
          </span>
        </label>
        {blocker && (
          <p className="field-error" data-tone="warn">
            {blocker}
          </p>
        )}

        <label className="mode-option">
          <input
            type="radio"
            name="run-mode"
            value="demo"
            checked={mode === "demo"}
            onChange={() => onMode("demo")}
          />
          <span className="mode-copy">
            <strong>{modeLabel("simulate")}</strong>
            <span>{engineLabel("fods")} with the fixture plan. No provider calls.</span>
          </span>
        </label>
        <FieldError id="mode-error" message={errors.mode && errors.mode !== blocker ? errors.mode : ""} />
      </section>

      <section className="popover-section" aria-labelledby="agent-config-heading">
        <h3 className="popover-heading" id="agent-config-heading">
          Agent configuration
          <span className="popover-note">read-only, from /api/config</span>
        </h3>
        {config?.models ? (
          <dl className="config-rows">
            {[
              ["Planner", config.models.planner],
              ["Structured", config.models.structured],
              ["Answer", config.models.answer],
              ["Embedding", config.models.embedding],
            ].map(([label, value]) => (
              <div className="config-row" key={label}>
                <dt>{label}</dt>
                <dd>
                  <code>{value || "not configured"}</code>
                </dd>
              </div>
            ))}
            <div className="config-row">
              <dt>Sources</dt>
              <dd>
                {Array.isArray(config.source_names) && config.source_names.length
                  ? config.source_names.join(", ")
                  : "none enabled"}
              </dd>
            </div>
            <div className="config-row">
              <dt>Daily cap</dt>
              <dd>{Number.isFinite(configuredBudget) ? `${configuredBudget} model requests` : "unknown"}</dd>
            </div>
          </dl>
        ) : (
          <p className="popover-note">Waiting for the local runtime.</p>
        )}
      </section>

      <section className="popover-section" aria-labelledby="topic-heading">
        <h3 className="popover-heading" id="topic-heading">
          Topic label
        </h3>
        <label className="visually-hidden" htmlFor="composer-topic">
          Topic label
        </label>
        <input
          id="composer-topic"
          className="popover-input"
          value={topic}
          placeholder={derivedTopic}
          maxLength={limits.topic_max}
          aria-invalid={Boolean(errors.topic)}
          aria-describedby={errors.topic ? "topic-error" : "topic-hint"}
          onChange={(event) => onTopic(event.target.value)}
        />
        <p className="popover-note" id="topic-hint">
          Sent with the run and shown in recents. Blank uses the question.
        </p>
        <FieldError id="topic-error" message={errors.topic} />
      </section>

      <section className="popover-section" aria-labelledby="advanced-heading">
        <button
          type="button"
          className="accordion-toggle"
          aria-expanded={advancedOpen}
          aria-controls="composer-advanced"
          onClick={() => onAdvanced(!advancedOpen)}
        >
          <ChevronDown
            size={16}
            aria-hidden="true"
            data-open={advancedOpen ? "true" : "false"}
          />
          Advanced
          <span className="popover-note">
            {advancedOpen ? "values sent only when changed" : "collapsed by default"}
          </span>
        </button>

        {advancedOpen && (
          <div className="advanced-grid" id="composer-advanced" ref={advancedRef}>
            {ADVANCED_FIELDS.map((field) => {
              const fallback = fieldDefault(config, field.name);
              const id = `advanced-${field.name}`;
              const message = errors[field.name];
              const display = overrides[field.name] ?? fallback.value ?? "";
              const min = limits[`${field.name}_min`];
              const max = limits[`${field.name}_max`];
              return (
                <div className="field" key={field.name}>
                  <label htmlFor={id}>
                    {field.label}
                    {field.unit ? ` (${field.unit})` : ""}
                  </label>
                  <input
                    id={id}
                    type="number"
                    inputMode={field.integer ? "numeric" : "decimal"}
                    step={field.integer ? 1 : "any"}
                    min={min}
                    max={max}
                    value={display}
                    aria-invalid={Boolean(message)}
                    aria-describedby={message ? `${id}-error` : `${id}-hint`}
                    onChange={(event) => onOverride(field.name, event.target.value)}
                  />
                  <p className="popover-note" id={`${id}-hint`}>
                    {field.hint} Default {fallback.value ?? "?"} · {fallback.source}
                  </p>
                  {field.name === "llm_request_budget" && needsOverride && (
                    <label className="override-check">
                      <input
                        type="checkbox"
                        checked={allowBudgetOverride}
                        onChange={(event) => onAllowBudgetOverride(event.target.checked)}
                      />
                      <span>
                        Allow {budget} requests for this run, above the configured cap of{" "}
                        {configuredBudget}.
                      </span>
                    </label>
                  )}
                  <FieldError id={`${id}-error`} message={message} />
                </div>
              );
            })}
            {Object.values(overrides).some((value) => value !== null && value !== "") && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => {
                  for (const field of ADVANCED_FIELDS) onOverride(field.name, null);
                  onAllowBudgetOverride(false);
                }}
              >
                <Check size={14} aria-hidden="true" /> Use runtime defaults
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
