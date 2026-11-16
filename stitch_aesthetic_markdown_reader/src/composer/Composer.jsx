import { ArrowUp } from "lucide-react";
import { useState } from "react";
import { engineLabel, modeLabel } from "../lib/events.js";
import { topicFromQuestion, useStartRun } from "./useStartRun.js";

function fieldErrors(fields) {
  if (!Array.isArray(fields)) return [];
  return fields.slice(0, 3).map((field) => {
    const name = Array.isArray(field?.loc) ? field.loc.filter((part) => part !== "body").join(".") : "";
    return name ? `${name}: ${field.msg || "invalid value"}` : field?.msg || "invalid value";
  });
}

export default function Composer({ config, inputRef }) {
  const [text, setText] = useState("");
  const { start, busy, error, clearError } = useStartRun();

  const question = text.trim();
  const canSend = question.length >= 3 && !busy;
  const budget = Number(config?.llm_request_budget);
  const keyless = config?.gemini_key_configured === false;

  async function submit(event) {
    event?.preventDefault();
    if (!canSend) return;
    const handle = await start({
      topic: topicFromQuestion(question),
      question,
      engine: "rla",
      mode: "live",
      planner: "auto",
    });
    if (handle) setText("");
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(event);
    }
  }

  return (
    <div className="composer-dock">
      <form className="composer" onSubmit={submit}>
        {error && (
          <div className="composer-error" role="alert">
            <div>
              <strong>{error.message}</strong>
              {fieldErrors(error.fields).length > 0 && (
                <ul>
                  {fieldErrors(error.fields).map((message) => (
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

        <label className="visually-hidden" htmlFor="composer-input">
          Research question
        </label>
        <div className="composer-box">
          <textarea
            id="composer-input"
            ref={inputRef}
            rows={1}
            value={text}
            placeholder="Ask a research question…"
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            autoFocus
          />
          <button
            type="submit"
            className="composer-send"
            disabled={!canSend}
            aria-label="Start the run"
            title={canSend ? "Start the run (Enter)" : "Type at least 3 characters"}
          >
            <ArrowUp size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="composer-meta">
          <span className="chip" title="The full literature pipeline runs live and needs a configured provider.">
            {engineLabel("rla")}
          </span>
          <span className="chip" title="Live runs call the configured providers.">
            {modeLabel("live")}
          </span>
          {Number.isFinite(budget) && budget > 0 && (
            <span
              className="chip"
              title="Configured per-run LLM request cap. It is a local budget, not a provider quota guarantee."
            >
              {budget}-call cap
            </span>
          )}
          {keyless && (
            <span className="chip" data-tone="warn" title="Set GEMINI_API_KEY to run live.">
              No API key — live runs will fail
            </span>
          )}
          <span className="spacer" />
          <span className="demo-hint">Enter to send · Shift+Enter for a new line</span>
        </div>
      </form>
    </div>
  );
}
