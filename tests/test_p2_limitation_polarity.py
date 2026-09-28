"""P2 gate: the stated_limitation polarity rule.

The failure this file exists to prevent is specific and expensive. An abstract
saying "we address the limitations of existing methods by using X" was recorded
as this paper's own limitation, which inverts its meaning. P6 then clusters
stated gaps, and a gap the paper *closed* reappears as an open problem. The
error is invisible in aggregate (a plausible-looking string) and only surfaces
as a nonsensical research report.
"""

from __future__ import annotations

import pytest

from rla.models import Paper
from rla.pipeline.extraction import (
    PaperFacts,
    build_prompt,
    is_prior_work_limitation,
)

#: A limitation this paper states about itself. Must survive.
OWN_LIMITS = [
    "However, our method fails to scale beyond 50 agents.",
    "We do not evaluate on images, only graphs.",
    "The approach is limited to undirected graphs.",
    "Our method struggles when the graph is dynamic.",
    "We leave multi-GPU training to future work.",
    "This is only a preliminary study.",
]

#: Prior work's problem that this paper fixes. Must be rejected.
PRIOR_LIMITS = [
    "HC-STGRL incorporates built-in mechanisms to prevent major arterial roads "
    "from starving adjacent intersections, thereby overcoming a well-documented "
    "limitation of conventional throughput-maximizing control.",
    "We address the limitations of existing methods by using a graph attention layer.",
    "Our framework overcomes the problem of high variance in prior RL algorithms.",
    "It alleviates the drawbacks of previous convolution-based approaches.",
    "We resolve the instability of conventional message passing.",
    "The method tackles the weak expressiveness of prior GNNs.",
]


@pytest.mark.parametrize("text", OWN_LIMITS)
def test_a_paper_own_limitation_is_kept(text):
    assert not is_prior_work_limitation(text)


@pytest.mark.parametrize("text", PRIOR_LIMITS)
def test_a_prior_work_limitation_is_rejected(text):
    assert is_prior_work_limitation(text)


def test_empty_text_is_not_a_prior_work_limitation():
    assert not is_prior_work_limitation("")
    assert not is_prior_work_limitation("   ")


def test_a_bare_verb_without_a_prior_work_reference_is_not_rejected():
    """Narrow on purpose: 'mitigate' alone is ambiguous, so we do not fire."""
    assert not is_prior_work_limitation("We mitigate the sparsity of the graph.")


def test_the_conclusion_is_policed_in_the_extraction():
    paper = Paper(id="p1", title="T", year=2024, abstract="body")
    facts = PaperFacts(
        stated_limitation=PRIOR_LIMITS[0],
        inferred_open_problem="Sparse graphs remain hard.",
    )
    extraction = facts.to_extraction(paper)
    assert extraction.stated_limitation == ""
    # The dependent field must go too, or P6 sees a problem with no stated cause.
    assert extraction.inferred_open_problem == ""


def test_a_kept_limitation_keeps_its_open_problem():
    paper = Paper(id="p1", title="T", year=2024, abstract="body")
    facts = PaperFacts(
        stated_limitation=OWN_LIMITS[0],
        inferred_open_problem="Scaling past 50 agents is open.",
    )
    extraction = facts.to_extraction(paper)
    assert extraction.stated_limitation == OWN_LIMITS[0]
    assert extraction.inferred_open_problem == "Scaling past 50 agents is open."


def test_an_open_problem_without_a_limitation_is_dropped():
    """A problem inferred with no stated basis is speculation, so it is cut."""
    paper = Paper(id="p1", title="T", year=2024, abstract="body")
    facts = PaperFacts(stated_limitation="", inferred_open_problem="Someone should try X.")
    assert facts.to_extraction(paper).inferred_open_problem == ""


def test_the_prompt_states_the_polarity_rule():
    """The rule must be in the prompt, since the filter is only a backstop."""
    prompt = build_prompt(Paper(id="p1", title="T", year=2024, abstract="body"))
    lowered = prompt.lower()
    assert "prior work" in lowered
    assert "leave that" in lowered or 'return ""' in lowered


def test_the_prompt_warns_against_inverting_prior_work():
    prompt = build_prompt(Paper(id="p1", title="T", year=2024, abstract="body")).lower()
    assert "limitations of existing" in prompt
    assert "someone else" in prompt or "not this paper" in prompt


def test_prompt_mentions_this_papers_own_limit():
    prompt = build_prompt(Paper(id="p1", title="T", year=2024, abstract="body")).lower()
    assert "this paper's own" in prompt or "this paper itself" in prompt
