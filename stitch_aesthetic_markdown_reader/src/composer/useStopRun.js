import { useCallback } from "react";
import { ApiError, api } from "../api/client.js";
import { useDispatch } from "../store/store.jsx";

/** Ask the local runtime to stop a live run (A-10).
 *
 *  Honesty rules:
 *  - The chip changes to "Stopping…" only after the request is sent; a failed
 *    request is reported in the app banner and the pending flag is cleared.
 *  - A 409 means the run already finished. That is not an error: the info
 *    fetch reconciles the chip with what was recorded.
 *  - Nothing here claims the run stopped. Only the recorded terminal event
 *    (`termination_reason: "cancelled"`) can do that, and the reducer clears
 *    the pending flag when it arrives. */
export function useStopRun() {
  const dispatch = useDispatch();

  const stop = useCallback(
    async (runId) => {
      if (!runId) return { ok: false, message: "There is no live run to stop." };
      dispatch({ type: "run/stop-requested", runId });
      try {
        await api.stopRun(runId);
        return { ok: true };
      } catch (reason) {
        dispatch({ type: "run/stop-rejected", runId });
        if (reason instanceof ApiError && reason.code === "run_finished") {
          try {
            const info = await api.run(runId);
            dispatch({ type: "run/info", runId, info });
          } catch {
            /* the recorded stream remains the source of truth */
          }
          return { ok: true, alreadyFinished: true };
        }
        const message = reason?.message || "The run could not be stopped.";
        const code = reason?.code || "";
        dispatch({ type: "ui/error", message, code });
        return { ok: false, message, code };
      }
    },
    [dispatch],
  );

  return { stop };
}
