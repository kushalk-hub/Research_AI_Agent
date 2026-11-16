import { useEffect } from "react";
import { api } from "../api/client.js";
import { openRunStream } from "../api/sse.js";
import { useDispatch } from "./store.jsx";

/** Subscribe to the active run's event stream. One stream at a time: when the
 *  viewed run changes, the previous connection is closed. */
export function useRunStream(runId) {
  const dispatch = useDispatch();

  useEffect(() => {
    if (!runId) return undefined;
    let disposed = false;
    dispatch({ type: "run/stream", runId, stream: "connecting" });

    const stream = openRunStream({
      runId,
      onBatch: (events) => dispatch({ type: "run/events", runId, events }),
      onState: (streamState) => dispatch({ type: "run/stream", runId, stream: streamState }),
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
