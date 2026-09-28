"""P1 gate: source adapters, dedup, acquisition wiring."""

from __future__ import annotations

import httpx
import pytest
import respx

from rla.config import Settings
from rla.errors import SourceFormatError
from rla.llm.base import LLMError
from rla.models import Corpus, Paper
from rla.pipeline.acquisition import Acquisition
from rla.pipeline.query_expansion import expand_title
from rla.pipeline.scoring import ScoreEntry, score_papers
from rla.sources.arxiv import ArxivSource
from rla.sources.base import clean_markup, guess_year, reconstruct_abstract
from rla.sources.crossref import CrossrefSource
from rla.sources.dblp import DblpSource
from rla.sources.dedup import Deduplicator, merge_papers
from rla.sources.openalex import OpenAlexSource
from rla.sources.semantic_scholar import SemanticScholarSource
from rla.sources.serpapi import SerpApiSource
from rla.store.cache import Fetcher, RateLimiter

S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OA_URL = "https://api.openalex.org/works"
DBLP_URL = "https://dblp.org/search/publ/api"
CR_URL = "https://api.crossref.org/works"
ARXIV_URL = "https://export.arxiv.org/api/query"

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <title>Sparse Graph Reasoning for Multi-Agent Systems</title>
    <summary>An abstract about agents.</summary>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <category term="cs.AI"/>
    <arxiv:doi>10.5555/arxiv.2401.01234</arxiv:doi>
  </entry>
</feed>"""


def make_fetcher(cache) -> Fetcher:
    return Fetcher(cache, httpx.AsyncClient(), limiter=RateLimiter(0.0), max_retries=1)


def _mock_all_sources_empty() -> None:
    """Every keyless source answers with zero results."""
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(json={"results": []})
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")


# -- Semantic Scholar --------------------------------------------------------


@respx.mock
async def test_semantic_scholar_maps_search_payload(cache):
    respx.get(S2_URL).respond(
        json={
            "data": [
                {
                    "paperId": "abc123",
                    "externalIds": {"DOI": "https://doi.org/10.5555/XYZ", "ArXiv": "2401.01234"},
                    "title": "Graph Attention Networks",
                    "abstract": "We study attention over graphs.",
                    "year": 2018,
                    "authors": [{"name": "Petar Velickovic"}, {"name": "Guillem Cucurull"}],
                    "venue": "ICLR",
                    "citationCount": 99999,
                    "references": [{"paperId": "ref1"}],
                    "citations": [{"paperId": "cit1"}],
                }
            ]
        }
    )
    papers = await SemanticScholarSource(make_fetcher(cache)).search("gat", 10)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.external_ids["s2"] == "abc123"
    assert paper.doi == "10.5555/xyz"
    assert paper.arxiv_id == "2401.01234"
    assert paper.citation_count == 99999
    assert paper.references == ["ref1"]
    assert paper.citations == ["cit1"]
    assert paper.sources == ["semantic_scholar"]


@respx.mock
async def test_semantic_scholar_tolerates_empty_payload(cache):
    respx.get(S2_URL).respond(json={})
    assert await SemanticScholarSource(make_fetcher(cache)).search("x", 5) == []


@respx.mock
async def test_semantic_scholar_references_unwrap_the_cited_paper(cache):
    respx.get("https://api.semanticscholar.org/graph/v1/paper/abc123/references").respond(
        json={"data": [{"citedPaper": {"paperId": "r1", "title": "A prior work"}}]}
    )
    seed = Paper(id="p", title="T", external_ids={"s2": "abc123"})
    papers = await SemanticScholarSource(make_fetcher(cache)).references(seed, 5)
    assert [p.external_ids["s2"] for p in papers] == ["r1"]


async def test_semantic_scholar_skips_citation_calls_without_a_native_id(cache):
    source = SemanticScholarSource(make_fetcher(cache))
    assert await source.references(Paper(id="p", title="T"), 5) == []
    assert await source.citations(Paper(id="p", title="T"), 5) == []


def test_semantic_scholar_rate_limit_is_the_strictest():
    assert SemanticScholarSource.min_interval >= 1.0
    assert OpenAlexSource.min_interval < SemanticScholarSource.min_interval


# -- OpenAlex ----------------------------------------------------------------


def test_openalex_rebuilds_abstract_from_inverted_index(cache):
    raw = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.5555/OA",
        "display_name": "Graph-of-Agents",
        "publication_year": 2024,
        "abstract_inverted_index": {"Graph": [0], "of": [1], "agents": [2]},
        "authorships": [{"author": {"display_name": "Someone"}}],
        "primary_location": {"landing_page_url": "http://x", "source": {"display_name": "arXiv"}},
        "cited_by_count": 12,
        "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
        "concepts": [{"display_name": "Multi-agent systems"}],
    }
    paper = OpenAlexSource(make_fetcher(cache)).to_paper(raw)
    assert paper.abstract == "Graph of agents"
    assert paper.references == ["W1", "W2"]
    assert paper.external_ids["openalex"] == "W123"
    assert paper.keywords == ["Multi-agent systems"]
    assert paper.venue == "arXiv"


def test_reconstruct_abstract_handles_gaps_and_empty():
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""
    assert reconstruct_abstract({"b": [1], "a": [0]}) == "a b"


# -- arXiv -------------------------------------------------------------------


@respx.mock
async def test_arxiv_parses_atom_feed(cache):
    respx.get(ARXIV_URL).respond(text=ARXIV_FEED, headers={"content-type": "application/atom+xml"})
    papers = await ArxivSource(make_fetcher(cache)).search("agent graphs", 5)
    assert len(papers) == 1
    assert papers[0].year == 2024
    assert papers[0].authors == ["Ada Lovelace"]
    assert papers[0].arxiv_id == "2401.01234v1"
    assert papers[0].doi == "10.5555/arxiv.2401.01234"
    assert papers[0].keywords == ["cs.AI"]


@respx.mock
async def test_arxiv_survives_malformed_xml(cache):
    respx.get(ARXIV_URL).respond(text="<not-xml")
    assert await ArxivSource(make_fetcher(cache)).search("x", 5) == []


# -- DBLP --------------------------------------------------------------------


@respx.mock
async def test_dblp_flattens_wrapped_scalars(cache):
    respx.get(DBLP_URL).respond(
        json={
            "result": {
                "hits": {
                    "hit": [
                        {
                            "info": {
                                "key": "conf/iclr/VelickovicG18",
                                "title": "Graph Attention Networks.",
                                "year": "2018",
                                "venue": "ICLR",
                                "doi": "10.5555/dblp.2018",
                                "ee": "https://dblp.org/rec/conf/iclr/VelickovicG18",
                                "authors": {"author": [{"text": "Petar Velickovic"}]},
                            }
                        }
                    ]
                }
            }
        }
    )
    papers = await DblpSource(make_fetcher(cache)).search("gat", 5)
    assert papers[0].title == "Graph Attention Networks."
    assert papers[0].year == 2018
    assert papers[0].authors == ["Petar Velickovic"]


@respx.mock
async def test_dblp_handles_single_author_dict(cache):
    respx.get(DBLP_URL).respond(
        json={
            "result": {
                "hits": {"hit": [{"info": {"title": "T", "authors": {"author": {"text": "Solo"}}}}]}
            }
        }
    )
    assert (await DblpSource(make_fetcher(cache)).search("x", 5))[0].authors == ["Solo"]


# -- CrossRef ----------------------------------------------------------------


@respx.mock
async def test_crossref_requires_a_doi_and_reads_reference_dois(cache):
    respx.get(CR_URL).respond(
        json={
            "message": {
                "items": [
                    {
                        "DOI": "10.5555/CR.1",
                        "title": ["A Crossref Paper"],
                        "issued": {"date-parts": [[2021, 5]]},
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "container-title": ["JMLR"],
                        "abstract": "<jats:p>Real abstract text.</jats:p>",
                        "is-referenced-by-count": 4,
                        "reference": [{"DOI": "10.5555/REF"}, {"unstructured": "no doi"}],
                    },
                    {"title": ["No DOI Here"]},
                ]
            }
        }
    )
    papers = await CrossrefSource(make_fetcher(cache)).search("x", 5)
    assert len(papers) == 1
    assert papers[0].year == 2021
    assert papers[0].authors == ["Ada Lovelace"]
    assert papers[0].abstract == "Real abstract text."
    assert papers[0].references == ["10.5555/ref"]


def test_clean_markup_and_guess_year():
    assert clean_markup("<jats:p>a  b</jats:p>") == "a b"
    assert clean_markup("") == ""
    assert guess_year("Published 2019 by ACM") == 2019
    assert guess_year("no year") is None


# -- SerpApi (key-gated) -----------------------------------------------------


def test_serpapi_is_unavailable_without_a_key(cache):
    assert SerpApiSource(make_fetcher(cache), "").available is False
    assert SerpApiSource(make_fetcher(cache), "k").available is True


def test_serpapi_id_is_stable_across_runs(cache):
    source = SerpApiSource(make_fetcher(cache), "k")
    raw = {
        "title": "T",
        "link": "http://x",
        "snippet": "s",
        "publication_info": {"summary": "2019 - ACM"},
    }
    assert source.to_paper(raw).id == source.to_paper(raw).id
    assert source.to_paper(raw).year == 2019


# -- dedup -------------------------------------------------------------------


def test_dedup_merges_on_doi_across_sources():
    dedup = Deduplicator()
    dedup.add(
        Paper(
            id="s2:1",
            title="Graph Attention Networks",
            doi="10.1/a",
            sources=["semantic_scholar"],
            external_ids={"s2": "1"},
        )
    )
    dedup.add(
        Paper(
            id="oa:2",
            title="Graph attention networks.",
            doi="https://doi.org/10.1/A",
            sources=["openalex"],
            external_ids={"openalex": "2"},
        )
    )
    assert len(dedup) == 1
    assert dedup.duplicates_merged == 1
    paper = dedup.papers[0]
    assert paper.sources == ["semantic_scholar", "openalex"]
    assert paper.external_ids == {"s2": "1", "openalex": "2"}


def test_dedup_merges_on_title_when_doi_is_missing():
    dedup = Deduplicator()
    dedup.add(Paper(id="a", title="The Graph-of-Agents: A Survey!"))
    dedup.add(Paper(id="b", title="graph of agents a survey"))
    assert len(dedup) == 1


def test_dedup_keeps_distinct_papers_apart():
    dedup = Deduplicator()
    dedup.add(Paper(id="a", title="Graph Attention Networks", doi="10.1/a"))
    dedup.add(Paper(id="b", title="Graph Convolutional Networks", doi="10.1/b"))
    assert len(dedup) == 2


def test_dedup_keeps_the_richer_abstract():
    dedup = Deduplicator()
    dedup.add(Paper(id="a", title="T", doi="10.1/a", abstract="short", sources=["crossref"]))
    dedup.add(
        Paper(
            id="b", title="T", doi="10.1/a", abstract="a much longer abstract", sources=["openalex"]
        )
    )
    assert dedup.papers[0].abstract == "a much longer abstract"


def test_merge_unions_references_and_keeps_max_citations():
    base = Paper(
        id="a",
        title="T",
        doi="10.1/a",
        references=["r1"],
        citations=["c1"],
        citation_count=3,
        sources=["s2"],
    )
    incoming = Paper(
        id="b",
        title="T",
        doi="10.1/a",
        references=["r2"],
        citations=["c2"],
        citation_count=9,
        sources=["oa"],
    )
    merged = merge_papers(base, incoming)
    assert merged.references == ["r1", "r2"]
    assert merged.citations == ["c1", "c2"]
    assert merged.citation_count == 9
    assert merged.sources == ["s2", "oa"]
    assert merged.id == "a"


def test_dedup_merges_via_native_id_when_no_doi():
    dedup = Deduplicator()
    dedup.add(Paper(id="x", title="A title", external_ids={"s2": "same"}))
    dedup.add(Paper(id="y", title="A slightly different title", external_ids={"s2": "same"}))
    assert len(dedup) == 1


def test_resolve_citations_maps_native_ids_to_internal():
    dedup = Deduplicator()
    old = Paper(id="doi:10.1/old", title="Old", doi="10.1/old", external_ids={"s2": "s2old"})
    new = Paper(
        id="doi:10.1/new", title="New", doi="10.1/new", references=["s2old"], citations=["s2ghost"]
    )
    dedup.add(old)
    dedup.add(new)
    resolved, dropped = dedup.resolve_citations()
    assert resolved == 1
    assert dropped == 1
    assert dedup.by_id("doi:10.1/new").references == ["doi:10.1/old"]


def test_resolve_citations_maps_a_paper_with_no_identifiers():
    """A paper with no DOI/arXiv/native id still matches on its own id.

    Otherwise it silently loses every citation edge it takes part in, because
    there is no identifier for a source to report and nothing to match on.
    """
    dedup = Deduplicator()
    dedup.add(Paper(id="p1", title="A", year=2016))
    dedup.add(Paper(id="p2", title="B", year=2021, references=["p1"]))

    resolved, dropped = dedup.resolve_citations()

    assert (resolved, dropped) == (1, 0)
    assert dedup.by_id("p2").references == ["p1"]


def test_resolve_citations_drops_self_references():
    dedup = Deduplicator()
    paper = Paper(id="doi:10.1/a", title="A", doi="10.1/a", external_ids={"s2": "self"})
    paper.references = ["self"]
    dedup.add(paper)
    resolved, dropped = dedup.resolve_citations()
    assert (resolved, dropped) == (0, 1)


def test_resolve_citations_maps_bare_dois():
    dedup = Deduplicator()
    dedup.add(Paper(id="doi:10.1/a", title="A", doi="10.1/a"))
    dedup.add(
        Paper(id="doi:10.1/b", title="B", doi="10.1/b", references=["https://doi.org/10.1/A"])
    )
    dedup.resolve_citations()
    assert dedup.by_id("doi:10.1/b").references == ["doi:10.1/a"]


def test_dedup_counts_by_source():
    dedup = Deduplicator()
    dedup.add(Paper(id="a", title="A", doi="10.1/a", sources=["openalex"]))
    dedup.add(Paper(id="b", title="B", doi="10.1/b", sources=["arxiv"]))
    assert dedup.by_source == {"openalex": 1, "arxiv": 1}


# -- scoring -----------------------------------------------------------------


class StubLLM:
    """Returns a fixed score for every paper id it is shown."""

    def __init__(self, score: int = 5) -> None:
        self.score = score
        self.calls = 0

    @property
    def fast_model(self) -> str:
        return "stub"

    @property
    def strong_model(self) -> str:
        return "stub"

    async def generate_structured(self, prompt, schema, **kwargs):

        self.calls += 1
        ids = [
            line.split("id: ", 1)[1].strip()
            for line in prompt.splitlines()
            if line.strip().startswith("- id:")
        ]
        return schema(scores=[{"id": i, "score": self.score} for i in ids])

    async def generate_text(self, prompt, **kwargs):
        return ""

    async def stream_text(self, prompt, **kwargs):
        yield ""


async def test_scoring_assigns_scores_in_batches():
    papers = [Paper(id=f"p{i}", title=f"T{i}") for i in range(25)]
    events = [evt async for evt in score_papers(papers, "topic", StubLLM(4))]
    assert all(p.relevance_score == 4 for p in papers)
    assert events[-1].kind == "ok"
    assert events[-1].payload["distribution"] == {"4": 25}


async def test_scoring_defaults_unscored_papers_to_three():
    class SilentLLM(StubLLM):
        async def generate_structured(self, prompt, schema, **kwargs):
            from rla.llm.base import LLMError

            raise LLMError("quota")

    papers = [Paper(id="p1", title="T")]
    async for _ in score_papers(papers, "topic", SilentLLM()):
        pass
    assert papers[0].relevance_score == 3


# -- query expansion ---------------------------------------------------------


async def test_query_expansion_fills_the_caller_list():
    queries: list[str] = []
    events = [evt async for evt in expand_title("graph agents", StubLLM(), queries, count=3)]
    assert events[-1].kind == "ok"
    assert isinstance(queries, list)


async def test_query_expansion_falls_back_to_the_title():
    class BrokenLLM(StubLLM):
        async def generate_structured(self, prompt, schema, **kwargs):
            from rla.llm.base import LLMError

            raise LLMError("down")

    queries: list[str] = []
    events = [evt async for evt in expand_title("graph agents", BrokenLLM(), queries)]
    assert queries == ["graph agents"]
    assert any(evt.kind == "warn" for evt in events)


# -- acquisition -------------------------------------------------------------


@respx.mock
async def test_acquisition_builds_a_corpus_without_an_llm(settings, cache):
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.5555/1",
                    "display_name": "Graph-based agent architectures",
                    "publication_year": 2024,
                    "abstract_inverted_index": {"Graph": [0], "agents": [1]},
                    "referenced_works": [],
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text=ARXIV_FEED)

    acquisition = Acquisition(settings, cache, None)
    events = [evt async for evt in acquisition.run("graph-based agents")]

    assert acquisition.corpus is not None
    corpus = acquisition.corpus
    assert isinstance(corpus, Corpus)
    assert len(corpus.papers) == 2
    assert corpus.queries == ["graph-based agents"]
    assert any(evt.phase.value == "fetch" and "Deduplicated" in evt.message for evt in events)
    assert acquisition.report.queries == ["graph-based agents"]


@respx.mock
async def test_acquisition_merges_the_same_paper_from_two_sources(settings, cache):
    """OpenAlex and arXiv describing one paper must collapse to a single record."""
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.5555/arxiv.2401.01234",
                    "display_name": "Sparse Graph Reasoning for Multi-Agent Systems",
                    "publication_year": 2024,
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text=ARXIV_FEED)

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert acquisition.corpus is not None
    assert len(acquisition.corpus.papers) == 1
    assert acquisition.corpus.papers[0].sources == ["openalex", "arxiv"]
    assert acquisition.report.duplicates_merged == 1


@respx.mock
async def test_acquisition_survives_a_dead_source(settings, cache):
    respx.get(S2_URL).respond(status_code=500)
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Only paper",
                    "publication_year": 2020,
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(status_code=503)
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<not-xml")

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert acquisition.corpus is not None
    assert [p.title for p in acquisition.corpus.papers] == ["Only paper"]


async def test_acquisition_reports_the_serpapi_blind_spot_without_it(settings, cache):
    _mock_all_sources_empty()
    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert any("SerpApi" in note for note in acquisition.report.notes)


async def test_acquisition_without_a_cache_is_skipped(settings):
    from rla.pipeline.orchestrator import Pipeline, PipelineResult

    result = PipelineResult()
    events = [evt async for evt in Pipeline(settings, None, None).run("t", result=result)]
    assert any(evt.kind == "warn" and "No cache" in evt.message for evt in events)
    assert result.corpus is None


async def test_acquisition_caps_the_corpus(settings, cache):
    settings.target_corpus_max = 2
    works = [
        {
            "id": f"https://openalex.org/W{i}",
            "doi": f"https://doi.org/10.5555/{i}",
            "display_name": f"Paper {i}",
            "publication_year": 2020,
            "cited_by_count": i,
        }
        for i in range(10)
    ]
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(json={"results": works})
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert acquisition.corpus is not None
    assert len(acquisition.corpus.papers) == 2
    assert any("cap" in note for note in acquisition.report.notes)


@pytest.mark.parametrize("namespace", ["s2", "openalex", "crossref"])
def test_every_adapter_stamps_its_own_provenance(cache, namespace):
    source = {
        "s2": SemanticScholarSource,
        "openalex": OpenAlexSource,
        "crossref": CrossrefSource,
    }[namespace](make_fetcher(cache))
    assert source.name in Settings().enabled_sources()


# -- Failure visibility -------------------------------------------------------


@respx.mock
async def test_non_json_response_raises_source_format_error(cache):
    """A bot-protection page must not read as 'this topic has no papers'."""
    respx.get(OA_URL).respond(
        text="<!doctype html><title>Making sure you're not a bot!</title>", status_code=200
    )
    source = OpenAlexSource(make_fetcher(cache))
    with pytest.raises(SourceFormatError):
        await source.search("agents", 5)


@respx.mock
async def test_a_dead_source_is_reported_and_the_rest_of_the_run_continues(settings, cache):
    respx.get(S2_URL).respond(json={"error": "Too Many Requests"}, status_code=429)
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Sparse Graph Reasoning for Multi-Agent Systems",
                    "publication_year": 2024,
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    events = [evt async for evt in acquisition.run("agents")]

    assert acquisition.corpus is not None
    assert len(acquisition.corpus.papers) == 1
    assert "semantic_scholar" in acquisition.report.failed_sources
    assert any(e.kind == "error" and e.payload.get("source") == "semantic_scholar" for e in events)
    assert any("semantic_scholar" in note for note in acquisition.report.notes)


# -- Citation graph -----------------------------------------------------------


@respx.mock
async def test_openalex_walks_citations_with_cites_and_cited_by_filters(cache):
    """OpenAlex is the keyless citation graph, so snowball survives a dead S2."""
    route = respx.get(OA_URL)
    route.side_effect = [
        httpx.Response(200, json={"results": []}),  # references -> cited_by
        httpx.Response(200, json={"results": []}),  # citations -> cites
    ]
    source = OpenAlexSource(make_fetcher(cache))
    paper = Paper(
        id="W1",
        title="Sparse Graph Reasoning for Multi-Agent Systems",
        external_ids={"openalex": "W1"},
    )

    await source.references(paper, 5)
    await source.citations(paper, 5)

    assert [r.request.url.params["filter"] for r in route.calls] == [
        "cited_by:W1",
        "cites:W1",
    ]


@respx.mock
async def test_snowball_falls_back_to_openalex_when_semantic_scholar_is_dead(settings, cache):
    respx.get(S2_URL).respond(json={"error": "Too Many Requests"}, status_code=429)
    search = respx.get(OA_URL)
    search.side_effect = [
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Sparse Graph Reasoning for Multi-Agent Systems",
                        "publication_year": 2024,
                    }
                ]
            },
        ),
        httpx.Response(200, json={"results": []}),  # references
        httpx.Response(200, json={"results": []}),  # citations
    ]
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    events = [evt async for evt in acquisition.run("agents")]

    assert any("via openalex" in e.message for e in events)
    assert "semantic_scholar" in acquisition.report.failed_sources


@respx.mock
async def test_snowball_repeats_are_not_counted_as_merged_duplicates(settings, cache):
    """Re-seeing a paper while snowballing is not a dedup win."""
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Sparse Graph Reasoning for Multi-Agent Systems",
                    "publication_year": 2024,
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass

    # OpenAlex answers every request with W1, so snowball sees it twice more.
    assert acquisition.report.snowball_repeats == 2
    assert acquisition.report.duplicates_merged == 0
    assert acquisition.report.snowball_added == 0


# -- Metadata quality at the cap ----------------------------------------------


@respx.mock
async def test_trim_prefers_papers_that_have_an_abstract_over_more_cited_stubs(settings, cache):
    """Snowball adds citation-only stubs; P2 needs text, so keep the readable ones."""
    settings = settings.model_copy(update={"target_corpus_max": 2})
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "A Complete Paper About Agents",
                    "publication_year": 2024,
                    "abstract_inverted_index": {"agents": {"Agents": [0]}},
                },
                {
                    "id": "https://openalex.org/W2",
                    "display_name": "A Stub Paper About Agents",
                    "publication_year": 2023,
                    "cited_by_count": 900,
                },
                {
                    "id": "https://openalex.org/W3",
                    "display_name": "Another Complete Paper About Agents",
                    "publication_year": 2022,
                    "abstract_inverted_index": {"agents": {"Agents": [0]}},
                },
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert acquisition.corpus is not None

    kept = acquisition.corpus.papers
    assert len(kept) == 2
    assert all(p.abstract and p.year for p in kept)
    assert "A Stub Paper About Agents" not in {p.title for p in kept}


@respx.mock
async def test_thin_metadata_is_reported_against_the_90_percent_target(settings, cache):
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {"id": f"https://openalex.org/W{i}", "display_name": f"Paper {i}"} for i in range(6)
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    acquisition = Acquisition(settings, cache, None)
    async for _ in acquisition.run("agents"):
        pass
    assert any("90% metadata target" in note for note in acquisition.report.notes)


# -- Scoring failure visibility ------------------------------------------------


@pytest.mark.asyncio
async def test_a_dead_llm_is_reported_instead_of_scoring_silently(papers):
    class BrokenLLM:
        async def generate_structured(self, *args, **kwargs):
            raise LLMError("401 UNAUTHENTICATED")

    events = [evt async for evt in score_papers(papers, "agents", BrokenLLM())]

    final = events[-1]
    assert final.kind == "warn"
    assert final.payload["scored"] == 0
    assert final.payload["failed_batches"] >= 1
    assert "default score of 3" in final.message
    assert "UNAUTHENTICATED" in final.message
    assert all(p.relevance_score == 3 for p in papers)


@pytest.mark.asyncio
async def test_one_dead_llm_batch_does_not_discard_the_others():
    """Batches are independent: one provider failure must not sink the rest."""
    many = [Paper(id=f"p{i}", title=f"Paper {i}", year=2024) for i in range(12)]

    class FlakyLLM:
        async def generate_structured(self, prompt, schema, **kwargs):
            if "Paper 0" in prompt:
                raise LLMError("rate limited")
            return schema(scores=[ScoreEntry(id=f"p{i}", score=5) for i in (10, 11)])

    events = [evt async for evt in score_papers(many, "agents", FlakyLLM())]

    final = events[-1]
    assert final.kind == "ok"
    assert final.payload["scored"] == 2
    assert final.payload["failed_batches"] == 1
    assert "batch(es) failed" in final.message
    assert many[10].relevance_score == 5
    assert many[0].relevance_score == 3


# -- Cache-only rerun ----------------------------------------------------------


@respx.mock
async def test_a_second_run_reaches_no_network(settings, cache):
    """P1 gate: once warm, a rebuild must be answerable from the cache alone.

    The second pass runs inside a respx block with no routes registered, so any
    real HTTP call fails the test instead of silently going out to the internet.
    """
    respx.get(S2_URL).respond(json={"data": []})
    respx.get(OA_URL).respond(
        json={
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Sparse Graph Reasoning for Multi-Agent Systems",
                    "publication_year": 2024,
                }
            ]
        }
    )
    respx.get(DBLP_URL).respond(json={"result": {"hits": {"hit": []}}})
    respx.get(CR_URL).respond(json={"message": {"items": []}})
    respx.get(ARXIV_URL).respond(text="<feed/>")

    first = Acquisition(settings, cache, None)
    async for _ in first.run("agents"):
        pass

    with respx.mock(assert_all_called=False) as offline:
        second = Acquisition(settings, cache, None)
        async for _ in second.run("agents"):
            pass
        assert not offline.routes, "a cached rebuild still made a network call"

    assert second.corpus is not None
    assert first.corpus is not None
    assert [p.id for p in second.corpus.papers] == [p.id for p in first.corpus.papers]


# -- Diagnostics ---------------------------------------------------------------


def test_the_source_probe_does_not_trust_a_cached_ok(settings, monkeypatch, tmp_path):
    """A cached reply proves a source worked once, not that it works now.

    This is how OpenAlex read as "ok" for hours while its daily keyless budget
    was exhausted, and the build produced a corpus with zero citations.
    """
    import asyncio

    from rla.cli import _probe_sources

    settings.data_dir = tmp_path
    with respx.mock(assert_all_called=False) as inner:
        cached_reply = inner.get(OA_URL).mock(
            return_value=httpx.Response(200, json={"results": [{"id": "W1"}]})
        )

        def fake_build_sources(_settings, probe_cache):
            client = httpx.AsyncClient()
            return {"openalex": OpenAlexSource(Fetcher(probe_cache, client))}

        monkeypatch.setattr("rla.pipeline.acquisition.build_sources", fake_build_sources)
        monkeypatch.setattr("rla.cli.get_settings", lambda: settings)

        # Two cache-reading probes share one network call...
        asyncio.run(_probe_sources("graph attention networks", use_cache=True))
        asyncio.run(_probe_sources("graph attention networks", use_cache=True))
        assert cached_reply.call_count == 1

        # ...while a no-cache probe always goes to the source again.
        asyncio.run(_probe_sources("graph attention networks", use_cache=False))
        assert cached_reply.call_count == 2, "the uncached probe reused the cache"


def test_the_doctor_llm_probe_never_reports_a_stale_cached_ok(settings, monkeypatch):
    """`doctor --llm` promises a live request, so it must not read the cache.

    A cache-first probe returns a green light from a call that once succeeded
    under a different key, which is precisely the failure it exists to catch.
    """
    import asyncio

    from rla.cli import _probe_llm

    seen = {}

    class RecordingClient:
        def __init__(self, s, cache, tracker):
            seen["cache"] = cache

        @property
        def backend(self):
            return type("B", (), {"name": "test"})()

        @property
        def fast_model(self):
            return "test-model"

        async def generate_text(self, prompt, **kwargs):
            raise LLMError("401 UNAUTHENTICATED: invalid credentials")

    class RecordingEmbedder:
        def __init__(self, s, cache, tracker):
            seen["embed_cache"] = cache

        async def embed_one(self, text):
            raise LLMError("401 UNAUTHENTICATED: invalid credentials")

    # The probe now builds through the factory, so that is the seam to patch.
    # The invariant under test is unchanged: the probe must be constructed with a
    # None cache, whatever backend is selected.
    monkeypatch.setattr("rla.llm.factory.build_client", lambda *a, **k: RecordingClient(*a, **k))
    monkeypatch.setattr("rla.cli.Embedder", RecordingEmbedder, raising=False)
    monkeypatch.setattr("rla.llm.embeddings.Embedder", RecordingEmbedder)
    status, detail = asyncio.run(_probe_llm(settings))

    assert seen["embed_cache"] is None

    assert seen["cache"] is None
    assert status == "unusable"
    assert "401" in detail


# -- Rate-limit handling -------------------------------------------------------


@respx.mock
async def test_a_long_retry_after_gives_up_immediately_with_a_reason(cache):
    """Retrying a 5-hour quota four times in seven seconds cannot help."""
    route = respx.get(OA_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "18750"})
    )
    async with httpx.AsyncClient() as client:
        fetcher = Fetcher(cache, client, max_retries=4)
        # Distinct params per test: a cached body would skip the request
        # entirely and the test would pass for the wrong reason.
        with pytest.raises(RuntimeError, match="rate limited"):
            await fetcher.get_json(OA_URL, {"search": "retry-after-long"})

    assert route.call_count == 1  # gave up instead of burning every retry


@respx.mock
async def test_a_short_retry_after_is_honoured_rather_than_guessed(cache, monkeypatch):
    seen: list[float] = []

    async def fake_sleep(delay):
        seen.append(delay)

    monkeypatch.setattr("rla.store.cache.asyncio.sleep", fake_sleep)

    route = respx.get(OA_URL)
    route.side_effect = [
        httpx.Response(429, headers={"retry-after": "20"}),
        httpx.Response(200, json={"results": []}),
    ]
    async with httpx.AsyncClient() as client:
        fetcher = Fetcher(cache, client, max_retries=4)
        body = await fetcher.get_json(OA_URL, {"search": "retry-after-short"})

    assert body == {"results": []}
    assert route.call_count == 2
    # Our own 1s backoff would have been too short; the server asked for 20.
    assert seen == [20.0]


@respx.mock
async def test_a_non_numeric_retry_after_is_ignored(cache, monkeypatch):
    async def fake_sleep(delay):
        return None

    monkeypatch.setattr("rla.store.cache.asyncio.sleep", fake_sleep)
    respx.get(OA_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2099 07:28:00 GMT"})
    )
    async with httpx.AsyncClient() as client:
        fetcher = Fetcher(cache, client, max_retries=1)
        with pytest.raises(RuntimeError, match="failed to fetch"):
            await fetcher.get_json(OA_URL, {"search": "retry-after-httPDATE"})
