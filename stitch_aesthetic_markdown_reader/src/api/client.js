/** Typed HTTP client for the local FODS runtime.
 *
 *  The browser is a read-only observer: every call here either reads recorded
 *  state or asks the local server to run/replay something. No provider, model or
 *  secret is ever touched from this side.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, code = "", fields = [] } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

function idempotencyKey() {
  const random = globalThis.crypto?.randomUUID?.();
  return random || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request(path, { method = "GET", body, headers = {} } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? headers : { "Content-Type": "application/json", ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the local runtime.", { code: "network" });
  }

  const type = response.headers.get("content-type") || "";
  let payload = null;
  if (type.includes("json")) {
    payload = await response.json().catch(() => null);
  } else {
    payload = await response.text().catch(() => "");
  }

  if (!response.ok) {
    const message =
      (payload && typeof payload === "object" && payload.error) ||
      `Request failed (${response.status})`;
    throw new ApiError(message, {
      status: response.status,
      code: (payload && typeof payload === "object" && payload.code) || "",
      fields: (payload && typeof payload === "object" && payload.fields) || [],
    });
  }

  return payload;
}

export const api = {
  health: () => request("/api/health"),
  config: () => request("/api/config"),
  contexts: () => request("/api/contexts"),
  history: () => request("/api/history"),
  run: (runId) => request(`/api/runs/${runId}`),

  /** Start a run. `payload` is validated again by the server (NewRun). */
  createRun: (payload) =>
    request("/api/runs", {
      method: "POST",
      body: payload,
      headers: { "Idempotency-Key": idempotencyKey() },
    }),

  replayRun: (runId, speedMs = 0) =>
    request("/api/replay", { method: "POST", body: { run_id: runId, speed_ms: speedMs } }),

  stopRun: (runId) => request(`/api/runs/${runId}`, { method: "DELETE" }),

  brief: async (runId, { download = false } = {}) => {
    const query = download ? "?download=1" : "";
    const response = await fetch(`/api/runs/${runId}/brief${query}`);
    if (!response.ok) {
      throw new ApiError(
        response.status === 404 ? "No saved brief for this run." : "The brief could not be read.",
        { status: response.status, code: "brief" },
      );
    }
    return response.text();
  },

  /** UI-10: the brief as content, not a raw download in a new tab. */
  briefDocument: (runId) => request(`/api/runs/${runId}/brief?format=json`),
};
