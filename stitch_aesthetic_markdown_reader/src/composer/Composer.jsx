import { ArrowUp, Play, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { engineLabel, modeLabel } from "../lib/events.js";
import { useDispatch, useStore } from "../store/store.jsx";
import ComposerMenu from "./ComposerMenu.jsx";
import {
  buildRequest,
  defaultMode,
  liveBlocker,
  mapServerFields,
  validate,
} from "./model.js";
import { useStartRun } from "./useStartRun.js";

/** The composer and its `+` menu.
 *
 *  Honesty rules enforced here:
 *  - The default mode is the one that can actually run. With no usable live
 *    provider the composer starts on the deterministic demo instead of offering
 *    a send button that is known to fail.
 *  - Choosing Live when it cannot run disables send, states the reason inline,
 *    and offers the demo in one click.
 *  - Advanced values are validated before the request is built; the server's
 *    own field errors are mapped back next to the same input. */
export default function Composer({ config, inputRef }) {
  const state = useStore();
  const dispatch = useDispatch();
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);
  const plusRef = useRef(null);
  const { start, busy, error, clearError } = useStartRun();

  const composer = state.composer;
  const mode = composer.mode ?? defaultMode(config);
  const blocker = liveBlocker(config);
  const liveBlocked = mode === "live" && Boolean(blocker);

  const values = useMemo(
    () => ({
      question: text,
      topic: composer.topic,
      mode,
      overrides: composer.overrides,
      allowBudgetOverride: composer.allowBudgetOverride,
    }),
    [text, composer.topic, mode, composer.overrides, composer.allowBudgetOverride],
  );

  const { errors } = useMemo(() => validate(values, config), [values, config]);

  // Server-side field errors land next to the input that caused them (UI-04).
  // A local error wins, because it describes the value currently in the field.
  // The alert repeats them as `field: message`, so a field inside the closed
  // menu is still reported rather than silently dropped.
  const withServer = useMemo(() => {
    const mapped = mapServerFields(error?.fields);
    const merged = { ...errors };
    for (const [field, message] of Object.entries(mapped.byField)) {
      if (!merged[field]) merged[field] = message;
    }
    const summary = [
      ...Object.entries(mapped.byField).map(([field, message]) => `${field}: ${message}`),
      ...mapped.summary,
    ];
    return { errors: merged, summary };
  }, [errors, error]);

  const canSend = !busy && !liveBlocked && Object.keys(errors).length === 0;

  function setMode(next) {
    dispatch({ type: "composer/mode", mode: next });
  }

  async function submit(event) {
    event?.preventDefault();
    setTouched(true);
    if (!canSend) return;
    const handle = await start(buildRequest(values, config));
    if (handle) {
      setText("");
      setTouched(false);
      dispatch({ type: "composer/reset" });
    }
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(event);
    }
  }

  // Mod+. toggles the menu from anywhere; Escape closes it and returns focus.
  useEffect(() => {
    function onDocumentKeyDown(event) {
      if ((event.ctrlKey || event.metaKey) && event.key === ".") {
        event.preventDefault();
        dispatch({ type: "composer/menu" });
        return;
      }
      if (event.key === "Escape" && composer.menuOpen) {
        event.preventDefault();
        dispatch({ type: "composer/menu", open: false });
        plusRef.current?.focus();
      }
    }
    function onPointerDown(event) {
      if (!composer.menuOpen) return;
      const trigger = plusRef.current;
      if (trigger?.closest(".composer-tools")?.contains(event.target)) return;
      if (event.target.closest?.(".composer-popover")) return;
      dispatch({ type: "composer/menu", open: false });
    }
    document.addEventListener("keydown", onDocumentKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onDocumentKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [composer.menuOpen, dispatch]);

  const sendTitle = liveBlocked
    ? blocker
    : !canSend && busy
      ? "A run is already starting."
      : !canSend && Object.keys(errors).length > 0
        ? "Fix the highlighted settings first."
        : "Start the run (Enter)";

  const questionError = touched && text.trim().length > 0 ? withServer.errors.question : "";

  return (
    <div className="composer-dock">
      <form className="composer" onSubmit={submit} noValidate>
        {error && (
          <div className="composer-error" role="alert">
            <div>
              <strong>{error.message}</strong>
              {withServer.summary.length > 0 && (
                <ul>
                  {withServer.summary.slice(0, 3).map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              )}
            </div>
            <button type="button" className="btn btn--ghost btn--sm" onClick={clearError}>
              Dismiss
            </button>
          </div>
        )}

        {liveBlocked && (
          <div className="composer-note" role="status">
            <span>
              <strong>Live research is unavailable.</strong> {blocker}
            </span>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setMode("demo")}
            >
              <Play size={14} aria-hidden="true" /> Run as deterministic demo
            </button>
          </div>
        )}

        <label className="visually-hidden" htmlFor="composer-input">
          Research question
        </label>
        <div className="composer-box">
          <div className="composer-tools">
            <button
              type="button"
              ref={plusRef}
              className="composer-plus"
              aria-label="Run settings"
              aria-haspopup="dialog"
              aria-expanded={composer.menuOpen}
              aria-controls="composer-run-settings"
              title="Run settings (+ menu)"
              onClick={() => dispatch({ type: "composer/menu" })}
            >
              <Plus size={18} aria-hidden="true" />
            </button>
            {composer.menuOpen && (
              <div id="composer-run-settings">
                <ComposerMenu
                  config={config}
                  mode={mode}
                  onMode={setMode}
                  topic={composer.topic}
                  onTopic={(topic) => dispatch({ type: "composer/topic", topic })}
                  advancedOpen={composer.advancedOpen}
                  onAdvanced={(open) =>
                    dispatch({
                      type: "composer/advanced",
                      open: typeof open === "boolean" ? open : undefined,
                    })
                  }
                  overrides={composer.overrides}
                  onOverride={(field, value) =>
                    dispatch({ type: "composer/override", field, value })
                  }
                  allowBudgetOverride={composer.allowBudgetOverride}
                  onAllowBudgetOverride={(value) =>
                    dispatch({ type: "composer/allow-budget-override", value })
                  }
                  question={text}
                  errors={withServer.errors}
                  onClose={() => {
                    dispatch({ type: "composer/menu", open: false });
                    plusRef.current?.focus();
                  }}
                />
              </div>
            )}
          </div>

          <textarea
            id="composer-input"
            ref={inputRef}
            rows={1}
            value={text}
            placeholder="Ask a research question…"
            aria-invalid={Boolean(questionError)}
            aria-describedby={questionError ? "composer-question-error" : undefined}
            onChange={(event) => {
              setText(event.target.value);
              setTouched(true);
            }}
            onKeyDown={onKeyDown}
            autoFocus
          />
          <button
            type="submit"
            className="composer-send"
            disabled={!canSend}
            aria-label="Start the run"
            title={sendTitle}
          >
            <ArrowUp size={18} aria-hidden="true" />
          </button>
        </div>

        {questionError && (
          <p className="field-error" id="composer-question-error" role="alert">
            {questionError}
          </p>
        )}

        <div className="composer-meta">
          {mode === "demo" ? (
            <span
              className="chip"
              title="The fixture plan runs locally and writes the same event log. No provider is called."
            >
              {modeLabel("simulate")} · {engineLabel("fods")}
            </span>
          ) : blocker ? (
            <span className="chip" data-tone="warn" title={blocker}>
              Live unavailable
            </span>
          ) : (
            <span
              className="chip"
              data-tone="live"
              title="The full literature pipeline runs against the configured providers."
            >
              {modeLabel("live")} · {engineLabel("rla")}
            </span>
          )}

          {composer.topic.trim() && (
            <span className="chip" title="Topic label sent with the next run">
              {composer.topic.trim()}
            </span>
          )}

          <span className="spacer" />
          <span className="demo-hint">Enter to send · Shift+Enter for a new line</span>
        </div>
      </form>
    </div>
  );
}
