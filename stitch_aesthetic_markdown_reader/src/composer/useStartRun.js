import { useCallback, useState } from "react";
import { ApiError, api } from "../api/client.js";
import { shorten } from "../lib/format.js";
import { useDispatch, useStore } from "../store/store.jsx";

/** Requests the runtime accepts (see webapp.NewRun). Only fields the UI sets are
 *  sent: the server forbids unknown keys. */
const BASE = {
  engine: "rla",
  mode: "live",
  planner: "auto",
  schedule: "fifo",
  concurrency: 3,
  source_limit: 3,
  paper_limit: 5,
  delay_ms: 150,
};

export const DEMO_REQUEST = {
  ...BASE,
  engine: "fods",
  mode: "simulate",
  planner: "fixture",
  topic: "Deterministic demo",
  question: "How does the scheduler turn a plan into observable tasks?",
};

function toError(reason) {
  if (reason instanceof ApiError) {
    return { message: reason.message, code: reason.code, fields: reason.fields || [] };
  }
  return { message: reason?.message || "The run could not be started.", code: "", fields: [] };
}

/** Starts runs and replays, and refuses to start a second one while the open run
 *  is still live — the runtime owns at most one run per tab. */
export function useStartRun() {
  const dispatch = useDispatch();
  const { activeRunId, runs } = useStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const blocked = useCallback(() => {
    const active = activeRunId ? runs[activeRunId] : null;
    if (!active) return false;
    const live = active.stream === "live" || active.stream === "connecting";
    if (live) {
      setError({
        message: "A run is already open. Wait for it to finish, or stop it first.",
        code: "busy",
        fields: [],
      });
      return true;
    }
    return false;
  }, [activeRunId, runs]);

  const start = useCallback(
    async (request) => {
      if (blocked()) return null;
      setBusy(true);
      setError(null);
      try {
        const handle = await api.createRun(request);
        dispatch({ type: "run/opened", handle, request });
        return handle;
      } catch (reason) {
        setError(toError(reason));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [blocked, dispatch],
  );

  const replay = useCallback(
    async (runId) => {
      if (blocked()) return null;
      setBusy(true);
      setError(null);
      try {
        const handle = await api.replayRun(runId, 0);
        dispatch({
          type: "run/opened",
          handle,
          request: { mode: "replay", engine: handle.engine, topic: handle.topic },
        });
        return handle;
      } catch (reason) {
        setError(toError(reason));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [blocked, dispatch],
  );

  return {
    start,
    replay,
    startDemo: () => start(DEMO_REQUEST),
    busy,
    error,
    clearError: () => setError(null),
  };
}

/** The runtime wants a short topic as well as the question; derive one from the
 *  question so a single input stays honest. */
export function topicFromQuestion(question) {
  return shorten(question, 80) || "Untitled investigation";
}
