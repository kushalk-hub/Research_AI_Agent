# Required standalone page/state mockups

Create one standalone HTML mockup per row. These are design deliverables for the designer agent to create; this handoff kit intentionally does not preselect a visual design. The designer may alter page names or consolidate navigation, but must still supply a view that covers each required use case/state. Add views if the chosen information architecture introduces more distinct pages.

| ID | Required sample view | Required visible content/state |
|---|---|---|
| 01 | Research — empty/new investigation | Question field, optional topic, live vs deterministic simulation choice, primary start action, advanced controls/disclosure, validation or helper treatment, navigation. No replay in new-run choices. |
| 02 | Research — active investigation | Submitted question, selected run identity and actual mode, progress/task counts, available event-backed progress, waiting/failure representation, cancel if supported, route to Trace/Lab. |
| 03 | Research — completed brief | Same-run question/mode/status, stored answer, citation IDs/validation wording, evidence list/inspector entry, saved brief state only if eligible. |
| 04 | Research — partial or failed | Clear partial/failure status, useful explanation/error details, surviving evidence/results if present, recovery/next action only when supported. |
| 05 | Trace — selected event | Event sequence, filters, readable chronological events, selected-event fields, collapsed raw payload, missing/correlation/duration treatment, pause/resume where applicable. |
| 06 | FODS Lab — dependency graph | Accepted DAG topology, task role/state, selected node/inspector, edges/legend, synchronized cursor, empty/no-plan variant indication. |
| 07 | FODS Lab — scheduler/queue | Recorded enqueue/dequeue/priority order, front/rear where applicable, actual vs missing queue snapshot, inferred concurrency labeled clearly if shown. |
| 08 | FODS Lab — task state and stacks | Task ID → state dictionary and per-task LIFO stacks with TOP marker; stored operations/history limitations explicit. |
| 09 | Library — investigations and replay | Search/filter/history rows, actual mode/status, run identity/artifacts, replay action and source provenance; empty or missing-log treatment. |
| 10 | Library — saved contexts | Saved-context list/detail with only recorded topic/hash/version/count/freshness relationships; empty and missing-metadata treatment. |
| 11 | Shared narrow-mobile sample | Designer-selected representative page showing responsive navigation, run provenance, primary content, and an accessible path to graph/timeline/inspector detail. |
| 12 | Full product shell / navigation | Show the new global information architecture and the path between the major areas. This must be a newly conceived shell, not a reconstruction of a pre-existing application layout. |

## File and review rules

- Use `mockups/01-research-empty.html` through `mockups/12-product-shell.html` (or a consistently numbered equivalent) so each view is easy to identify.
- Add `mockups/index.html` as a clickable index linking to every sample. The index is not a replacement for per-page files.
- Each HTML file must open locally without a server, external network, CDN, or credentials. Inline/local CSS and SVG are acceptable. Keep sample values clearly illustrative unless copied from a committed fixture and identified as such.
- Each page should show a designed page at a sensible viewport and include responsive CSS or a short annotation explaining its responsive treatment. At least one separate mobile view is required (ID 11).
- Optional PNG exports may accompany HTML, with viewport dimensions and filenames documented in the index. HTML remains editable source of truth.
- Zip all mockups, the completed `DESIGN.md`, design assets, and an index/README. The zip must not contain secrets, `.env`, caches, or unrelated repository files.
