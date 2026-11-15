# FODS frontend redesign handoff

This package briefs a frontend designer agent to create a clean-slate design for the complete FODS web product and produce a reviewable implementation handoff. It intentionally contains no source code, screenshots, prior mockups, or previous design proposals.

## Files

- `FRONTEND_DESIGNER_PROMPT.md` — copy-ready task prompt for the designer agent.
- `DESIGN.md` — the design system and implementation guide the designer must complete.
- `PRODUCT_CONTEXT.md` — an implementation-independent product brief and data-integrity requirements.
- `MOCKUP_DELIVERABLES.md` — required standalone page/state mockup inventory and delivery rules.

The designer owns all creative decisions: information architecture, page composition, visual hierarchy, color, typography, spacing, components, and interaction presentation. Start from user needs and the product brief; do not use an existing layout or visual reference as a baseline.

## Output expected from the designer

Return a completed `DESIGN.md` plus one standalone HTML mockup per page/state listed in `MOCKUP_DELIVERABLES.md` (or PNGs if HTML is impractical). Include the source and a ZIP with those files. Mockups should be static, self-contained review artifacts; production implementation belongs to the coding agent.
