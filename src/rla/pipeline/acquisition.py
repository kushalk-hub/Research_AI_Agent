"""Multi-source acquisition with dedup and snowball sampling (spec sections 2 and 4).

Flow: title -> queries -> fan out to every enabled source -> dedup -> 1-hop
snowball over the strongest seeds -> LLM relevance filter -> working corpus.

`run()` is an async generator that yields Events and stores the finished
`Corpus` on `self.corpus`, matching the `yield Event(...)` shape in spec
section 8. Every source call is cached and rate-limited, so a re-run costs
nothing and a crash mid-build resumes from the cache rather than from scratch.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from rla.config import Settings
from rla.events import Event, Phase, event
from rla.llm.base import LLMClient
from rla.models import Corpus, Paper
from rla.pipeline.query_expansion import expand_title
from rla.pipeline.scoring import DEFAULT_SCORE, MIN_KEEP_SCORE, score_papers
from rla.sources.arxiv import ArxivSource
from rla.sources.base import HttpSource
from rla.sources.crossref import CrossrefSource
from rla.sources.dblp import DblpSource
from rla.sources.dedup import Deduplicator
from rla.sources.openalex import OpenAlexSource
from rla.sources.semantic_scholar import SemanticScholarSource
from rla.sources.serpapi import SerpApiSource
from rla.store.cache import Cache, Fetcher, RateLimiter

#: Per-source request budget per query. Semantic Scholar is the tightest.
PER_QUERY_LIMIT: dict[str, int] = {
    "semantic_scholar": 25,
    "openalex": 25,
    "arxiv": 20,
    "dblp": 20,
    "crossref": 15,
    "serpapi": 20,
}

#: Seeds used for 1-hop snowball sampling, and the fan-out per direction.
SNOWBALL_SEEDS = 6
SNOWBALL_PER_DIRECTION = 12

#: How many candidates the relevance-scoring stage may look at, per paper of
#: corpus cap.
#:
#: Scoring costs one request per `scoring.BATCH_SIZE` papers, so if it sees the
#: whole candidate pool its cost scales with however many papers the sources
#: happened to return rather than with the corpus being kept. A 291-paper pool
#: trimmed to 30 spent 17 of a 20-request daily allowance on 261 papers that were
#: then discarded -- and left nothing for extraction, the stage that actually
#: builds the graph.
#:
#: Three gives the scorer room to demote two thirds of the window before the cap
#: bites, while keeping the request count proportional to the corpus.
CANDIDATE_MULTIPLE = 3


def candidate_window(papers: list[Paper], cap: int) -> list[Paper]:
    """The papers worth spending a scoring request on.

    A cheap, model-free pre-selection using the same signals `_trim` falls back
    on when no score exists: metadata completeness first, then citations. A
    snowballed stub with no abstract cannot be extracted from at all, so it should
    not displace a complete paper just by being more cited.

    Papers outside the window keep `relevance_score = None`, which `_trim` reads as
    the default and which sorts below every scored paper -- so the cap is filled
    from the window.
    """
    ranked = sorted(
        papers,
        key=lambda p: (not (p.abstract and p.year), -p.citation_count, p.id),
    )
    return ranked[: max(cap, 1) * CANDIDATE_MULTIPLE]

SOURCE_CLASSES: tuple[type[HttpSource], ...] = (
    SemanticScholarSource,
    OpenAlexSource,
    ArxivSource,
    DblpSource,
    CrossrefSource,
)


@dataclass
class AcquisitionReport:
    queries: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)
    failed_sources: dict[str, str] = field(default_factory=dict)
    duplicates_merged: int = 0
    snowball_added: int = 0
    snowball_repeats: int = 0
    citation_edges_resolved: int = 0
    citation_edges_dropped: int = 0
    scored_out: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "queries": self.queries,
            "per_source": self.per_source,
            "failed_sources": self.failed_sources,
            "duplicates_merged": self.duplicates_merged,
            "snowball_added": self.snowball_added,
            "snowball_repeats": self.snowball_repeats,
            "citation_edges_resolved": self.citation_edges_resolved,
            "citation_edges_dropped": self.citation_edges_dropped,
            "scored_out": self.scored_out,
            "notes": self.notes,
        }


def _short(error: Exception, limit: int = 120) -> str:
    """Provider errors arrive as multi-kilobyte JSON; keep log lines readable."""
    text = str(error) if isinstance(error, RuntimeError) else f"{type(error).__name__}: {error}"
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def build_sources(settings: Settings, cache: Cache) -> dict[str, HttpSource]:
    """One Fetcher per source so rate limits are per-source, not global."""
    http = httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        headers={"User-Agent": "rla/0.1 (research literature agent)"},
        follow_redirects=True,
    )

    def fetcher_for(min_interval: float) -> Fetcher:
        return Fetcher(
            cache,
            http,
            limiter=RateLimiter(min_interval),
            max_retries=settings.max_retries,
            timeout=settings.request_timeout_seconds,
        )

    enabled = settings.enabled_sources()
    sources: dict[str, HttpSource] = {}
    for cls in SOURCE_CLASSES:
        if cls.name not in enabled:
            continue
        # The Semantic Scholar delay is configurable because its anonymous pool
        # is shared; a keyless run needs roughly one request per second.
        interval = settings.s2_delay_seconds if cls.name == "semantic_scholar" else cls.min_interval
        sources[cls.name] = cls(fetcher_for(interval))
    if "serpapi" in enabled:
        sources["serpapi"] = SerpApiSource(fetcher_for(0.5), settings.serpapi_api_key)
    return sources


class Acquisition:
    def __init__(self, settings: Settings, cache: Cache, llm: LLMClient | None) -> None:
        self.settings = settings
        self.cache = cache
        self.llm = llm
        self.sources = build_sources(settings, cache)
        self.report = AcquisitionReport()
        self.corpus: Corpus | None = None

    async def _queries(self, title: str) -> AsyncIterator[Event]:
        if self.llm is None:
            self.report.notes.append("no LLM configured: searched the raw title only")
            yield event(
                Phase.SEARCH, "No LLM configured, searching the raw title only", kind="warn"
            )
            self.report.queries = [title]
            return
        async for evt in expand_title(title, self.llm, self.report.queries):
            yield evt

    async def _fan_out(self, queries: list[str], dedup: Deduplicator) -> AsyncIterator[Event]:
        yield event(
            Phase.FETCH,
            f"Fetching from {len(self.sources)} sources x {len(queries)} queries",
            sources=list(self.sources),
        )

        async def run_query(source: HttpSource, query: str) -> tuple[list[Paper], Exception | None]:
            try:
                return await source.search(query, PER_QUERY_LIMIT.get(source.name, 20)), None
            except (RuntimeError, httpx.HTTPError) as exc:
                return [], exc

        jobs = [
            (source.name, query, run_query(source, query))
            for source in self.sources.values()
            for query in queries
        ]
        # Gather so every source is queried at once; each adapter owns a Fetcher
        # with its own rate limiter, so cross-source concurrency is safe.
        outcomes = await asyncio.gather(*(coro for _, _, coro in jobs), return_exceptions=True)

        for (name, query, _), outcome in zip(jobs, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                # Unexpected error type: still a failure, not an empty result.
                papers, error = [], outcome
            else:
                papers, error = outcome
            if error is not None:
                # A dead source is not the same as a topic with no papers; say which.
                self.report.failed_sources.setdefault(name, _short(error))
                yield event(
                    Phase.FETCH,
                    f"{name}: request failed ({_short(error)})",
                    kind="error",
                    source=name,
                    query=query,
                )
                continue
            for paper in papers:
                dedup.add(paper)
            yield event(
                Phase.FETCH,
                f"{name}: {len(papers)} papers for {query!r}",
                source=name,
                query=query,
            )

        for name, count in dedup.by_source.items():
            self.report.per_source[name] = count

    def _graph_sources(self) -> list[HttpSource]:
        """Sources that can walk citations, best first."""
        return [
            source
            for source in (self.sources.get("semantic_scholar"), self.sources.get("openalex"))
            if source is not None
        ]

    async def _snowball(self, dedup: Deduplicator) -> AsyncIterator[Event]:
        graph_sources = self._graph_sources()
        if not graph_sources:
            yield event(
                Phase.FETCH, "No citation-graph source available, skipping snowball", kind="warn"
            )
            return

        names = {s.name for s in graph_sources}
        seeds = sorted(dedup.papers, key=lambda p: p.citation_count, reverse=True)[:SNOWBALL_SEEDS]
        seeds = [p for p in seeds if names.intersection(p.sources)]
        if not seeds:
            yield event(
                Phase.FETCH,
                "No seed paper carries a citation-graph id, skipping snowball",
                kind="warn",
            )
            return

        yield event(
            Phase.FETCH,
            f"Snowballing 1 hop from {len(seeds)} seed papers via {', '.join(sorted(names))}",
            seeds=len(seeds),
        )
        before = len(dedup)

        async def expand(seed: Paper) -> list[Paper]:
            found: list[Paper] = []
            for source in graph_sources:
                for direction in (source.references, source.citations):
                    try:
                        found.extend(await direction(seed, SNOWBALL_PER_DIRECTION))
                    except (RuntimeError, httpx.HTTPError) as exc:
                        self.report.failed_sources.setdefault(f"{source.name}:graph", _short(exc))
                        continue
            return found

        for batch in await asyncio.gather(*(expand(seed) for seed in seeds)):
            for paper in batch:
                dedup.add(paper)

        self.report.snowball_added = len(dedup) - before
        yield event(
            Phase.FETCH, f"Snowball added {self.report.snowball_added} new papers", kind="ok"
        )

    def _trim(self, dedup: Deduplicator) -> list[Paper]:
        papers = dedup.papers
        kept = [p for p in papers if (p.relevance_score or DEFAULT_SCORE) >= MIN_KEEP_SCORE]
        # Relevance first, then metadata completeness, then citations. Snowball
        # adds many citation-only stubs with no abstract, and P2 concept
        # extraction needs text, so a complete paper is worth more than a
        # more-cited incomplete one when the cap forces a choice.
        kept.sort(
            key=lambda p: (
                -(p.relevance_score or 0),
                not (p.abstract and p.year),
                -p.citation_count,
            )
        )
        self.report.scored_out = len(papers) - len(kept)

        cap = self.settings.target_corpus_max
        if len(kept) > cap:
            self.report.notes.append(
                f"trimmed {len(kept) - cap} papers to reach the {cap}-paper cap"
            )
            kept = kept[:cap]
        if len(kept) < self.settings.target_corpus_min:
            self.report.notes.append(
                f"only {len(kept)} papers cleared the relevance filter; "
                "widen the queries or lower MIN_KEEP_SCORE"
            )
        thin = [p for p in kept if not (p.abstract and p.year)]
        if len(thin) > len(kept) * 0.1:
            self.report.notes.append(
                f"{len(thin)}/{len(kept)} kept papers still lack an abstract or year, "
                "below the 90% metadata target; a source that supplies abstracts "
                "(or a full-text stage) would close the gap"
            )
        return kept

    async def run(self, title: str) -> AsyncIterator[Event]:
        dedup = Deduplicator()

        async for evt in self._queries(title):
            yield evt

        async for evt in self._fan_out(self.report.queries, dedup):
            yield evt
        merged_while_searching = dedup.duplicates_merged

        async for evt in self._snowball(dedup):
            yield evt

        resolved, dropped = dedup.resolve_citations()
        self.report.citation_edges_resolved = resolved
        self.report.citation_edges_dropped = dropped
        # Snowballing re-encounters papers search already found; counting those
        # as "duplicates merged" would overstate the dedup rate.
        self.report.snowball_repeats = dedup.duplicates_merged - merged_while_searching
        self.report.duplicates_merged = merged_while_searching

        yield event(
            Phase.FETCH,
            f"Deduplicated to {len(dedup)} unique papers "
            f"({self.report.duplicates_merged} merged, {resolved} citation edges kept)",
            kind="ok",
            unique=len(dedup),
            per_source=dict(self.report.per_source),
        )

        if self.llm is not None:
            # Only the bounded candidate window is scored. The rest are already
            # ranked below it on completeness and citations, so spending requests
            # on them would buy nothing but a smaller budget for extraction.
            window = candidate_window(dedup.papers, self.settings.target_corpus_max)
            if len(window) < len(dedup.papers):
                self.report.notes.append(
                    f"relevance-scored a {len(window)}-paper candidate window rather than "
                    f"all {len(dedup.papers)} candidates; the rest rank below it on "
                    "completeness and citations and could not have reached the corpus"
                )
            async for evt in score_papers(
                window, title, self.llm, self.settings.max_concurrency
            ):
                if evt.kind == "warn" and not evt.payload.get("scored", 0):
                    self.report.notes.append(
                        "the LLM rejected every scoring request, so relevance filtering did not "
                        "actually run; run `rla doctor --llm` to check the key"
                    )
                yield evt
        else:
            self.report.notes.append(
                f"no LLM configured: every paper kept the default score of {DEFAULT_SCORE}"
            )
            yield event(
                Phase.SCORE, f"No LLM configured, defaulting scores to {DEFAULT_SCORE}", kind="warn"
            )

        papers = self._trim(dedup)
        self.corpus = Corpus(
            title=title,
            papers=papers,
            queries=list(self.report.queries),
            source_yield=dict(self.report.per_source),
            built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

        stats = self.corpus.stats()
        yield event(
            Phase.SCORE, f"Working corpus ready: {stats['papers']} papers", kind="ok", **stats
        )

        for name, reason in self.report.failed_sources.items():
            self.report.notes.append(f"source {name} was unusable this run: {reason}")
        if dropped > resolved * 4 and resolved < 20:
            self.report.notes.append(
                f"only {resolved} of {resolved + dropped} reported citation edges landed "
                "inside the corpus, so the citation graph is sparse; more snowball hops or a "
                "larger seed set would densify it"
            )
        if "serpapi" not in self.sources:
            self.report.notes.append(
                "SerpApi disabled: recent preprints and grey literature are a known blind spot"
            )
