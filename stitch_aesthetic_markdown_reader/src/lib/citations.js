/** Citation labels (`[P3]`, `[C1]`) and the evidence they point at.
 *
 *  Two recorded shapes have to resolve to the same card:
 *  - RLA puts `{citation, paper}` and, since slice 5, `{citation, concept}`
 *    on `research_answer.evidence`;
 *  - FODS puts `{citation, paper, ...}` on `evidence_selected.evidence`;
 *  - old RLA logs have no concept evidence at all, but their `traverse`
 *    progress event already carries every subgraph node.
 *
 *  Everything here is pure: the components decide how to render, this module
 *  decides what a citation *means*. If a cited label has no recorded evidence
 *  it still gets an explicit "not recorded" card rather than a dead chip.
 */

const LABEL = /^[PC]\d+$/;

/** `"[P1]"`, `"P1"`, `" p1 "` -> `"P1"`; anything else -> `""`. */
export function normaliseLabel(raw) {
  const value = String(raw ?? "")
    .trim()
    .replace(/^\[/, "")
    .replace(/\]$/, "")
    .trim()
    .toUpperCase();
  return LABEL.test(value) ? value : "";
}

function citeGroup(inner) {
  const parts = inner
    .split(",")
    .map((part) => normaliseLabel(part))
    .filter(Boolean);
  return parts;
}

/** Split answer text into literal text and citation-bearing groups.
 *
 *  `[P2, C4]` yields one group with two labels; `[not a cite]` stays text.
 *  Only `P#`/`C#` tokens are ever removed from the literal text, so the reader
 *  always sees the recorded prose unchanged. */
export function parseCitations(text = "") {
  const source = String(text);
  const segments = [];
  let cursor = 0;
  for (const match of source.matchAll(/\[([^\]]*)\]/g)) {
    const labels = citeGroup(match[1]);
    if (labels.length === 0) continue;
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ type: "text", text: source.slice(cursor, start) });
    }
    segments.push({ type: "cite", labels, raw: match[0] });
    cursor = start + match[0].length;
  }
  if (cursor < source.length) {
    segments.push({ type: "text", text: source.slice(cursor) });
  }
  return segments;
}

/** Distinct labels in order of first appearance. */
export function collectCitations(text = "") {
  const seen = [];
  for (const segment of parseCitations(text)) {
    if (segment.type !== "cite") continue;
    for (const label of segment.labels) {
      if (!seen.includes(label)) seen.push(label);
    }
  }
  return seen;
}

/** Only `http(s)` links are ever rendered (no `javascript:`, no `data:`). */
export function safeHttpUrl(raw) {
  const value = String(raw ?? "").trim();
  if (!rss(value)) return "";
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function rss(value) {
  return value.startsWith("http://") || value.startsWith("https://");
}

function text(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function paperEntry(label, paper = {}) {
  return {
    citation: label,
    kind: "paper",
    missing: false,
    title: text(paper.title) || "Untitled paper",
    year: number(paper.year),
    authors: Array.isArray(paper.authors) ? paper.authors.map(text).filter(Boolean) : [],
    venue: text(paper.venue),
    abstract: text(paper.abstract),
    doi: text(paper.doi),
    url: safeHttpUrl(paper.url),
  };
}

function conceptEntry(label, concept = {}) {
  return {
    citation: label,
    kind: "concept",
    missing: false,
    title: text(concept.name) || "Unnamed concept",
    year: number(concept.year),
    authors: [],
    venue: "",
    abstract: text(concept.description),
    doi: "",
    url: "",
    aliases: Array.isArray(concept.aliases) ? concept.aliases.map(text).filter(Boolean) : [],
  };
}

function missingEntry(label) {
  return {
    citation: label,
    kind: label.startsWith("C") ? "concept" : "paper",
    missing: true,
    title: `No recorded evidence for [${label}]`,
    year: null,
    authors: [],
    venue: "",
    abstract:
      "The answer cites this label, but the run did not record an evidence card for it.",
    doi: "",
    url: "",
  };
}

function mergeInto(map, entry) {
  if (!entry.citation) return;
  // Later records are richer (research_answer follows evidence_selected), so
  // they replace an earlier card for the same label.
  map.set(entry.citation, entry);
}

/** Every evidence card the run recorded, sorted `P1..` then `C1..`. */
export function evidenceFrom(events = []) {
  const byLabel = new Map();
  for (const event of events) {
    const payload = event?.payload || {};
    if (event?.kind === "evidence_selected" && Array.isArray(payload.evidence)) {
      for (const item of payload.evidence) {
        const label = normaliseLabel(item?.citation);
        if (!label) continue;
        mergeInto(byLabel, paperEntry(label, item.paper || {}));
      }
    }
    if (event?.kind === "research_answer" && Array.isArray(payload.evidence)) {
      for (const item of payload.evidence) {
        const label = normaliseLabel(item?.citation);
        if (!label) continue;
        if (item.paper) mergeInto(byLabel, paperEntry(label, item.paper));
        else if (item.concept) mergeInto(byLabel, conceptEntry(label, item.concept));
      }
    }
    // Old RLA logs: the subgraph nodes are already in the stream, before the
    // answer. Paper nodes also arrive here; concept nodes only here.
    if (payload.phase === "traverse" && Array.isArray(payload.stage_payload?.nodes)) {
      for (const node of payload.stage_payload.nodes) {
        const label = normaliseLabel(node?.label);
        if (!label) continue;
        const type = text(node.type).toLowerCase();
        if (type === "concept") {
          mergeInto(
            byLabel,
            conceptEntry(label, {
              name: node.name,
              year: node.year,
              aliases: node.extra?.aliases,
              description: node.extra?.description,
            }),
          );
        } else if (type === "paper") {
          mergeInto(byLabel, paperEntry(label, { title: node.name, year: node.year }));
        }
      }
    }
  }
  return [...byLabel.values()].sort(compareCards);
}

/** Evidence cards for a recorded answer, including honest placeholders. */
export function answerEvidence(answer, events = []) {
  const byLabel = new Map(evidenceFrom(events).map((card) => [card.citation, card]));
  for (const label of collectCitations(answer?.text || "")) {
    if (!byLabel.has(label)) byLabel.set(label, missingEntry(label));
  }
  return [...byLabel.values()].sort(compareCards);
}

function compareCards(left, right) {
  return rank(left.citation) - rank(right.citation);
}

function rank(label) {
  const match = /^([PC])(\d+)$/.exec(label || "");
  if (!match) return Number.MAX_SAFE_INTEGER;
  const family = match[1] === "P" ? 0 : 1_000_000;
  return family + Number(match[2]);
}
