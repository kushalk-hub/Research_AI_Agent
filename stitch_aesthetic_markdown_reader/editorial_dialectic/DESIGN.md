---
name: Editorial Dialectic
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#45464d'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#006a63'
  on-secondary: '#ffffff'
  secondary-container: '#99efe5'
  on-secondary-container: '#006f67'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#331200'
  on-tertiary-container: '#cf6721'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#9cf2e8'
  secondary-fixed-dim: '#80d5cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#00504a'
  tertiary-fixed: '#ffdbca'
  tertiary-fixed-dim: '#ffb68e'
  on-tertiary-fixed: '#331200'
  on-tertiary-fixed-variant: '#763300'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  display-lg:
    fontFamily: Newsreader
    fontSize: 48px
    fontWeight: '400'
    lineHeight: 56px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Newsreader
    fontSize: 32px
    fontWeight: '400'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Newsreader
    fontSize: 32px
    fontWeight: '500'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Newsreader
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 32px
    letterSpacing: 0em
  headline-md:
    fontFamily: Newsreader
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 32px
  headline-sm:
    fontFamily: Newsreader
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
  body-lg:
    fontFamily: Newsreader
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Newsreader
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.04em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 2rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system crafts an intellectually serene, highly credible environment tailored for deep academic rigor, synthesis, and autonomous agent runtime inspection. It reconciles two distinct modalities: the literary authority of long-form academic publication and the precise, deterministic clarity required for systems observability and runtime analysis.

The aesthetic philosophy centers on **warm editorial precision**:
- **Tone & Demeanor**: Authoritative yet unhurried, rigorous, transparent, and quietly confident. It discards sterile enterprise uniformity and abrasive neon developer-terminal motifs in favor of warm scholarly grounding.
- **Visual Paradigms**: Tactile paper-grade surfaces, crisp micro-borders, generous typographic line heights, and explicit operational state badges.
- **Mental Model**: The workspace is structured as a scholarly laboratory desk—where raw telemetry feeds, synthesized hypotheses, and peer citations coexist with absolute structural hierarchy and no visual clutter.

## Colors

The color system relies on natural editorial warmth, subtle paper tints, and high semantic contrast. The system operates primarily in light mode to mirror reading on physical stock, reducing eye fatigue during multi-hour synthesis and code inspection sessions.

### Functional Palette Logic
- **Primary (`#0F172A`) — Slate Obsidian**: High-contrast text, primary structural headings, active tool states, and core UI boundaries. Ensures deep optical contrast against off-white grounds.
- **Secondary (`#0F766E`) — Empirical Teal**: Represents verified evidence, passing assertions, validated citations, and finalized agent synthesis.
- **Tertiary (`#B45309`) — Archival Amber**: Encapsulates simulated, uncommitted, replayed, or in-flight agent actions requiring user scrutiny.
- **Neutral Canvas (`#F8F9FA`) — Warm Alabaster**: The primary page backdrop, complemented by clean pure white (`#FFFFFF`) card surfaces and quiet boundary borders (`#E2E8F0`).
- **Critical Diagnostics (`#BE123C`) — Resolute Crimson**: Reserved strictly for irrecoverable agent traps, failed runtime assertions, and invalidated citations.

### State & Integrity Modalities
- **Live Research**: Primary background with subtle active pulsating badge in Empirical Teal (`#0F766E`).
- **Deterministic Simulation**: Watermarked header band in Archival Amber with dotted borders (`#FDE68A` surface, `#B45309` foreground).
- **Historical Replay**: Calm slate-tinted canvas (`#F1F5F9`) with monospaced chronological scrubbers.
- **Unavailable / Unrecorded Telemetry**: Textured diagonal hatch pattern over neutral grey (`#94A3B8`) accompanied by explicit non-rendered text markers (`[NOT RECORDED]`).

## Typography

The dual typographic system pairs the scholarly warmth of **Newsreader** with the operational efficiency of **Plus Jakarta Sans**, reinforced by **JetBrains Mono** for data payloads and execution traces.

### Type Pairings & Roles
- **Newsreader (Editorial & Analytical)**: Used for research questions, hypothesis briefs, narrative answers, academic abstracts, and direct quote inspection. Uses optical size variants where available and italics for emphasized dialectics.
- **Plus Jakarta Sans (Operational & Structural)**: Powers all toolbars, table headers, breadcrumbs, metrics, controls, and schema keys. Its geometric clarity prevents eye strain in high-density runtime inspectors.
- **JetBrains Mono (Deterministic Artifacts)**: Dedicated to agent memory traces, model seed tokens, execution hashes, vector distances, and JSON payloads.

### Editorial Guidelines
- Body passages must not exceed 68 characters per line (`max-w-prose`) to preserve reading flow.
- Footnotes and bibliographic references render at `body-sm` in Plus Jakarta Sans to distinguish citation metadata from the source narrative itself.

## Layout & Spacing

The workspace uses a fluid 12-column foundation anchored by strict split-pane workbenches, ensuring multi-tiered analytical workflows can stay contextually visible simultaneously.

### Responsive Breakpoints & Viewport Adaptations
- **Desktop (>= 1280px)**: 12-column grid. Standard dual/triple pane workspace: persistent Navigation Rail (240px fixed), Analytical Canvas (flexible main column, minimum 640px), and Collapsible Citation/Runtime Inspector (400px–520px fixed).
- **Tablet (768px – 1279px)**: 8-column layout. The runtime inspector collapses into an off-canvas slide-over drawer accessible via persistent top-level tab controls.
- **Mobile (< 768px)**: 4-column single stream layout. Panes stack vertically into a tabbed segment controller (`Brief` | `Synthesis` | `Traces`). Margins decrease to `margin-mobile` (1rem).

### Layout Rules
- Workspace gutters maintain fixed vertical rhythm (`space-lg`) between content modules.
- Split-pane dividers must feature a 1px border (`#E2E8F0`) with a subtle drag handle affordance for custom analyst widths.
- Never truncate academic claims in fluid cards; allow natural vertical height expansion while bounding scroll regions within trace logs.

## Elevation & Depth

To protect legibility and intellectual calm, this design system rejects heavy drop shadows, intense glows, and high-opacity blurs. Depth is achieved strictly through **tonal layering and low-contrast perimeter lines**.

### Elevation Scale
- **Base Layer (0dp)**: Canvas ground (`#F8F9FA`). No shadow. Unbordered.
- **Surface Layer (1dp)**: Work cards, paper containers, reading panes (`#FFFFFF`). Enclosed by a 1px crisp stroke of `#E2E8F0`, paired with an ultra-soft, warm shadow: `0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.02)`.
- **Floating Controls (2dp)**: Floating action bars, citation tooltips, and popovers (`#FFFFFF`). Bordered with `#CBD5E1`, with elevation shadow: `0 4px 12px -2px rgba(15, 23, 42, 0.08), 0 2px 4px -2px rgba(15, 23, 42, 0.04)`.
- **Overlays / Dialogs (3dp)**: Telemetry drill-downs and trace snapshots. Rendered above a backdrop scrim tinted with `#0F172A` at 30% opacity with a subtle `2px` blur. Shadow: `0 12px 32px -4px rgba(15, 23, 42, 0.12)`.

### Integrity Visual Cue
Simulated or non-authoritative panes bypass soft shadows and instead display an offset outline or a dual-tone dashed border (`#D97706`), communicating that the surface represents non-canonical historical data.

## Shapes

The shape vocabulary uses **Soft (`1`)** geometry. Radii are modest and grounded, rejecting playful bubble-like contours to preserve an architectural and editorial bearing.

- **Base Elements (Inputs, Buttons, Chips, Badges)**: `0.25rem` (4px). Provides neat, precise corners that fit tabular data.
- **Cards, Trays, and Panes (`rounded-lg`)**: `0.5rem` (8px). Softens modular reading panels without breaking grid geometry.
- **Modals & Dialogs (`rounded-xl`)**: `0.75rem` (12px). Applied strictly to major modal envelopes.
- **Pill Exceptions**: Fully rounded forms (`9999px`) are restricted exclusively to status indicators, live recording pips, and categorical identity tags.

## Components

### Buttons & Interactive Controls
- **Primary Action**: Solid `#0F172A` background, `#FFFFFF` text, `0.25rem` radius, subtle hover transition to `#334155`. Height: 36px (compact density).
- **Secondary / Ghost**: Transparent fill, `#E2E8F0` border, `#0F172A` text. On hover, background fills with `#F1F5F9`.
- **Academic Synthesis Trigger**: Subtle Empirical Teal fill (`#0F766E`), white label, paired with a leading monograph icon.

### Citation & Assertion Chips
- **Verified Citation Chip**: Compact pill shape, `#F0FDFA` background, `#0D9488` border, `#0F766E` text. Includes an anchor icon and reference index (`[1]`). On click, opens the side inspector focused on the exact source span.
- **Unverified / Speculative Chip**: `#FFFBEB` background, `#D97706` dashed border, `#92400E` text.
- **Status Badges**: `label-sm` font, uppercase, 4px horizontal padding, with explicit dot status (`Live: Green`, `Replay: Slate`, `Sim: Amber`).

### Input Fields & Search Bars
- Background: `#FFFFFF`. Border: 1px `#CBD5E1`. Radius: `0.25rem`.
- Focus state: Replaces border with `#0F766E` and applies a crisp 1px ring outline (`#0F766E` at 20% opacity). Never use oversized neon glow rings.
- Query Inputs: Embedded monospaced prefix tag (`filter:`) and hotkey identifier (`⌘K`) in `JetBrains Mono`.

### Lists & Split-Pane Trace Inspects
- Alternating row zebra tints are avoided. Instead, list elements are separated by hairline borders (`#F1F5F9`).
- Hover states initiate a smooth transition to `#F8FAFC`.
- Active / Inspected Row: Features a solid 3px left border accent in `#0F766E` with `#F0FDFA` ambient background tint.

### Cards & Synthesis Panels
- Header: Typographic lockup with `headline-sm` serif, metadata right-aligned in `label-md` sans.
- Body: `body-md` in Newsreader, generous 1.625 line height, relaxed paragraph spacing (`space-md`).
- Footer: Hairline top border (`#F1F5F9`), containing token usage counts, runtime execution duration (`142ms`), and provenance hashes in `JetBrains Mono`.

### Missing Telemetry & State Modals
- If runtime data was unrecorded, fields render a light grey diagonal hash-pattern box containing `#64748B` uppercase text: `— DATA POINT UNRECORDED —`. Fields never collapse or vanish silently, ensuring transparent scientific accountability.