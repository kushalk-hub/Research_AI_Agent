# Research Studio Implementation Baseline

**Inspected:** 2026-11-01  
**Repository:** `D:\Research_AI_Agent-fods`  
**Branch / HEAD:** `codex/fods-mvp-acceptance` / `f533ae1ea8b0af7bdf99a6fee0d9f44d3b267ed8`  
**Worktree:** already contains uncommitted documentation, shell, webapp, test and prototype work. These files were preserved.

## Frontend and delivery

- Production app is a Python `ThreadingHTTPServer` in `src/fods/webapp.py` serving static HTML, CSS and JavaScript from `src/fods/web/`.
- The repository has no `package.json`, npm lockfile, TypeScript configuration or frontend bundler. Python packaging includes the FODS static web directory.
- `index.html` currently hosts the newer Research Studio shell and the classic workbench. `/?legacy=1` keeps the classic workbench reachable.
- The newer shell owns DOM rendering. Its SVG DAG uses explicit SVG DOM calls in `shell.js`; D3's line generator supplies curved dependency-edge geometry. Pinned `d3-path` 3.1.0 and `d3-shape` 3.2.0 UMD assets are served locally from `src/fods/web/vendor/` with their license texts. The execution environment has a Node runtime binary but no `npm`/`npx`; the required Context7 command could not run. Current line/curve behavior was verified against the official [D3 Lines](https://d3js.org/d3-shape/line) and [D3 Curves](https://d3js.org/d3-shape/curve) documentation.
- Decision: retain plain JavaScript and the current Python static-asset distribution. Do not add React or TypeScript. No runtime CDN or bundler dependency is introduced. D3 does not own or mutate the SVG DOM.

## API and event flow

| Route | Behavior |
|---|---|
| `GET /api/health` | Local app health response. |
| `GET /api/config` | Configured model names/provider names and credential-presence flags; no credential values. |
| `GET /api/history` | Reads persisted JSONL run files and reports run ID, mode, status, topic, model attribution, duration and event count. |
| `GET /api/contexts` | Reads saved topic-context snapshots. |
| `POST /api/runs` | Validates request, starts the existing `_execute`/`run_plan` implementation on a background thread and returns a run handle. |
| `GET /api/runs/{id}/events` | Server-sent event stream; supports `Last-Event-ID` and `?after=` sequence resumption. |
| `GET /api/runs/{id}/brief` | Reads the brief recorded by that run if it is inside the briefs directory. |
| `POST /api/replay` | Reads a persisted event log and publishes it as a replay run; does not execute tools. |
| `DELETE /api/runs/{id}` | Requests cancellation of a running task. |

Event envelope is currently backward-compatible JSON with `seq`, `kind`, `message`, `payload`, and Unix `timestamp`. Events include `run_started`, `plan_received`, `plan_validated`/`plan_rejected`, `task_ready`, `queue_updated`, `task_dequeued`, `task_started`, `task_completed`/`task_failed`/`task_blocked`/`task_cancelled`/`task_retry`, `stack_push`/`stack_pop`, model/source/tool/context events, `evidence_selected`, `citation_validation`, `brief_saved`, and `run_finished`. Queue updates carry `ready_queue`; plan validation carries tasks and topological levels; stack events carry the affected task and current frame list.

The event contract has ordered sequence numbers and timestamps but no top-level schema version, stable event UUID, worker ID, or causal/activity ID. Do not infer those fields in the browser. Scheduler snapshots can be projected from `queue_updated`; priority queue snapshots are emitted in priority/tie-break order, not as the internal binary heap array. A real heap-tree display requires additional authoritative instrumentation.

## Provider and source integration

- `src/fods/cli.py::_execute` is the production executor. Planner routing is fixture or configured Ollama; the web manager now rejects fixture planning for a fresh live run and maps live `auto` to the configured Ollama planner. Live source adapters are constructed by the real FODS research flow. Simulation uses deterministic fixture sources and deterministic answer drafting.
- Answer model routing uses the configured model settings; Gemini use is gated by `RLA_FODS_ALLOW_GEMINI=1` and key configuration. Run events record actual completed model calls.
- `fresh_sources` exists in the web request model and CLI executor; the web manager now passes it through and rejects cache bypass for simulation.
- Live source output records cache mode and provider/source outcomes. A cache hit must remain distinguishable from a fresh request.
- A real provider run still depends on the current machine's provider configuration, local Ollama availability or allowed model provider, network, quota and academic-source availability. No credential values are exposed in this document.

## Visualization gaps and implementation order

1. Make browser live runs fail closed when a fixture planner would otherwise be selected; pass through the explicit fresh-source policy.
2. Complete the Research and Library surfaces against existing run/context APIs, keeping the draft separate from selected persisted run data.
3. Keep queue-empty distinct from missing queue snapshots; show active task overlap without invented worker slots; derive stack frames at the selected event.
4. Add a deterministic event projection and regression coverage for cursor state and run provenance.
5. D3 path geometry is now locally served and used by the DAG. Add zoom/pan or further D3 modules only if a production interaction requires them.
6. Instrument true heap array snapshots if a heap-tree display is required; decide whether runtime worker IDs are safe/meaningful before showing numbered slots.
7. Verify server/API/SSE/replay, provider readiness and browser behavior. Run a real live request only when configured providers are available; preserve provider failures as failures.

## React / TypeScript decision

Neither is currently supported or necessary: the frontend is static JavaScript and the backend already serves it. Continue with one DOM owner per SVG. A frontend build step is not currently required because the pinned UMD assets are served as static files.
