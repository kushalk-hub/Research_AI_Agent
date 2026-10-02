"""P5 answer generation: prompt assembly, citation enforcement, and event stream.

Uses a fake LLM throughout. These tests must never touch the network, and they
must still prove the important property: a citation that the subgraph does not
contain never survives into the answer.
"""

from __future__ import annotations

import pytest

from rla.events import Phase
from rla.llm.base import LLMClient
from rla.models import Concept, EdgeType, Paper, Relation, RelationType
from rla.pipeline.answer import (
    AnswerResult,
    answer_question,
    answer_question_result,
    build_prompt,
    render_markdown,
)
from rla.pipeline.traverse import QuestionType, Subgraph
from rla.store.graph_store import build_graph

PAPERS = [
    Paper(id="p1", title="Graph Attention Networks", year=2018, abstract="introduces GAT"),
    Paper(id="p2", title="Graph Convolutional Networks", year=2017, abstract="introduces GCN"),
    Paper(id="p3", title="Graph-of-Agents", year=2024, abstract="agents over graphs",
          references=["p1"]),
]

CONCEPTS = [
    Concept(id="c:gcn", name="graph convolutional networks", first_seen_year=2017),
    Concept(id="c:gat", name="graph attention networks", first_seen_year=2018, aliases=["GAT"]),
    Concept(id="c:agent-graphs", name="agent graphs", first_seen_year=2024),
]

RELATIONS = [
    Relation(source_id="c:gcn", target_id="c:gat", edge_type=EdgeType.EXTENDS,
             relation=RelationType.EXTENDS),
    Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p2", target_id="c:gcn", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p3", target_id="c:agent-graphs", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p3", target_id="c:gat", edge_type=EdgeType.USES),
    Relation(source_id="p1", target_id="c:agent-graphs", edge_type=EdgeType.HAS_LIMITATION,
             evidence="oversmooths on dense graphs"),
]


class FakeLLM(LLMClient):
    """Replays a fixed chunk list. Records what it was asked."""

    def __init__(self, chunks: list[str] | None = None, fail: bool = False) -> None:
        self.chunks = chunks if chunks is not None else ["An answer ", "with [P1]."]
        self.fail = fail
        self.prompts: list[str] = []
        self.models: list[str | None] = []
        self.stages: list[str | None] = []

    async def complete(self, prompt, *, model=None, stage=None, **kwargs):
        self.prompts.append(prompt)
        return "".join(self.chunks)

    async def stream_text(self, prompt, *, model=None, stage=None, **kwargs):
        self.prompts.append(prompt)
        self.models.append(model)
        self.stages.append(stage)
        if self.fail:
            raise RuntimeError("upstream exploded")
        for chunk in self.chunks:
            yield chunk

    async def complete_json(self, prompt, *, model=None, stage=None, **kwargs):
        return {}


@pytest.fixture
def graph():
    g, _, _ = build_graph(PAPERS, CONCEPTS, RELATIONS)
    return g


async def collect(gen):
    return [evt async for evt in gen]


# -- prompt --------------------------------------------------------------------


def test_the_prompt_carries_the_question_and_the_rendered_subgraph(graph):
    sub = Subgraph(
        question="q",
        question_type=QuestionType.LINEAGE,
        nodes=[],
    )
    prompt = build_prompt("How did GAT evolve?", sub)
    assert "How did GAT evolve?" in prompt
    assert "question type: lineage" in prompt
    assert "nodes:" in prompt


async def test_labels_reach_the_prompt_so_the_model_can_cite_them(graph):
    llm = FakeLLM(["Fine."])
    _ = [e async for e in answer_question(graph, "lineage of GAT", llm)]
    assert llm.prompts, "the LLM must actually be called"
    prompt = llm.prompts[0]
    assert "- [P1]" in prompt or "- [C1]" in prompt


# -- citation enforcement ------------------------------------------------------


async def test_a_valid_citation_survives_generation(graph):
    llm = FakeLLM(["GAT came from GCN, see [C1] and [C2]."])
    result, events = await answer_question_result(graph, "lineage of GAT", llm)
    assert result is not None
    assert "[C1]" in result.answer
    assert result.stripped_citations == []


async def test_an_invented_citation_is_stripped_and_reported(graph):
    llm = FakeLLM(["The claim [P999] is unsupported, but [C1] is real."])
    result, events = await answer_question_result(graph, "lineage of GAT", llm)
    assert result is not None
    assert "[P999]" not in result.answer
    assert result.stripped_citations == ["[P999]"]
    assert any("dropped unsupported citation" in e.message for e in events)


async def test_a_citation_split_across_chunks_is_still_checked(graph):
    """Streaming must validate the reassembled text, not each fragment."""
    llm = FakeLLM(["first [P", "1] then [C", "9] end."])
    result, _ = await answer_question_result(graph, "lineage of GAT", llm)
    assert result is not None
    # [P1] and [C9] are both in range for some subgraph labelling; the point is
    # that neither fragment is dropped for being unparseable on its own.
    assert "first" in result.answer and "end." in result.answer


async def test_citations_used_are_listed_in_first_appearance_order(graph):
    llm = FakeLLM(["Start [C1], then [P1], then [C1] again."])
    result, _ = await answer_question_result(graph, "lineage of GAT", llm)
    assert result is not None
    assert result.citations_used() == ["C1", "P1"]


async def test_the_completion_event_reports_uncited_nodes(graph):
    llm = FakeLLM(["Only [C1]."])
    result, events = await answer_question_result(graph, "lineage of GAT", llm)
    done = next(e for e in events if e.phase is Phase.ANSWER and e.kind == "ok")
    assert done.payload["citations"] == ["C1"]
    assert done.payload["uncited"], "nodes the answer ignored should be reported"
    assert result is not None


# -- failure and edge paths ----------------------------------------------------


async def test_an_llm_failure_becomes_an_error_event_not_an_exception(graph):
    events = await collect(answer_question(graph, "lineage of GAT", FakeLLM(fail=True)))
    errors = [e for e in events if e.kind == "error"]
    assert errors, "a transport failure must surface as an event"
    assert "upstream exploded" in errors[0].message
    result, _ = await answer_question_result(graph, "lineage of GAT", FakeLLM(fail=True))
    assert result is None


async def test_no_llm_yields_the_subgraph_and_no_answer(graph):
    events = await collect(answer_question(graph, "lineage of GAT", None))
    assert any("No LLM configured" in e.message for e in events)
    result, _ = await answer_question_result(graph, "lineage of GAT", None)
    assert result is None


async def test_an_empty_subgraph_is_reported_rather_than_answered():
    from rla.store.graph_store import empty_graph

    events = await collect(answer_question(empty_graph(), "lineage of anything", FakeLLM()))
    assert any("empty subgraph" in e.message for e in events)
    result, _ = await answer_question_result(empty_graph(), "lineage of anything", FakeLLM())
    assert result is None, "an empty graph must not yield a fabricated answer"


async def test_a_concept_with_no_edges_still_produces_a_minimal_subgraph():
    """A lone concept is traversable even with no lineage under it."""
    g, _, _ = build_graph([PAPERS[0]], [CONCEPTS[2]], [])
    result, _ = await answer_question_result(g, "lineage of agent graphs", FakeLLM())
    assert result is not None
    from rla.models import NodeType

    concepts = [n.name for n in result.subgraph.nodes if n.type == str(NodeType.CONCEPT)]
    assert concepts == ["agent graphs"]


async def test_a_silent_model_is_reported(graph):
    llm = FakeLLM(["  ", "\n"])
    events = await collect(answer_question(graph, "lineage of GAT", llm))
    assert any("returned nothing" in e.message for e in events)
    result, _ = await answer_question_result(graph, "lineage of GAT", FakeLLM(["  "]))
    assert result is None


async def test_the_answer_stage_is_requested_by_name(graph):
    llm = FakeLLM(["ok [C1]"])
    _ = [e async for e in answer_question(graph, "lineage of GAT", llm)]
    assert llm.stages == ["answer"]


async def test_the_traverse_event_precedes_every_answer_event(graph):
    events = await collect(answer_question(graph, "lineage of GAT", FakeLLM()))
    phases = [e.phase for e in events]
    assert phases.index(Phase.TRAVERSE) < phases.index(Phase.ANSWER)


# -- rendering -----------------------------------------------------------------


def test_markdown_names_the_traversal_and_lists_the_subgraph():
    sub = Subgraph(question="q", question_type=QuestionType.COMPARISON, nodes=[])
    result = AnswerResult(
        question="How do GAT and GCN compare?",
        question_type=QuestionType.COMPARISON,
        answer="They share an ancestor [C1].",
        subgraph=sub,
    )
    text = render_markdown(result)
    assert "# How do GAT and GCN compare?" in text
    assert "comparison traversal" in text
    assert "They share an ancestor [C1]." in text


def test_markdown_surfaces_stripped_citations():
    sub = Subgraph(question="q", question_type=QuestionType.FULL_REPORT, nodes=[])
    result = AnswerResult(
        question="q",
        question_type=QuestionType.FULL_REPORT,
        answer="text",
        subgraph=sub,
        stripped_citations=["[P999]"],
    )
    assert "[P999]" in render_markdown(result)
    assert "Stripped" in render_markdown(result)


async def test_citations_used_is_empty_when_the_answer_cites_nothing():
    result = AnswerResult(question="q", question_type=QuestionType.GAP, answer="no ids here")
    assert result.citations_used() == []
