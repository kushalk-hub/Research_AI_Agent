import { Fragment } from "react";
import { parseCitations } from "../lib/citations.js";

/** One clickable citation. The visible text stays the recorded `[P#]`/`[C#]`
 *  token; the accessible name says what activating it does. */
export function CitationChip({
  label,
  selected = false,
  active = false,
  onSelect,
  onHover,
  onHoverEnd,
}) {
  return (
    <button
      type="button"
      className="cite-chip"
      data-citation={label}
      data-active={active ? "true" : undefined}
      aria-pressed={selected}
      aria-label={`Select evidence for [${label}]`}
      title={`Show evidence for [${label}]`}
      onClick={() => onSelect?.(label)}
      onMouseEnter={() => onHover?.(label)}
      onMouseLeave={() => onHoverEnd?.()}
      onFocus={() => onHover?.(label)}
      onBlur={() => onHoverEnd?.()}
    >
      [{label}]
    </button>
  );
}

/** Answer prose with every recorded citation turned into a chip.
 *
 *  Nothing is injected as HTML: the text arrives as React text nodes, and only
 *  tokens that match `[P#]`/`[C#]` leave the literal stream. */
export function CitationText({ text, selected, active, onSelect, onHover, onHoverEnd }) {
  const segments = parseCitations(text);
  return (
    <p className="answer-text">
      {segments.map((segment, index) =>
        segment.type === "text" ? (
          <Fragment key={`text-${index}`}>{segment.text}</Fragment>
        ) : (
          <Fragment key={`cite-${index}`}>
            {segment.labels.map((label, position) => (
              <CitationChip
                key={`${label}-${position}`}
                label={label}
                selected={selected === label}
                active={active === label}
                onSelect={onSelect}
                onHover={onHover}
                onHoverEnd={onHoverEnd}
              />
            ))}
          </Fragment>
        ),
      )}
    </p>
  );
}

/** The scan line above the prose: one chip per distinct citation, in the order
 *  the answer first uses them. */
export function CitationList({ labels, selected, active, onSelect, onHover, onHoverEnd }) {
  if (labels.length === 0) return null;
  return (
    <ul className="cite-row" aria-label="Citations in this answer">
      {labels.map((label) => (
        <li key={label}>
          <CitationChip
            label={label}
            selected={selected === label}
            active={active === label}
            onSelect={onSelect}
            onHover={onHover}
            onHoverEnd={onHoverEnd}
          />
        </li>
      ))}
    </ul>
  );
}
