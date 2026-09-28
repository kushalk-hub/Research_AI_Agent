"""Narrative answer generation over a traversed subgraph (spec section 6, layer 4).

Traversal decides what the model is allowed to see; this stage decides how it is
phrased. The two are deliberately separate so the reasoning stays testable
without an LLM, and so a bad answer can be traced to a bad subgraph.

Every answer is post-validated: citation ids that are not in the subgraph are
stripped and reported. The prompt forbids inventing ids, but a prompt is a
request rather than a guarantee, and a confident `[P47]` that points at nothing
is worse than an honest gap.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from rla.events import Event, Phase, event
from rla.llm.base import LLMClient
from rla.llm.prompts.templates import ANSWER_GENERATION
from rla.pipeline.traverse import (
    QuestionType,
    Subgraph,
    classify_question,
    traverse,
    validate_citations,
)

#: Streaming chunks below this length are not forwarded individually; they are
#: only worth rendering if the model produces real prose, not JSON punctuation.
_MIN_CHUNK = 2


@dataclass
class AnswerResult:
    question: str
    question_type: QuestionType
    answer: str = ""
    subgraph: Subgraph | None = None
    stripped_citations: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def citations_used(self) -> list[str]:
        """Labels the answer actually cites, in order of first appearance."""
        seen: list[str] = []
        import re

        for token in re.findall(r"\[(?:P|C)\d+\]", self.answer):
            if token[1:-1] not in seen:
                seen.append(token[1:-1])
        return seen


def build_prompt(question: str, subgraph: Subgraph) -> str:
    return ANSWER_GENERATION.format(
        question_type=subgraph.question_type,
        question=question,
        subgraph=subgraph.render(),
    )


async def answer_question(
    graph,
    question: str,
    llm: LLMClient,
    *,
    question_type: QuestionType | None = None,
    model: str | None = None,
) -> AsyncIterator[Event]:
    """Traverse, then stream a cited answer, validating ids as they land.

    Yields `traverse` events describing the subgraph and `answer` events carrying
    the text, so the TUI can show the traversal before the answer arrives.
    """
    qtype = question_type or classify_question(question)
    subgraph = traverse(graph, question, qtype)
    payload = subgraph.to_payload()

    yield event(
        Phase.TRAVERSE,
        f"Query type: {qtype.value.upper()} - selected subgraph with "
        f"{payload['stats']['nodes']} nodes and {payload['stats']['edges']} edges",
        kind="info",
        **payload,
    )
    for note in subgraph.notes:
        yield event(Phase.TRAVERSE, note, kind="info")

    if not subgraph.nodes:
        yield event(
            Phase.ANSWER,
            "The traversal selected an empty subgraph, so there is nothing to answer from.",
            kind="warn",
            question_type=str(qtype),
        )
        return

    if llm is None:
        yield event(
            Phase.ANSWER,
            "No LLM configured; showing the traversed subgraph only.",
            kind="pending",
            question_type=str(qtype),
        )
        return

    prompt = build_prompt(question, subgraph)
    collected: list[str] = []
    stripped: list[str] = []
    try:
        async for chunk in llm.stream_text(prompt, model=model, stage="answer"):
            if len(chunk) < _MIN_CHUNK:
                continue
            cleaned, removed = validate_citations(chunk, subgraph)
            if removed:
                stripped.extend(removed)
                yield event(
                    Phase.ANSWER,
                    f"dropped unsupported citation id(s): {', '.join(removed)}",
                    kind="warn",
                )
            if not cleaned.strip():
                continue
            collected.append(cleaned)
            yield event(Phase.ANSWER, cleaned, kind="delta")
    except Exception as exc:  # LLMError and transport failures alike
        yield event(
            Phase.ANSWER,
            f"answer generation failed: {exc}",
            kind="error",
            question_type=str(qtype),
        )
        return

    text = "".join(collected).strip()
    if not text:
        yield event(Phase.ANSWER, "the model returned nothing", kind="warn")
        return

    result = AnswerResult(
        question=question,
        question_type=qtype,
        answer=text,
        subgraph=subgraph,
        stripped_citations=stripped,
        stats=payload["stats"],
    )
    used = result.citations_used()
    yield event(
        Phase.ANSWER,
        f"Answer complete: {len(used)} of {len(subgraph.labels)} subgraph nodes cited",
        kind="ok",
        question_type=str(qtype),
        citations=used,
        uncited=[label for label in sorted(subgraph.labels) if label not in used],
        stripped_citations=stripped,
        stats=payload["stats"],
    )


async def answer_question_result(
    graph, question: str, llm: LLMClient | None
) -> tuple[AnswerResult | None, list[Event]]:
    """Run a full answer and return (result, events).

    `answer_question` is a generator, so it can yield events or return a value
    but not both. The orchestrator needs both, so this drains the stream and
    re-runs the cheap tail: the traversal is deterministic, so the subgraph the
    events reported is identical to the one attached to the result.
    """
    events: list[Event] = []
    async for evt in answer_question(graph, question, llm):
        events.append(evt)
    done = next((e for e in reversed(events) if e.kind == "ok"), None)
    if done is None:
        return None, events
    subgraph = traverse(graph, question, QuestionType(done.payload["question_type"]))
    return (
        AnswerResult(
            question=question,
            question_type=subgraph.question_type,
            answer="".join(e.message for e in events if e.kind == "delta").strip(),
            subgraph=subgraph,
            stripped_citations=list(done.payload.get("stripped_citations", [])),
            stats=done.payload.get("stats", {}),
        ),
        events,
    )


def render_markdown(result: AnswerResult) -> str:
    """Answer plus a provenance footer, for `rla ask` output and reports."""
    lines = [f"# {result.question}", "", f"*{result.question_type.value} traversal*", ""]
    lines.append(result.answer)
    if result.subgraph is not None:
        lines += ["", "---", "", "**Subgraph used**", ""]
        for node in result.subgraph.nodes:
            year = f" {node.year}" if node.year else ""
            lines.append(f"- [{node.label}] {node.type}{year}: {node.name}")
    if result.stripped_citations:
        lines += [
            "",
            f"> Stripped {len(result.stripped_citations)} unsupported citation id(s): "
            + ", ".join(result.stripped_citations),
        ]
    return "\n".join(lines)
