import { useCallback, useEffect, useRef } from "react";
import { api } from "../api/client.js";
import Composer from "../composer/Composer.jsx";
import { useStartRun } from "../composer/useStartRun.js";
import { useStopRun } from "../composer/useStopRun.js";
import { isTerminal } from "../lib/events.js";
import { selectActiveRun, selectRecents } from "../store/selectors.js";
import { useDispatch, useStore } from "../store/store.jsx";
import { useRunStream } from "../store/useRunStream.js";
import Sidebar from "../sidebar/Sidebar.jsx";
import Thread from "../thread/Thread.jsx";
import StatusChip from "../ui/StatusChip.jsx";
import LabView from "../views/LabView.jsx";
import LibraryView from "../views/LibraryView.jsx";
import TraceView from "../views/TraceView.jsx";
import { routeByKey } from "./routes.js";

export default function App() {
  const state = useStore();
  const dispatch = useDispatch();
  const inputRef = useRef(null);
  const { replay, busy, error: replayError, clearError } = useStartRun();
  const { stop } = useStopRun();

  const activeRun = selectActiveRun(state);
  const recents = selectRecents(state);
  const route = routeByKey(state.page);
  const liveActive = Boolean(
    activeRun && (activeRun.stream === "live" || activeRun.stream === "connecting"),
  );

  useRunStream(state.activeRunId);

  const refreshHistory = useCallback(async () => {
    try {
      const result = await api.history();
      dispatch({ type: "history/loaded", history: result.runs || [] });
    } catch {
      /* the connection badge already reports an unreachable runtime */
    }
  }, [dispatch]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [config, history, contexts] = await Promise.all([
          api.config(),
          api.history(),
          api.contexts(),
        ]);
        if (cancelled) return;
        dispatch({
          type: "bootstrap/succeeded",
          config,
          history: history.runs || [],
          contexts: contexts.contexts || [],
        });
      } catch (reason) {
        if (cancelled) return;
        dispatch({ type: "bootstrap/failed", message: reason?.message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  useEffect(() => {
    document.title = `${route.label} · FODS Research Studio`;
  }, [route.label]);

  const focusComposer = useCallback(() => {
    dispatch({ type: "ui/page", page: "research" });
    inputRef.current?.focus();
  }, [dispatch]);

  const newInvestigation = useCallback(async () => {
    // Closing the stream while the run keeps burning quota would be dishonest.
    // A live run is stopped first; if the request fails the conversation stays
    // visible and the banner explains why.
    const active = state.runs[state.activeRunId];
    const live =
      active &&
      !active.historical &&
      active.kind !== "replay" &&
      (active.stream === "live" ||
        active.stream === "connecting" ||
        active.status === "running" ||
        active.status === "starting") &&
      !active.events.some(isTerminal);
    if (live && !active.stopping) {
      const result = await stop(active.id);
      if (!result.ok) return;
    }
    dispatch({ type: "ui/new-investigation" });
    inputRef.current?.focus();
  }, [state.runs, state.activeRunId, stop, dispatch]);

  useEffect(() => {
    function onKeyDown(event) {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      const typing =
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if (typing) return;
      if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        newInvestigation();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [newInvestigation]);

  async function openRecent(item) {
    if (item.live && state.runs[item.run_id]) {
      dispatch({ type: "run/selected", runId: item.run_id });
      dispatch({ type: "ui/page", page: "research" });
      return;
    }
    const handle = await replay(item.run_id);
    if (handle) dispatch({ type: "ui/page", page: "research" });
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>

      <Sidebar
        page={state.page}
        connection={state.connection}
        recents={recents}
        onNavigate={(page) => dispatch({ type: "ui/page", page })}
        onNew={newInvestigation}
        onOpenRecent={openRecent}
        onRefreshHistory={refreshHistory}
      />

      <div className="workspace" id="workspace">
        <header className="topbar">
          <div className="topbar-heading">
            <h1>{route.label}</h1>
            {activeRun && (
              <>
                <StatusChip
                  status={activeRun.stopping ? "stopping" : activeRun.status}
                  reason={activeRun.statusReason}
                />
                <code className="mono">{activeRun.id}</code>
              </>
            )}
          </div>
          <div className="topbar-actions">
            <span className="demo-hint">
              {state.connection === "ready"
                ? "Local only"
                : state.connection === "down"
                  ? "Runtime unreachable"
                  : "Connecting…"}
            </span>
          </div>
        </header>

        {replayError && (
          <div className="banner-error" role="alert">
            <strong>{replayError.message}</strong>
            <button type="button" className="btn btn--ghost btn--sm" onClick={clearError}>
              Dismiss
            </button>
          </div>
        )}

        {state.error && (
          <div className="banner-error" role="alert">
            <strong>{state.error.message}</strong>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => dispatch({ type: "ui/clear-error" })}
            >
              Dismiss
            </button>
          </div>
        )}

        <main className="view" aria-label={route.label}>
          {state.page === "research" && (
            <Thread
              state={state}
              run={activeRun}
              onFocusComposer={focusComposer}
              onOpenTrace={() => dispatch({ type: "ui/page", page: "trace" })}
            />
          )}
          {state.page === "trace" && (
            <TraceView run={activeRun} onFocusComposer={focusComposer} />
          )}
          {state.page === "lab" && (
            <LabView
              state={state}
              run={activeRun}
              onFocusComposer={focusComposer}
              onLab={(patch) => dispatch({ type: "lab/update", patch })}
            />
          )}
          {state.page === "library" && (
            <LibraryView
              history={state.history}
              onReplay={openRecent}
              busy={busy}
              liveActive={liveActive}
            />
          )}
        </main>

        {state.page === "research" && <Composer config={state.config} inputRef={inputRef} />}
      </div>
    </div>
  );
}
