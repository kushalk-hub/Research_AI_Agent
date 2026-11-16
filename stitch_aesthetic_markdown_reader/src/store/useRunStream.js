import { useEffect } from "react";
import { api } from "../api/client.js";
import { openRunStream } from "../api/sse.js";
import { useDispatch } from "./store.jsx";

/** Subscribe to the active run's event stream. One stream at a time: when the
 *  viewed run changes, the previous connection is closed.
 *
 *  The chip is reconciled with `GET /api/runs/<id>` on mount (so a run opened
 *  from history shows its real status immediately), on selection (the effect
 *  re-runs) and after a reconnect (`onState("live")`). A terminal event already
 *  in the stream always wins over a late fetch (reducer `run/info`). */
export function useRunStream(runId) {
  const dispatch = useDispatch();

  useEffect(() => {
    if (!runId) return undefined;
    let disposed = false;

    const reconcile = () => {
      api
        .run(runId)
        .then((info) => {
          if (!disposed) dispatch({ type: "run/info", runId, info });
        })
        .catch(() => {
          /* the stream state already reports an unreachable runtime */
        });
    };

    dispatch({ type: "run/stream", runId, stream: "connecting" });
    reconcile();

    const stream = openRunStream({
      runId,
      onBatch: (events) => dispatch({ type: "run/events", runId, events }),
      onState: (streamState) => {
        dispatch({ type: "run/stream", runId, stream: streamState });
        if (streamState === "live") reconcile();
      },
      onTerminal: () => {
        api
          .history()
          .then((result) => {
            if (!disposed) dispatch({ type: "history/loaded", history: result.runs || [] });
          })
          .catch(() => {});
      },
    });

    return () => {
      disposed = true;
      stream.close();
    };
  }, [runId, dispatch]);
}
