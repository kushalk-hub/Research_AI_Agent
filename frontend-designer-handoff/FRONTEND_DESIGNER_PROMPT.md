# Task prompt: redesign the complete FODS frontend

You are the lead frontend product designer for FODS Research Studio. Redesign the entire user-facing web frontend and prepare a precise, implementation-ready handoff for a separate coding agent.

## Your authority

You own the design. Make the final calls on information architecture, navigation labels and structure, visual style, color theme, typography, page composition, element placement, responsive behavior, component patterns, and interaction presentation. Do not ask the requester to choose a palette, layout, or style. This is a clean-slate design exercise: do not inspect, request, or rely on an existing implementation, screenshot, prototype, design system, or prior design proposal. Work from the user needs and product requirements in this handoff. Invent a distinct, coherent new visual direction and layout.

The product requirements and data-integrity rules below are binding. There is no legacy layout to preserve. Explain your information-architecture decisions in `DESIGN.md`.

## Objective

Create a coherent redesign of every web page and important state in the FODS frontend. The result must help researchers start an investigation, read an evidence-backed answer, inspect how the run executed, explore FODS task structures, and find prior investigations and saved contexts. The design must also give a coding agent enough visual and behavioral detail to implement it without guessing.

This is a design task, not a production coding task. Do not modify application source files. Deliver a completed `DESIGN.md` and one sample-view artifact per page/state listed in `MOCKUP_DELIVERABLES.md`. Prefer a standalone HTML file for each artifact; use PNG only when HTML cannot show the intended view clearly. Package the editable sources and final artifacts in a ZIP.

## Read before designing

Read only the files in this handoff. Do not browse the repository or request implementation files, screenshots, prototypes, or previous design references. Base the design on `PRODUCT_CONTEXT.md` and the requirements below. If a behavior depends on details not included here, mark the assumption or the needed backend contract in `DESIGN.md`; do not present unsupported facts as real data.

## Product scope

Redesign the entire primary browser experience, including:

1. Starting a new research investigation and its validation/advanced settings.
2. Active, completed, partial, failed, and empty Research states.
3. The answer/brief, citation validation, and evidence inspection.
4. Recorded run Trace, event filtering, selection, details, and raw-payload disclosure.
5. FODS Lab visualizations: task dependency graph, scheduler/queue, task-state dictionary, per-task stacks, and shared event playback/cursor.
6. Library views for recorded investigations and saved contexts, including empty/loading/error/missing-data cases.
7. Replay provenance and replay playback states.
8. Responsive layouts and keyboard/focus/accessible alternatives.
9. A complete top-level navigation and shared application shell that make these capabilities feel like one product. Existing CLI and API are outside visual redesign scope.

Create a new information architecture and new navigation labels as you see fit, while keeping every capability above findable and clear. Avoid product language that implies durable multi-turn chat/session behavior; records are investigations/runs.

## Non-negotiable product truths

- A selected result belongs to one `run_id`. Its submitted question, actual mode, replay origin, answer, citations, evidence, brief, and trace must stay tied to that run or an explicitly recorded source run.
- Draft settings for the next investigation are independent of the selected run. Editing a draft must not rewrite the selected run's question or mode.
- Live research, deterministic simulation, and replay are distinct. Replay comes from a saved run and reads recorded events; it does not run fresh source/model calls.
- Show provider/model attribution only when the run records actual use. Configured settings are not proof of use. Missing facts display a clear unknown/“not recorded” treatment.
- Display only stored answer structure and evidence text. Do not fabricate summaries, findings, excerpts, authors, source identities, durations, event relationships, worker assignments, queue contents, heap states, graph relations, or quality metrics.
- Citation-ID validation is different from semantic support. Make that distinction explicit.
- A missing queue snapshot differs from a recorded empty queue. Inferred concurrent lanes must be labeled inferred; do not number or imply workers where no worker IDs exist.
- Task-state and stack visualizations must reflect recorded state/operations; incomplete or unavailable history must be labeled. Backward playback changes the view cursor and does not reverse runtime effects.
- Color cannot be the only carrier of state. Include textual/shape/icon cues and accessible contrast.
- Preserve safe handling: no credential values in browser-facing artifacts; do not make external calls from static mockups.

## Visual design process

1. Map the capabilities, user inputs, outputs, error cases, and persistence boundaries described in this handoff.
2. Propose the information architecture and explain the rationale in `DESIGN.md`.
3. Establish a complete visual system with named tokens and reusable components. You choose the aesthetic; make it coherent, legible, distinctive, and suitable for sustained research work.
4. Design each page for realistic content density and include the state variants in the deliverables list. Use representative sample data, clearly marked as illustrative wherever it is not a real fixture.
5. Make the design responsive at desktop, tablet, and narrow mobile widths. Specify behavior for complex graph and timeline surfaces on small screens.
6. Define interaction states: hover, focus, selected, disabled, loading, empty, success, partial, error, stale/missing, and confirmation where applicable.
7. Keep the result implementation-ready: define measurements/tokens, hierarchy, grid, component states, content rules, responsive breakpoints, and interaction behavior.

## Mockup requirements

- Produce a separate, directly openable HTML file for every entry in `MOCKUP_DELIVERABLES.md`. Each file is one page/state, not a collage of multiple screens. HTML mockups may contain small local interactions needed to demonstrate the design, but must not call a live backend or external service.
- Use realistic page content and show hierarchy, spacing, alignment, and component states. Do not substitute a text-only wireframe for a designed sample view.
- Keep mockups self-contained: local CSS and any local SVG/illustration assets; no CDN, remote font, or remote image dependency. Include sensible page title and semantic landmarks.
- At minimum include a clear selected-run identity, primary action, navigation, and relevant responsive behavior on each applicable page. Show visible focus styling and do not rely on color alone.
- Add an HTML index/preview page that links to each mockup and gives a short description. Include PNG captures only as optional review aids; HTML is the source of truth.
- Provide an image/export note with viewport dimensions used for review. Do not label illustrative values as real production evidence.

## `DESIGN.md` requirements

Complete `DESIGN.md` as the contract for the coding agent. Include:

- Product goals, users, key tasks, and design principles.
- Final information architecture, navigation, page/state inventory, and rationale for changes.
- Global shell and page-specific layout specs, including element order and responsive changes.
- Design tokens: colors (with accessible foreground/background combinations), typography, type scale, spacing, sizing, radii, borders, shadows, layers, motion, and focus treatment.
- Component inventory with states and behavior, including forms, buttons, tabs, badges, tables/lists, evidence inspector, dialogs/drawers, graph nodes/edges, queue, dictionary, stacks, event rows, filters, playback, and empty/error states as applicable.
- Content/label rules for run ID, submitted question, mode, status, replay origin, unknown data, citation validity, evidence excerpt, queue availability, inferred data, and unsupported features.
- Responsive behavior for desktop, tablet, and mobile, including navigation, inspector, graph, and timeline.
- Keyboard and accessibility behavior, including focus order, names, announcement expectations, reduced motion, non-color cues, and alternatives to visual-only interactions.
- Page-to-mockup cross-reference and any implementation notes, assumptions, risks, or items requiring future backend support.
- A concise “coding-agent implementation checklist” with prioritized build order and acceptance checks.

## Quality bar and final handoff

Before delivery, check every deliverable listed in `MOCKUP_DELIVERABLES.md`; verify every HTML page opens offline, links in the preview work, pages are distinct and complete, and content follows the data-truth rules. Do not run or modify application tests; this task is a design handoff.

Return:

1. The completed `DESIGN.md`.
2. One standalone HTML mockup for each listed page/state.
3. A clickable preview/index page.
4. Any optional PNG captures and source assets.
5. A ZIP containing the complete handoff.
6. A short delivery summary naming the files, design decisions, responsive/accessibility coverage, and any features that need backend support.

Do not ask the requester to make visual choices. Use your judgment and document it.
