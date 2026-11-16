import { useEffect, useRef } from "react";
import { shorten } from "../lib/format.js";

function authorLine(card) {
  if (card.kind === "concept") {
    return [card.year ? String(card.year) : "", card.aliases?.length ? card.aliases[0] : ""]
      .filter(Boolean)
      .join(" · ");
  }
  const authors =
    card.authors.length > 3
      ? `${card.authors.slice(0, 3).join(", ")} et al.`
      : card.authors.join(", ");
  return [authors, card.year ? String(card.year) : "", card.venue].filter(Boolean).join(" · ");
}

function prefersReducedMotion() {
  return Boolean(
    typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
}

/** The evidence column. Selecting a chip must move this list, not just tint a
 *  card (UI-09); `scrollIntoView({block:"nearest"})` keeps the page still and
 *  reduced-motion users get an instant jump. Cards are buttons, so `Enter`
 *  and `Space` work without a mouse. */
export default function EvidencePanel({
  evidence,
  selected,
  active,
  onSelect,
  onHover,
  onHoverEnd,
}) {
  const refs = useRef(new Map());

  useEffect(() => {
    if (!selected) return;
    const node = refs.current.get(selected);
    if (!node || typeof node.scrollIntoView !== "function") return;
    node.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [selected]);

  if (evidence.length === 0) return null;

  return (
    <section className="evidence-panel" aria-label={`Evidence (${evidence.length})`}>
      <div className="evidence-head">
        <h3 className="evidence-title">Evidence</h3>
        <span className="num">{evidence.length}</span>
      </div>

      <ol className="evidence-list">
        {evidence.map((card) => {
          const isSelected = selected === card.citation;
          const isActive = active === card.citation;
          return (
            <li key={card.citation}>
              <button
                type="button"
                ref={(node) => {
                  if (node) refs.current.set(card.citation, node);
                  else refs.current.delete(card.citation);
                }}
                className="evidence-item"
                data-citation={card.citation}
                data-kind={card.kind}
                data-missing={card.missing ? "true" : undefined}
                data-active={isActive ? "true" : undefined}
                aria-pressed={isSelected}
                aria-label={`Evidence [${card.citation}]: ${card.title}`}
                onClick={() => onSelect(card.citation)}
                onMouseEnter={() => onHover(card.citation)}
                onMouseLeave={() => onHoverEnd()}
                onFocus={() => onHover(card.citation)}
                onBlur={() => onHoverEnd()}
              >
                <span className="evidence-cite">[{card.citation}]</span>
                <span className="evidence-body">
                  <span className="evidence-name">{card.title}</span>
                  {authorLine(card) && (
                    <span className="evidence-meta">{authorLine(card)}</span>
                  )}
                  {card.abstract && (
                    <span className="evidence-abstract">{shorten(card.abstract, 200)}</span>
                  )}
                </span>
              </button>
              {card.url && (
                <a
                  className="evidence-link"
                  href={card.url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Open source
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
