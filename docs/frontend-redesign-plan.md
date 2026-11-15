# Frontend redesign and React migration plan

## Goal

Replace the current browser interface with the visual direction in
`stitch_aesthetic_markdown_reader/`. Preserve the existing research, simulation,
replay, evidence, and telemetry behavior while rebuilding the presentation as a
responsive React application. The reference HTML and screenshots are design
inputs; their sample papers, run IDs, events, timing, and graph shapes are not
runtime data and must never appear as application content.

## Design references

- `alexandria/DESIGN.md`: premium editorial reading, serif narrative typography,
  quiet tonal surfaces, generous whitespace, soft controls, and archival gold.
- `editorial_dialectic/DESIGN.md`: alabaster canvas, Newsreader and Plus Jakarta
  Sans, JetBrains Mono for telemetry, teal verified evidence, amber in-flight or
  simulated states, clear missing-data treatment, and responsive split panes.
- `research_new_investigation_composer/`: research composer and recent inquiries.
- `research_completed_brief_evidence_inspector_clean_modern/`: completed brief
  with inline citation and evidence inspector.
- `library_investigations_replay_provenance_clean_modern/`: searchable run
  library with mode, status, provenance, and replay affordances.
- `fods_lab_runtime_dependency_graph_clean_modern/`: timeline and dependency
  graph with a selected-node inspector.
- `fods_lab_scheduler_queue_clean_modern/`: queue policy, queue depth, dispatch
  latency, queue items, active lanes, and recent dispatch events.
- `fods_lab_task_stacks_state_dictionary_clean_modern/`: time scrubber, task
  dictionary, filters, and stack frames.

Where the references disagree, use the Editorial Dialectic palette and
typography as the shared system, and Alexandria's tonal layering and editorial
reading principles. Keep operational states explicit and high contrast.

## Existing runtime seam to preserve

The Python server in `src/fods/webapp.py` owns all work and remains the source of
truth. The new frontend must use its same-origin endpoints:

- `GET /api/health`, `/api/config`, `/api/history`, `/api/contexts`
- `GET /api/runs/{id}`, `/api/runs/{id}/events`, `/api/runs/{id}/brief`
- `POST /api/runs`, `POST /api/replay`, `DELETE /api/runs/{id}`

Run creation, model calls, retrieval, citation validation, output writing,
simulation, replay, and cancellation remain server responsibilities. The UI
renders recorded events and derived snapshots; it must not invent task
dependencies, queue order, stack frames, citations, confidence, durations, or
research content. Existing API payloads and event envelopes are the integration
contract. Any required contract change must be separately justified and tested.

## Product structure

1. **Research** — new-run composer, research-mode selection where supported,
   topic, question, paper limit, provider wait, model request budget, advanced
   runtime settings, live progress, final cited answer, source cards, and brief
   link. The full literature pipeline is the primary action and default engine.
2. **Execution Trace** — chronological recorded event stream, event filters,
   payload inspector, and replay cursor. Unrecorded fields are visibly marked;
   do not synthesize missing telemetry.
3. **FODS Lab** — three tabs: Dependency Graph, Queue & Scheduler, and Task
   Stacks. Graph layout is computed from the actual plan dependencies and task
   states. Queue and stack views derive from recorded events using the existing
   snapshot logic. Timeline playback and selection only move through recorded
   events.
4. **Library** — searchable persisted run list, mode/status/provenance metadata,
   inspect completed results, and replay eligible runs.

Shared shell: brand/navigation header, connection state, run identity/status,
new investigation action, and responsive navigation. Desktop uses a navigation
rail plus flexible analytical canvas and evidence/telemetry inspector. Tablet
turns inspectors into drawers. Mobile uses a single column with segmented Brief,
Evidence, and Trace navigation.

## Visual and interaction requirements

- Colors: alabaster background `#F8F9FA`, white reading surfaces, slate ink
  `#0F172A`, verified teal `#0F766E`, archival amber `#B45309`, and crimson
  `#BE123C` for failures and invalid evidence.
- Typography: Newsreader for briefs, questions, abstracts, and evidence prose;
  Plus Jakarta Sans for navigation, controls, labels, and tables; JetBrains Mono
  for IDs, hashes, event payloads, and measured values.
- Favor whitespace, surface tone shifts, soft elevation, and modest 4–12px
  radii. Avoid the old visual language, neon effects, arbitrary graphs, and
  decorative metrics.
- Keep animation functional: task/edge transitions follow real task-state
  changes; queue and stack changes follow new recorded events; cite-chip
  selection focuses the associated source; timeline playback advances through
  the actual event list. Respect `prefers-reduced-motion`.
- Include loading, empty, partial, failed, completed, and connection-lost
  states. Partial-source failures and the full-text phase stub must remain
  legible and honest.
- All controls are keyboard reachable, labeled, and usable at narrow widths.

## React implementation

- Add a Vite-managed React application under
  `stitch_aesthetic_markdown_reader/src/`; keep source modules
  separate from the generated static bundle.
- Use React and React DOM for the app, a dependency-driven SVG graph whose
  nodes and edges come only from the validated plan, and `lucide-react` for
  consistent icons. Use native CSS layout and transitions for the remaining
  views; avoid adding a large visual framework.
- Add one small same-origin frontend adapter for HTTP, Server-Sent Events,
  history, config, and replay. Keep endpoint details out of view modules.
- Parse the existing SSE envelope into one normalized client-side run state;
  derive graph/queue/stack snapshots from events, not from presentation fixtures.
- Build the app into `src/fods/web/dist/`. Serve only a fixed allow-list of
  generated assets from the Python server, retaining its same-origin CSP. Do not
  introduce a development CDN dependency.
- Preserve the current UI temporarily only during migration. Remove the old
  shell, its entry scripts, and obsolete styles after parity and browser
  verification, so the new React app is the one served at `/`.

## Phases and completion gates

### Phase 1 — Inventory and contract capture

- Read every Markdown design specification, all reference HTML files, and
  inspect all screenshots.
- Record the visual system, page inventory, server routes, event envelope, and
  existing runtime guarantees in this plan.
- Gate: each screenshot page has a corresponding new React view and a stated
  data source.

### Phase 2 — React foundation and shared shell

- Create the Vite/React source tree, build script, style tokens, font setup,
  layout primitives, navigation, responsive shell, and API/SSE adapter.
- Make the root route and static asset serving use the built application.
- Gate: production build loads from the Python server with same-origin assets;
  health/config/history render without mock data.

### Phase 3 — Research and completed brief

- Implement composer, bounded execution options, progress, paper results,
  answer, validated citation chips, evidence inspector, and saved-brief link.
- Gate: submit a live run from the browser and verify the existing backend
  completes retrieval through answer; inspect citations and saved brief.

### Phase 4 — Library, trace, and replay

- Implement searchable persisted history, run inspection, event filtering,
  payload details, cursor controls, and replay.
- Gate: select existing records, replay an eligible run, and confirm the trace
  and displayed state match the server event order.

### Phase 5 — Data-driven FODS Lab

- Compute graph layout from plan dependency edges; animate only observed task
  state transitions. Render node details from selected task/event data.
- Render queue and scheduler details from recorded queue events. Render stack
  dictionary and frames from recorded stack events.
- Gate: verify graph nodes/edges and queue/stack states against recorded event
  payloads, including an empty or absent-data case. No reference fixture values
  may be surfaced.

### Phase 6 — Responsive and accessibility pass

- Verify desktop, tablet, and mobile layouts; keyboard navigation, focus, text
  contrast, reduced motion, and long paper titles/abstracts.
- Gate: each main view stays usable at widths 1440px, 1024px, and 390px.

### Phase 7 — Remove old frontend and verify

- Remove obsolete static UI files and legacy script tags after the React build is
  the sole root implementation. Keep any files with independent runtime or test
  consumers until those consumers have a replacement.
- Verify lint/build and relevant API tests. Use the browser to complete a real
  user-initiated frontend run, inspect its result, and confirm the saved data and
  graph remain consistent.
- Gate: only the redesigned UI is served; no hardcoded operational telemetry;
  the user can start, observe, inspect, and read a complete pipeline run.

## Current status

- Phase 1 design and route inventory completed.
- React source, responsive editorial shell, research/demo composer, trace,
  library, event-derived runtime lab, and static asset route are implemented.
- React production build and browser verification remain blocked because package
  registry access is unavailable and the dependencies are not cached locally.
- The working tree already contains prior full-pipeline UI integration. Preserve
  it while changing presentation; do not discard the live pipeline adapter.

## Risks and decisions

- The environment's automatic approval review blocked Context7 CLI invocation
  before execution due to an account usage limit. React documentation could not
  be fetched in this turn. The offline npm install also confirmed the required
  packages are not cached, so the production build and browser check remain
  pending until registry access is available.
- Reference HTML uses CDN Tailwind and sample static telemetry. Neither should
  be copied as a runtime dependency or as application data.
- Full-text retrieval remains an upstream phase-2 stub; the UI must label this
  rather than imply full-text extraction.
