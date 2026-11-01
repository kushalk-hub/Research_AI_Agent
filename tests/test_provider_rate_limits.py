from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from fods.events import EventLog
from fods.sources import build_live_source_pool, selected_live_source_names
from fods.tools import DiscoverReferencesArgs, SearchArgs, ToolContext, create_registry
from rla.models import Paper
from rla.pipeline.acquisition import build_sources
from rla.store.cache import Cache, Fetcher
from rla.store.rate_limits import (
    LiveCollectionInProgress,
    LiveCollectionLock,
    ProviderRequestLimiter,
    RateLimitDeadlineExceeded,
    RequestAttemptBudget,
    RequestAttemptBudgetExceeded,
    current_request_context,
    outbound_request_context,
    parse_retry_after,
    provider_policy,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.value += delay
        await asyncio.sleep(0)


async def test_arxiv_requests_are_serial_and_spaced_at_the_transport_boundary(
    tmp_path,
) -> None:
    clock = FakeClock()
    starts: list[float] = []
    in_flight = 0
    maximum_in_flight = 0

    async def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, maximum_in_flight
        starts.append(clock.now())
        in_flight += 1
        maximum_in_flight = max(maximum_in_flight, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return httpx.Response(200, text="<feed/>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    limiter = ProviderRequestLimiter(
        provider_policy("arxiv"),
        lock_dir=None,
        clock=clock.now,
        sleeper=clock.sleep,
    )
    fetcher = Fetcher(Cache(tmp_path / "cache.db"), client, provider_limiter=limiter, max_retries=2)

    try:
        await asyncio.gather(
            fetcher.get_text("https://export.arxiv.org/api/query", {"search_query": "one"}),
            fetcher.get_text("https://export.arxiv.org/api/query", {"search_query": "two"}),
        )
    finally:
        await client.aclose()

    assert len(starts) == 2
    assert starts[1] - starts[0] >= 3.0
    assert maximum_in_flight == 1


async def test_retry_after_is_a_minimum_and_retry_uses_the_same_limiter(tmp_path) -> None:
    clock = FakeClock()
    starts: list[float] = []
    responses = [429, 200]

    async def respond(request: httpx.Request) -> httpx.Response:
        starts.append(clock.now())
        status = responses.pop(0)
        headers = {"Retry-After": "5"} if status == 429 else {}
        return httpx.Response(status, text="ok", headers=headers, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    limiter = ProviderRequestLimiter(
        provider_policy("arxiv"),
        lock_dir=None,
        clock=clock.now,
        sleeper=clock.sleep,
    )
    fetcher = Fetcher(Cache(tmp_path / "cache.db"), client, provider_limiter=limiter, max_retries=2)
    try:
        assert (
            await fetcher.get_text("https://export.arxiv.org/api/query", {"search_query": "x"})
            == "ok"
        )
    finally:
        await client.aclose()

    assert len(starts) == 2
    assert starts[1] - starts[0] >= 5.0
    assert limiter.maximum_in_flight_observed == 1


def test_retry_after_accepts_delta_seconds_and_http_date() -> None:
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
    future = now + timedelta(seconds=12)

    assert parse_retry_after("7") == 7
    assert parse_retry_after(future.strftime("%a, %d %b %Y %H:%M:%S GMT"), now=now) == 12
    assert parse_retry_after("invalid", now=now) is None


def test_crossref_headers_tighten_but_never_relax_public_policy() -> None:
    limiter = ProviderRequestLimiter(provider_policy("crossref"), lock_dir=None)

    public_headers = limiter.observe_headers(
        {
            "x-api-pool": "public",
            "x-rate-limit-limit": "1",
            "x-rate-limit-interval": "8s",
            "x-concurrency-limit": "1",
        }
    )
    assert limiter.minimum_interval >= 8
    assert limiter.policy.max_in_flight == 1
    assert public_headers["x-api-pool"] == "public"

    polite_headers = limiter.observe_headers(
        {
            "x-api-pool": "polite",
            "x-rate-limit-limit": "10",
            "x-rate-limit-interval": "1s",
            "x-concurrency-limit": "3",
        }
    )
    assert limiter.minimum_interval >= 8
    assert limiter.policy.max_in_flight == 1
    assert polite_headers["x-api-pool"] == "polite"


async def test_openalex_headers_apply_reset_cooldown_and_capture_safe_values() -> None:
    clock = FakeClock()
    limiter = ProviderRequestLimiter(
        provider_policy("openalex"), lock_dir=None, clock=clock.now, sleeper=clock.sleep
    )

    safe_headers = limiter.observe_headers(
        {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "11"}
    )
    assert safe_headers == {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "11"}
    async with limiter.request("works_search", 1):
        pass
    assert clock.now() >= 11


async def test_required_cooldown_beyond_workflow_deadline_stops_without_request() -> None:
    clock = FakeClock()
    limiter = ProviderRequestLimiter(
        provider_policy("arxiv"), lock_dir=None, clock=clock.now, sleeper=clock.sleep
    )
    limiter.defer_for(10)

    try:
        async with limiter.request("search", 1, deadline=5):
            raise AssertionError("request must not be entered after its deadline")
    except RateLimitDeadlineExceeded:
        pass
    else:
        raise AssertionError("deadline overrun must stop the provider attempt")


async def test_independent_providers_do_not_share_a_global_lock() -> None:
    clock = FakeClock()
    arxiv = ProviderRequestLimiter(
        provider_policy("arxiv"), lock_dir=None, clock=clock.now, sleeper=clock.sleep
    )
    dblp = ProviderRequestLimiter(
        provider_policy("dblp"), lock_dir=None, clock=clock.now, sleeper=clock.sleep
    )
    starts: list[tuple[str, float]] = []

    async def one(limiter: ProviderRequestLimiter, provider: str) -> None:
        async with limiter.request("search", 1) as permit:
            starts.append((provider, permit.started_at))
            await asyncio.sleep(0)

    await asyncio.gather(one(arxiv, "arxiv"), one(dblp, "dblp"))

    assert set(starts) == {("arxiv", 0.0), ("dblp", 0.0)}


async def test_same_provider_limiters_share_workspace_lock_and_spacing(tmp_path) -> None:
    clock = FakeClock()
    lock_dir = tmp_path / "provider-locks"
    first = ProviderRequestLimiter(
        provider_policy("arxiv"), lock_dir=lock_dir, clock=clock.now, sleeper=clock.sleep
    )
    second = ProviderRequestLimiter(
        provider_policy("arxiv"), lock_dir=lock_dir, clock=clock.now, sleeper=clock.sleep
    )
    starts: list[float] = []

    async def one(limiter: ProviderRequestLimiter) -> None:
        async with limiter.request("search", 1) as permit:
            starts.append(permit.started_at)
            await asyncio.sleep(0)

    await asyncio.gather(one(first), one(second))

    assert len(starts) == 2
    assert abs(starts[0] - starts[1]) >= 3.0


def test_live_collection_lock_rejects_overlapping_runs(tmp_path) -> None:
    lock = LiveCollectionLock(tmp_path)
    with lock:
        try:
            with LiveCollectionLock(tmp_path):
                raise AssertionError("a second run must not acquire the workspace lock")
        except LiveCollectionInProgress:
            pass


def test_http_attempt_budget_is_a_hard_ceiling() -> None:
    budget = RequestAttemptBudget(1)
    assert budget.claim("arxiv", "search", 1) == 1
    try:
        budget.claim("arxiv", "search", 2)
    except RequestAttemptBudgetExceeded:
        pass
    else:
        raise AssertionError("a claim beyond the ceiling must fail before dispatch")


async def test_enabled_sources_share_the_provider_policy_for_search_and_references(
    settings, cache
) -> None:
    sources = build_sources(settings, cache)
    try:
        assert selected_live_source_names(settings, 3) == [
            "semantic_scholar",
            "openalex",
            "arxiv",
        ]
        assert selected_live_source_names(settings, 5) == [
            "semantic_scholar",
            "openalex",
            "arxiv",
            "crossref",
            "dblp",
        ]
        assert sources["semantic_scholar"].fetcher.provider_limiter.minimum_interval >= 1.1
        assert sources["arxiv"].fetcher.provider_limiter.minimum_interval == 3.0
        assert sources["dblp"].fetcher.provider_limiter.minimum_interval == 2.0
        assert sources["crossref"].fetcher.provider_limiter.minimum_interval == 1.0
        assert sources["openalex"].fetcher.provider_limiter.minimum_interval == 1.0

        pool = build_live_source_pool(settings, cache, limit=5)
        assert list(pool.searchers) == [
            "semantic_scholar",
            "openalex",
            "arxiv",
            "crossref",
            "dblp",
        ]
        assert set(pool.reference_resolvers) == {"semantic_scholar", "openalex"}
        for provider, resolver in pool.reference_resolvers.items():
            assert resolver.__self__.fetcher.provider_limiter.policy.provider == provider
        await pool.close()
    finally:
        if sources:
            await next(iter(sources.values())).fetcher.client.aclose()


async def test_transport_telemetry_is_sanitized_and_cache_remains_cache_first(tmp_path) -> None:
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text="retry", request=request)
        return httpx.Response(
            200,
            json={"results": []},
            headers={"X-RateLimit-Remaining": "9", "X-RateLimit-Reset": "60"},
            request=request,
        )

    clock = FakeClock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    budget = RequestAttemptBudget(2)
    limiter = ProviderRequestLimiter(
        provider_policy("openalex"), lock_dir=None, clock=clock.now, sleeper=clock.sleep
    )
    fetcher = Fetcher(
        Cache(tmp_path / "cache.db"),
        client,
        provider_limiter=limiter,
        attempt_budget=budget,
        max_retries=2,
    )
    telemetry: list[tuple[str, dict[str, object]]] = []
    try:
        with outbound_request_context(emit=lambda kind, payload: telemetry.append((kind, payload))):
            assert await fetcher.get_json(
                "https://api.openalex.org/works", {"search": "topic", "api_key": "test-secret"}
            ) == {"results": []}
            assert await fetcher.get_json(
                "https://api.openalex.org/works", {"search": "topic", "api_key": "test-secret"}
            ) == {"results": []}
    finally:
        await client.aclose()

    assert calls == 2
    assert budget.used == 2
    assert [kind for kind, _payload in telemetry].count("source_http_attempt") == 2
    assert any(kind == "source_http_retry" for kind, _payload in telemetry)
    assert any(
        payload.get("rate_limit_headers")
        == {
            "x-ratelimit-remaining": "9",
            "x-ratelimit-reset": "60",
        }
        for kind, payload in telemetry
        if kind == "source_http_response"
    )
    assert "test-secret" not in repr(telemetry)


async def test_fods_acquisition_and_reference_tools_propagate_deadline_and_telemetry(
    tmp_path,
) -> None:
    observed: list[tuple[str, bool]] = []

    async def search(_query: str, _limit: int) -> list[Paper]:
        request_context = current_request_context()
        observed.append(
            ("search", request_context is not None and request_context.emit is not None)
        )
        assert request_context is not None and request_context.deadline == 123.0
        return []

    async def resolve(_paper: Paper, _limit: int) -> list[Paper]:
        request_context = current_request_context()
        observed.append(
            ("reference", request_context is not None and request_context.emit is not None)
        )
        assert request_context is not None and request_context.deadline == 123.0
        return []

    paper = Paper(id="p1", title="Graph attention", external_ids={"openalex": "W1"})
    registry = create_registry({"openalex": search}, reference_resolvers={"openalex": resolve})
    context = ToolContext(
        run_id="rate-limit-test",
        mode="live",
        topic="graph attention",
        question="How does graph attention work?",
        output_path="brief.md",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        event_log=EventLog(),
        dependency_results={
            "context": {
                "snapshot_reused": True,
                "context_hash": "a" * 32,
                "papers": [paper.model_dump(mode="json")],
            }
        },
        metadata={"outbound_request_deadline": 123.0, "reference_timeout_seconds": 5},
    )

    await registry.get("search_openalex").handler(context, SearchArgs(query="graph attention"))
    await registry.get("discover_references").handler(
        context,
        DiscoverReferencesArgs(seed_paper_id="p1", resolver_source="openalex", max_candidates=5),
    )

    assert observed == [("search", True), ("reference", True)]
