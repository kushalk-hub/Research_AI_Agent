import { useState } from "react";
import { collectCitations } from "../lib/citations.js";
import { CitationList, CitationText } from "./Citations.jsx";
import EvidencePanel from "./EvidencePanel.jsx";

/** The cited answer and its evidence, in one two-way-linked pair (UI-09).
 *
 *  A-07 honesty: a stripped citation is reported as removed, and a cited label
 *  with no recorded evidence gets an explicit "no recorded evidence" card. The
 *  card never claims the answer, or any citation, passed a semantic check. */
export default function AnswerCard({ answer }) {
  const [selected, setSelected] = useState("");
  const [hovered, setHovered] = useState("");

  const labels = collectCitations(answer.text);
  const active = hovered || selected;
  const missing = answer.evidence.filter(
    (card) => card.missing && labels.includes(card.citation),
  );

  const onHover = (label) => setHovered(label || "");
  const onHoverEnd = () => setHovered("");
  const onSelect = (label) => setSelected((current) => (current === label ? "" : label));

  return (
    <section className="answer-card" aria-label="Answer">
      <div className="answer-head">
        <p className="answer-label">Answer</p>
        <CitationList
          labels={labels}
          selected={selected}
          active={active}
          onSelect={onSelect}
          onHover={onHover}
          onHoverEnd={onHoverEnd}
        />
      </div>

      <div className="answer-layout">
        <div className="answer-main">
          <CitationText
            text={answer.text}
            selected={selected}
            active={active}
            onSelect={onSelect}
            onHover={onHover}
            onHoverEnd={onHoverEnd}
          />

          {answer.stripped.length > 0 && (
            <p className="answer-note">
              {answer.stripped.length} citation
              {answer.stripped.length === 1 ? "" : "s"} in this answer could not be
              matched to the evidence graph and were removed.
            </p>
          )}

          {missing.length > 0 && (
            <p className="answer-note">
              {missing.length} cited label{missing.length === 1 ? " has" : "s have"} no
              recorded evidence card{missing.length === 1 ? "" : "s"}; they are marked as
              not recorded, not as checked.
            </p>
          )}
        </div>

        <EvidencePanel
          evidence={answer.evidence}
          selected={selected}
          active={active}
          onSelect={onSelect}
          onHover={onHover}
          onHoverEnd={onHoverEnd}
        />
      </div>
    </section>
  );
}
