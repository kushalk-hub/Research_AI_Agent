"""Concept and limitation extraction, one structured LLM call per paper.

Spec §2 layer 2. Three decisions are worth stating up front:

- **The model is never asked for an id.** `paper_id` and `paper_hash` are
  stamped from the corpus we already hold, so a hallucinated or reordered id
  cannot attach a summary to the wrong paper.
- **Empty means empty.** The prompt asks for a stated limitation only when the
  paper actually states one. Inventing plausible limitations is worse than
  having none, because P6 aggregates them into "gaps" that never existed.
- **Resume is a store, not a retry.** Successful extractions are appended to
  disk as they land, keyed by paper content hash, so an interrupted run picks
  up exactly where it stopped without re-calling the model.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from rla.events import Event, Phase, event
from rla.llm.base import LLMClient, LLMError
from rla.llm.prompts.templates import PAPER_EXTRACTION
from rla.llm.retry import BudgetExhausted
from rla.models import ConceptMention, Extraction, Paper, RelationType
from rla.store.cache import CostTracker
from rla.store.extraction_store import ExtractionStore

STAGE = "extraction"
#: Abstracts are the MVP body. Truncating bounds cost without losing the point.
MAX_BODY_CHARS = 4000
#: Identical failures are reported once, then counted. A hundred copies of the
#: same 401 teaches nobody anything and buries the rest of the run.
MAX_REPORTED_PER_REASON = 3
#: Credentials do not become valid by trying again on the next 99 papers.
_AUTH_MARKERS = ("401", "403", "unauthenticated", "permission denied", "api key", "credential")

#: Verbs whose subject is someone else's work, so the paper is the fix rather
#: than the casualty: "we address the limitations of X", "overcoming a limitation
#: of conventional Y". Inflections matter, since the model writes whichever form
#: the sentence needs: the real extraction said "overcoming", not "overcomes".
_PRIOR_WORK_VERBS = (
    "address",
    "overcome",
    "resolve",
    "tackle",
    "alleviat",
    "mitigat",
    "addressing",
    "overcoming",
    "resolving",
    "tackling",
    "alleviating",
    "mitigating",
)

#: References to work this paper is reacting to, which give the sentence a
#: subject other than the paper itself.
_PRIOR_WORK_SUBJECTS = (
    "existing",
    "previous",
    "prior",
    "conventional",
    "traditional",
    "current",
    "earlier",
    "limitation of",
    "limitations of",
    "problem of",
    "problems of",
    "weakness",
    "weaknesses",
    "drawback",
    "drawbacks",
    "shortcoming",
)


def is_prior_work_limitation(text: str) -> bool:
    """True when a claimed limitation belongs to prior work, not this paper.

    Deliberately narrow: it only fires when an explicit "fix prior work" verb
    appears in the same clause as a reference to other methods. Clearing a real
    limitation is a false negative here, which costs a gap; accepting a solved
    problem as an open one is a false positive, which is worse.
    """
    lowered = " ".join(text.split()).lower()
    if not lowered:
        return False
    if not any(verb in lowered for verb in _PRIOR_WORK_VERBS):
        return False
    return any(subject in lowered for subject in _PRIOR_WORK_SUBJECTS)


class PaperFacts(BaseModel):
    """Exactly the fields the model fills in. Ids and hashes are ours to stamp."""

    summary: str = ""
    concepts: list[ConceptMention] = Field(default_factory=list)
    builds_on: list[str] = Field(default_factory=list)
    relation: RelationType | None = None
    relation_target: str = ""
    stated_limitation: str = ""
    inferred_open_problem: str = ""

    def to_extraction(self, paper: Paper) -> Extraction:
        concepts = [c for c in self.concepts if c.name]
        limitation = self.stated_limitation.strip()
        if is_prior_work_limitation(limitation):
            # Keeping it would make P6 report as an open gap something this paper
            # explicitly solved.
            limitation = ""
        extraction = Extraction(
            paper_id=paper.id,
            paper_hash=paper.ensure_hash(),
            summary=self.summary.strip(),
            concepts=concepts,
            builds_on=[b.strip() for b in self.builds_on if b and b.strip()],
            relation=self.relation,
            relation_target=self.relation_target.strip(),
            stated_limitation=limitation,
            inferred_open_problem=(
                ""
                if not limitation
                else self.inferred_open_problem.strip()
            ),
        )
        extraction.ensure_hash()
        return extraction


@dataclass
class ExtractionReport:
    total: int = 0
    reused: int = 0
    extracted: int = 0
    skipped: int = 0
    failed: int = 0
    failures: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "reused": self.reused,
            "extracted": self.extracted,
            "skipped": self.skipped,
            "failed": self.failed,
            "parse_rate": self.extracted / self.total if self.total else 0.0,
            "failures": self.failures,
        }


def _reason(error: Exception, limit: int = 140) -> str:
    text = " ".join(str(error).split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _is_auth_error(error: Exception) -> bool:
    """Bad credentials are systemic: every remaining paper will fail the same way."""
    text = str(error).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _is_budget_error(error: Exception) -> bool:
    """A spent allowance is systemic too: every remaining paper will fail the same.

    Both the local per-run budget and the provider's daily ceiling end the batch
    early. The difference is which one to tell the user about.
    """
    if isinstance(error, BudgetExhausted):
        return True
    text = str(error).lower()
    return "daily free-tier quota" in text or "daily quota" in text


def build_prompt(paper: Paper, source_kind: str = "ABSTRACT") -> str:
    body = " ".join((paper.abstract or "").split())
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + " [...]"
    return PAPER_EXTRACTION.format(
        title=paper.title,
        year=paper.year if paper.year else "unknown",
        venue=paper.venue or "unknown",
        source_kind=source_kind,
        body=body or "(no text available)",
    )


async def _extract_one(
    paper: Paper,
    llm: LLMClient,
    semaphore: asyncio.Semaphore,
    source_kind: str,
    model: str = "",
) -> tuple[Paper, Extraction | None, Exception | None]:
    async with semaphore:
        try:
            # `model` must reach the call. The audit found this parameter was
            # accepted and then used only to label the cost report, so the
            # configured model never reached the provider.
            facts = await llm.generate_structured(
                build_prompt(paper, source_kind), PaperFacts, stage=STAGE, model=model or None
            )
        except (LLMError, ValueError) as exc:
            return paper, None, exc
    return paper, facts.to_extraction(paper), None


async def extract_papers(
    papers: list[Paper],
    llm: LLMClient,
    store: ExtractionStore,
    concurrency: int = 4,
    source_kind: str = "ABSTRACT",
    tracker: CostTracker | None = None,
    model: str = "",
) -> AsyncIterator[Event]:
    """Extract knowledge from every paper, reusing stored results where valid."""
    report = ExtractionReport(total=len(papers))

    todo: list[Paper] = []
    for paper in papers:
        cached = store.get(paper.ensure_hash())
        if cached is not None:
            report.reused += 1
            continue
        todo.append(paper)

    yield event(
        Phase.EXTRACT,
        f"Extracting {len(todo)} papers ({report.reused} already extracted)",
        pending=len(todo),
        reused=report.reused,
    )

    semaphore = asyncio.Semaphore(concurrency)
    # as_completed, not gather: a 100-paper run should report progress as it
    # happens rather than going quiet for two minutes and then dumping a total.
    futures = [
        asyncio.ensure_future(_extract_one(paper, llm, semaphore, source_kind, model))
        for paper in todo
    ]
    done = 0
    reason_counts: dict[str, int] = {}
    auth_failure: str | None = None
    budget_failure: str | None = None
    try:
        for future in asyncio.as_completed(futures):
            paper, extraction, error = await future
            done += 1
            if error is not None:
                report.failed += 1
                reason = _reason(error)
                report.failures[paper.id] = reason
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if reason_counts[reason] <= MAX_REPORTED_PER_REASON:
                    yield event(
                        Phase.EXTRACT,
                        f"failed on {paper.id[:24]}: {reason}",
                        kind="error",
                        paper_id=paper.id,
                    )
                if _is_auth_error(error):
                    auth_failure = reason
                    break
                # A spent daily allowance or request budget will fail every
                # remaining paper identically, so stop instead of grinding
                # through the rest of the batch to collect the same error.
                if _is_budget_error(error):
                    budget_failure = reason
                    break
            elif extraction is not None:
                store.add(extraction)
                report.extracted += 1
                yield event(
                    Phase.EXTRACT,
                    f"{done}/{len(todo)} {paper.id[:24]}: {len(extraction.concepts)} concepts"
                    + (
                        f", limitation: {extraction.stated_limitation[:60]}"
                        if extraction.stated_limitation
                        else ""
                    ),
                    kind="ok",
                    paper_id=paper.id,
                    concepts=len(extraction.concepts),
                    has_limitation=bool(extraction.stated_limitation),
                )
            else:  # pragma: no cover - defensive
                report.failed += 1
                report.failures[paper.id] = "no result"
    finally:
        # A consumer that stops early (Ctrl-C, a closed stream) must not leave
        # in-flight requests running against a provider nobody is listening to.
        for future in futures:
            if not future.done():
                future.cancel()

    for reason, count in reason_counts.items():
        if count > MAX_REPORTED_PER_REASON:
            yield event(
                Phase.EXTRACT,
                f"{count} papers failed with the same error: {reason}",
                kind="error",
                count=count,
            )

    if auth_failure is not None:
        yield event(
            Phase.EXTRACT,
            f"stopping after {report.extracted} extracted: the LLM rejected the request "
            f"({auth_failure}). Check `rla doctor --llm`; the remaining "
            f"{len(todo) - done} papers were not attempted",
            kind="error",
            extracted=report.extracted,
            not_attempted=len(todo) - done,
        )
        return

    if budget_failure is not None:
        # Not a failure of the run so much as of the day. Say what was kept and
        # how to continue, because everything is on disk and resume is free.
        yield event(
            Phase.EXTRACT,
            f"stopping after {report.extracted} extracted: the request allowance is "
            f"spent ({budget_failure}). The {report.extracted} extracted paper(s) are "
            f"saved; re-run later to resume the remaining {len(todo) - done}.",
            kind="warn",
            extracted=report.extracted,
            not_attempted=len(todo) - done,
            store=str(store.path),
        )
        return

    stored = store.all()
    limitations = sum(1 for e in stored if e.stated_limitation)
    concepts = {c.name.lower() for e in stored for c in e.concepts}
    cost = tracker.stage_report(STAGE, model) if tracker else None

    yield event(
        Phase.EXTRACT,
        f"Extracted {report.extracted}/{report.total} papers "
        f"({len(concepts)} distinct concepts, {limitations} with a stated limitation)"
        + (f"; {report.failed} failed" if report.failed else ""),
        kind="warn" if report.failed else "ok",
        store=str(store.path),
        concepts=len(concepts),
        limitations=limitations,
        cost=cost,
        **report.to_dict(),
    )
