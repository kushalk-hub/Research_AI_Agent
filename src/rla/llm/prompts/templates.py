"""Prompt templates.

Each template is a module-level constant so it can be hashed into the LLM cache
key: editing a prompt invalidates exactly the calls that used it, and nothing
else (see PLAN.md section 4).
"""

from __future__ import annotations

import hashlib

QUERY_EXPANSION = """\
You expand a research project title into search queries for an academic paper search API.

Title: {title}

Produce {n} queries that together cover the topic's main sub-areas. Rules:
- Each query must be a short keyword phrase, not a full question.
- Vary terminology: include at least one synonym or acronym variant.
- Include at least one query aimed at the *evaluation/benchmark* angle and one at
  the *limitations/open problems* angle.
- Do not invent papers. Only output queries.

Return JSON: {{"queries": ["...", "..."]}}"""


PAPER_EXTRACTION = """\
You extract structured research knowledge from ONE paper. Use only what the text
below supports. If a field is not supported by the text, leave it empty rather
than guessing.

--- METADATA ---
Title: {title}
Year: {year}
Venue: {venue}

--- {source_kind} ---
{body}

--- TASK ---
Return JSON with these fields:
- "summary": 1-2 sentences on what the paper does.
- "concepts": list of methods/techniques/ideas the paper uses or introduces. Each
  entry: {{"name": canonical name, "description": one clause on what it is,
  "role": "introduces" | "uses"}}. Prefer well-known canonical names
  (e.g. "graph attention networks", not "our novel module").
- "builds_on": prior methods or papers this work extends, named explicitly.
- "relation": how this work relates to the most important thing it builds on.
  One of: "extends", "replaces", "combines", "applies-to-new-domain", "critiques".
- "relation_target": the specific method/concept the relation applies to.
- "stated_limitation": a limit on THIS paper's own method, in its own words.
  Only use a sentence that concedes something this work cannot do: a stated
  limitations or future-work section, a "however", "we do not", "fails to",
  "is limited to", or a scope caveat.
  Do NOT report a limitation of PRIOR work that this paper fixes. "We address the
  limitations of existing methods by..." describes someone else's problem, and
  the answer to it is this paper's contribution, not its limitation. Leave that
  field "" in that case.
  If the text states no such limit, return "" - do not infer one.
- "inferred_open_problem": a concrete unsolved problem this paper leaves open,
  derived from its own limitation. Return "" if there is nothing concrete.

Return JSON only."""


CONCEPT_RESOLUTION = """\
You decide whether two research concept names refer to the same thing.

Concept A: {a}
  Description: {a_desc}

Concept B: {b}
  Description: {b_desc}

Answer "same" only if one is an alias, abbreviation, or renaming of the other.
Answer "different" if they are related but distinct (e.g. a method versus the task
it is applied to, or two competing methods in the same family).

Return JSON: {{"verdict": "same" | "different", "confidence": 0.0-1.0,
"canonical": "preferred name"}}"""


ANSWER_GENERATION = """\
You answer a research question using ONLY the graph subgraph provided. Every claim
must be attributable to a node in the subgraph.

Question ({question_type}): {question}

--- SUBGRAPH ---
{subgraph}

--- RULES ---
- Cite with bracketed ids taken verbatim from the subgraph, e.g. [P12] or [C4].
- Never invent a citation id that is not in the subgraph.
- If the subgraph does not contain the answer, say so explicitly and name what is
  missing. Do not fill the gap with outside knowledge.
- Follow the narrative structure implied by the question type:
  lineage -> ordered chain with years; comparison -> shared ancestry then divergence;
  gaps -> per-paper stated gaps, then synthesized cross-paper open problems;
  full report -> what has been done (chronological) then what remains open.
- Mark any inference you make beyond the subgraph with "(inferred)".

Return markdown only."""


GAP_CLUSTERING = """\
You cluster the stated limitations of a research corpus into aggregate gaps.

--- STATED LIMITATIONS ---
{limitations}

Group limitations that describe the SAME unresolved problem, even when worded
differently and even when they come from different papers. Do not group
limitations that merely sound similar but are technically distinct.

Return JSON:
{{"gaps": [{{"theme": "short name", "summary": "one sentence", "paper_ids": ["P1","P7"]}}]}}"""


def prompt_hash(*prompts: str) -> str:
    """Cache-key fragment that changes whenever any prompt text changes."""
    joined = "\x1f".join(prompts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
