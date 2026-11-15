# FODS Frontend Design System and Implementation Handoff

> Designer: replace this template with the final approved-by-designer specification. You own all visual and information-architecture decisions. This file is intentionally not a preselected style direction.

## 1. Product goals and users

### Primary users

_Describe the researcher, evaluator, and technical-inspection users based on repository evidence._

### Main tasks

_List the tasks the redesign supports and their success outcomes._

### Design principles

_Define the principles that explain the design choices made in this redesign._

## 2. Information architecture

### Navigation and global shell

_Document final destinations, global selected-run identity, primary actions, and responsive navigation._

### Page/state inventory and rationale

| Page/state | User goal | Key content/actions | Mockup file | Rationale/notes |
|---|---|---|---|---|
| Research — empty/new draft | | | | |
| Research — active | | | | |
| Research — completed brief/evidence | | | | |
| Research — partial/failed | | | | |
| Trace — events and selected-event details | | | | |
| FODS Lab — dependency graph | | | | |
| FODS Lab — scheduler/queue | | | | |
| FODS Lab — task state and stacks | | | | |
| Library — investigations/replay | | | | |
| Library — saved contexts | | | | |
| Shared loading/empty/error/missing-data states | | | | |
| Full product shell/navigation | | | | |

_Add, remove, or split pages as needed, but account for every capability and deliverable in the prompt._

## 3. Visual system

### Design rationale

_Describe the visual direction and why it serves this product. All choices are yours._

### Tokens

| Token | Value | Usage/accessibility notes |
|---|---|---|
| Color palette | | |
| Typography and type scale | | |
| Spacing scale | | |
| Content widths and grid | | |
| Border/radius | | |
| Elevation/layers | | |
| Motion | | |
| Focus/selection | | |

Include actual CSS custom-property names/values and contrast pairings in the completed version.

## 4. Shared shell and page specifications

_For each page, document viewport composition, region order, hierarchy, key dimensions, scroll behavior, and responsive transformations. Cross-reference its HTML mockup._

## 5. Components and interaction states

| Component | Purpose | States | Keyboard/interaction behavior | Data/content rule |
|---|---|---|---|---|
| Navigation | | | | |
| Investigation composer | | | | |
| Run provenance/status | | | | |
| Progress and evidence | | | | |
| Brief/citations/evidence inspector | | | | |
| Trace filters/event rows/inspector | | | | |
| Dependency graph | | | | |
| Scheduler/queue | | | | |
| Task-state dictionary | | | | |
| Per-task stack | | | | |
| Playback/event cursor | | | | |
| Investigation/context library | | | | |
| Empty/loading/error/missing-data | | | | |

## 6. Content and data integrity rules

_Specify exact labels and presentation for actual mode vs configured mode, replay source, unknown metadata, citation-ID validity, semantic support, excerpt availability, empty vs unrecorded queue, inferred concurrency, missing correlation, partial/error runs, and unsupported/future features._

## 7. Responsive behavior

| Breakpoint/device class | Global shell | Research | Trace | FODS Lab | Library |
|---|---|---|---|---|---|
| Desktop | | | | | |
| Tablet | | | | | |
| Narrow mobile | | | | | |

## 8. Accessibility

_Document semantic landmarks, heading structure, keyboard order, visible focus, accessible names, status announcements, non-color state cues, contrast, reduced motion, and usable alternatives for graph/timeline interactions._

## 9. Mockup cross-reference

| Mockup file | Page/state | Key design questions answered |
|---|---|---|

## 10. Implementation notes and dependencies

### Supported by current backend

_List what can be implemented from the current web API/events._

### Requires backend or instrumentation changes

_List unsupported capabilities and safe fallback behavior._

### Assumptions and risks

_Document assumptions the coding agent should verify._

## 11. Coding-agent implementation checklist

1. _Prioritized implementation step._
2. _Responsive/accessibility step._
3. _Data integrity and run identity checks._
4. _Visual comparison/review step._

## 12. Design decisions

| Decision | Chosen approach | Alternatives considered | Reason |
|---|---|---|---|

