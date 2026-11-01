"""SQLite-backed cache for HTTP responses and LLM calls, plus a cost tracker.

This exists from P0 on purpose: Semantic Scholar anonymous access is roughly
1 request/second, so a re-run must be able to complete with zero network calls.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from rla.errors import SourceFormatError
from rla.store.rate_limits import (
    ProviderRequestLimiter,
    RateLimitDeadlineExceeded,
    RequestAttemptBudget,
    RequestAttemptBudgetExceeded,
    current_request_context,
    parse_retry_after,
)

#: USD per 1M tokens for the rough cost report printed at run end.
#:
#: Keys are matched EXACTLY (after stripping a `provider/` routing prefix), never by
#: substring. The previous substring scan iterated this dict in insertion order, so
#: `'gemini-2.5-flash'` matched inside `'gemini-2.5-flash-lite'` first and the lite
#: model was priced at the full-flash rate -- a 3x overcharge on input and 6.25x on
#: output, on the model that actually does most of the work. Substring matching is
#: the wrong tool for model ids: `flash` is a prefix of `flash-lite`, and any
#: vendor family name is a substring of its own variants.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    # Free on AI Studio today, so a zero estimate understates nothing yet.
    "gemini-embedding-001": (0.0, 0.0),
}

#: Explicit aliases for ids that should price as another entry. Exact-match only,
#: so an alias is always a deliberate statement rather than an accident of naming.
MODEL_PRICING_ALIASES: dict[str, str] = {}


def bare_model_id(model: str) -> str:
    """Strip a `provider/` routing prefix so both spellings price identically.

    LiteLLM routes on strings like `gemini/gemini-2.5-flash`; the direct backends
    use `gemini-2.5-flash`. Neither should be unpriced just because the operator
    wrote a prefix.
    """
    return model.strip().split("/", 1)[1] if "/" in model else model.strip()


def price_for(model: str) -> tuple[float, float] | None:
    """Return (input, output) rates per 1M tokens, or None if the model is unlisted.

    None is a real answer: it means "we do not know what this costs", which the
    report must show rather than silently rounding to a confident $0.00.
    """
    if not model:
        return None
    bare = bare_model_id(model)
    if bare in MODEL_PRICING:
        return MODEL_PRICING[bare]
    alias = MODEL_PRICING_ALIASES.get(bare)
    if alias and alias in MODEL_PRICING:
        return MODEL_PRICING[alias]
    return None


class RateLimiter:
    """Async throttle enforcing a minimum gap between calls."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


@dataclass
class CostTracker:
    """Accumulates token usage so every stage can report what it cost.

    Token counts are `int | None`, and `None` propagates: a call whose usage the
    provider did not report leaves the running total unknown rather than
    contributing a zero. The distinction is what stops a provider that silently
    drops usage metadata from making the whole run look free.
    """

    input_tokens: int | None = 0
    output_tokens: int | None = 0
    calls: int = 0
    #: Calls for which the provider reported no usage at all.
    unknown_calls: int = 0
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, stage: str, input_tokens: int | None, output_tokens: int | None) -> None:
        """Add one call's usage. `None` on either side marks the total unknown."""
        self.calls += 1
        if input_tokens is None or output_tokens is None:
            self.unknown_calls += 1
            # One unknown call poisons the aggregate: the sum is not knowable.
            self.input_tokens = None
            self.output_tokens = None
        else:
            if self.input_tokens is not None:
                self.input_tokens += input_tokens
                self.output_tokens = (self.output_tokens or 0) + output_tokens

        bucket = self.by_stage.setdefault(stage, {"calls": 0, "input": 0, "output": 0})
        bucket["calls"] += 1
        if input_tokens is not None:
            bucket["input"] += input_tokens
            bucket["output"] += output_tokens
        else:
            bucket["input"] = -1  # sentinel: counted, but not summable
            bucket["output"] = -1

    @staticmethod
    def _price(model: str) -> tuple[float, float] | None:
        return price_for(model)

    @staticmethod
    def _is_priced(model: str) -> bool:
        """False means the estimate is unknown, not that the model is free.

        Without this a misconfigured or newly released model reports a confident
        $0.00, which is indistinguishable from actually costing nothing.
        """
        return price_for(model) is not None

    @staticmethod
    def _bucket_tokens(value: int) -> int | None:
        """Per-stage token totals, where the -1 sentinel means 'not summable'."""
        return None if value < 0 else value

    def estimate_usd(self, model: str) -> float | None:
        """Estimated spend, or None when it cannot be known.

        None is returned for two distinct reasons that the report distinguishes
        via `cost_status`: the tokens are unknown, or the model is unpriced. A
        confident number in either case would be fabrication.
        """
        rates = price_for(model) if model else None
        if rates is None or self.input_tokens is None or self.output_tokens is None:
            return None
        in_rate, out_rate = rates
        return (self.input_tokens * in_rate + self.output_tokens * out_rate) / 1_000_000

    def _cost_status(self, model: str) -> str:
        """Why `estimated_usd` is or is not available."""
        if not model:
            return "no_model"
        if self.input_tokens is None or self.output_tokens is None:
            return "unknown_usage"
        if price_for(model) is None:
            return "unpriced_model"
        return "ok"

    def to_dict(self, model: str = "") -> dict[str, Any]:
        estimate = self.estimate_usd(model) if model else None
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "unknown_usage_calls": self.unknown_calls,
            "estimated_usd": round(estimate, 4) if estimate is not None else None,
            "model_priced": self._is_priced(model) if model else None,
            "cost_status": self._cost_status(model) if model else "no_model",
            "by_stage": self.by_stage,
        }

    def stage_report(self, stage: str, model: str = "") -> dict[str, Any]:
        """Cost of one stage alone, so a long pipeline can attribute spend."""
        bucket = self.by_stage.get(stage, {"calls": 0, "input": 0, "output": 0})
        rates = price_for(model) if model else None
        known = rates is not None and bucket["input"] >= 0
        estimate = (
            (bucket["input"] * rates[0] + bucket["output"] * rates[1]) / 1e6
            if known and rates is not None
            else None
        )
        status = (
            "ok"
            if known and model
            else ("no_model" if not model else ("unknown_usage" if rates else "unpriced_model"))
        )
        return {
            "calls": bucket["calls"],
            "input_tokens": self._bucket_tokens(bucket["input"]),
            "output_tokens": self._bucket_tokens(bucket["output"]),
            "estimated_usd": round(estimate, 4) if estimate is not None else None,
            "model_priced": self._is_priced(model) if model else None,
            "cost_status": status,
        }


class Cache:
    """Key/value store on SQLite. `kind` separates http and llm namespaces."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                key        TEXT NOT NULL,
                kind       TEXT NOT NULL,
                value      TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (key, kind)
            )
            """
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    def get(self, key: str, kind: str = "http") -> str | None:
        row = self._conn.execute(
            "SELECT value FROM entries WHERE key = ? AND kind = ?", (key, kind)
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return row[0]

    def set(self, key: str, value: str, kind: str = "http") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO entries (key, kind, value, created_at) VALUES (?, ?, ?, ?)",
            (key, kind, value, time.time()),
        )
        self._conn.commit()

    def get_json(self, key: str, kind: str = "http") -> Any | None:
        raw = self.get(key, kind)
        return None if raw is None else json.loads(raw)

    def set_json(self, key: str, value: Any, kind: str = "http") -> None:
        self.set(key, json.dumps(value, ensure_ascii=False), kind)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": self.entry_count()}

    def entry_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def cache_key(prefix: str, url: str, params: Mapping[str, Any] | None = None) -> str:
    """Deterministic cache key for a request, with params order-independent."""
    suffix = ""
    if params:
        suffix = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] is not None)
    return f"{prefix}:{url}?{suffix}"


class Fetcher:
    """Cache-first JSON fetcher with rate limiting and exponential backoff."""

    #: A 429 that asks us to wait longer than this cannot be ridden out inside
    #: one run, so we give up immediately instead of burning every retry.
    MAX_HONOURED_RETRY_AFTER = 60.0

    def __init__(
        self,
        cache: Cache,
        client: httpx.AsyncClient,
        limiter: RateLimiter | None = None,
        max_retries: int = 4,
        timeout: float = 30.0,
        provider_limiter: ProviderRequestLimiter | None = None,
        attempt_budget: RequestAttemptBudget | None = None,
    ) -> None:
        self.cache = cache
        self.client = client
        self.limiter = limiter or RateLimiter(0.0)
        self.max_retries = max_retries
        self.timeout = timeout
        self.provider_limiter = provider_limiter
        self.attempt_budget = attempt_budget

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        """Seconds the server asked us to wait, per the standard header."""
        return parse_retry_after(response.headers.get("retry-after"))

    async def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        prefix: str = "http",
    ) -> Any | None:
        body = await self._request(url, params, prefix)
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise SourceFormatError(f"expected JSON from {url} but got {body[:60]!r}") from exc

    async def get_text(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        prefix: str = "http",
    ) -> str | None:
        """For non-JSON endpoints, e.g. the arXiv Atom feed."""
        return await self._request(url, params, prefix)

    async def _request(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        prefix: str = "http",
    ) -> str | None:
        key = cache_key(prefix, url, params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        context = current_request_context()
        endpoint_class = self._endpoint_class(url, params)
        provider = (
            self.provider_limiter.policy.provider
            if self.provider_limiter is not None
            else prefix.split(":", 1)[0]
        )
        for attempt in range(1, self.max_retries + 1):
            permit_context = None
            permit = None
            permit_entered = False
            try:
                if self.provider_limiter is not None:
                    permit_context = self.provider_limiter.request(
                        endpoint_class,
                        attempt,
                        deadline=context.deadline if context else None,
                    )
                    permit = await permit_context.__aenter__()
                    permit_entered = True
                else:
                    await self.limiter.acquire()

                if self.attempt_budget is not None:
                    try:
                        attempt_number = self.attempt_budget.claim(
                            provider, endpoint_class, attempt
                        )
                    except RequestAttemptBudgetExceeded:
                        self._emit(
                            "source_http_budget_stopped",
                            context,
                            provider=provider,
                            endpoint_class=endpoint_class,
                            attempt=attempt,
                            attempts_used=self.attempt_budget.used,
                            attempt_budget=self.attempt_budget.maximum,
                            reason="hard_attempt_budget_exhausted",
                        )
                        raise
                else:
                    attempt_number = attempt

                if permit is not None:
                    self._emit(
                        "source_http_attempt",
                        context,
                        provider=provider,
                        endpoint_class=endpoint_class,
                        attempt=attempt,
                        attempt_number=attempt_number,
                        scheduled_delay=round(permit.scheduled_delay, 3),
                        actual_wait=round(permit.actual_wait, 3),
                        in_flight=self.provider_limiter._in_flight,
                        request_started_monotonic=round(permit.started_at, 6),
                    )

                response = await self.client.get(
                    url, params=dict(params or {}), timeout=self.timeout
                )
                safe_headers = (
                    self.provider_limiter.observe_headers(response.headers)
                    if self.provider_limiter is not None
                    else (
                        {"retry-after": response.headers["retry-after"]}
                        if "retry-after" in response.headers
                        else {}
                    )
                )
                retry_after = self._retry_after(response)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    delay = self._retry_delay(attempt, retry_after)
                    decision = (
                        "stop_retry_after_exceeds_bound"
                        if retry_after is not None and retry_after > self.MAX_HONOURED_RETRY_AFTER
                        else "retry"
                        if attempt < self.max_retries
                        else "attempts_exhausted"
                    )
                    if permit is not None and delay:
                        permit.defer_for(delay)
                    self._emit(
                        "source_http_response",
                        context,
                        provider=provider,
                        endpoint_class=endpoint_class,
                        attempt=attempt,
                        status=response.status_code,
                        retry_after=retry_after,
                        rate_limit_headers=safe_headers,
                        retry_delay=round(delay, 3),
                        retry_decision=decision,
                    )
                    if decision == "retry":
                        self._emit(
                            "source_http_retry",
                            context,
                            provider=provider,
                            endpoint_class=endpoint_class,
                            attempt=attempt,
                            status=response.status_code,
                            retry_after=retry_after,
                            scheduled_delay=round(delay, 3),
                        )
                    if decision == "stop_retry_after_exceeds_bound":
                        raise RuntimeError(
                            f"rate limited by {provider} {endpoint_class} "
                            f"({self._safe_endpoint(url)}); Retry-After {retry_after:g}s "
                            f"exceeds the {self.MAX_HONOURED_RETRY_AFTER:g}s retry bound"
                        ) from None
                    if attempt == self.max_retries:
                        break
                    if self.provider_limiter is None:
                        await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                self.cache.set(key, response.text)
                self._emit(
                    "source_http_response",
                    context,
                    provider=provider,
                    endpoint_class=endpoint_class,
                    attempt=attempt,
                    status=response.status_code,
                    retry_after=retry_after,
                    rate_limit_headers=safe_headers,
                    retry_decision="success",
                )
                return response.text
            except (httpx.HTTPError, UnicodeDecodeError) as exc:
                last_error = exc
                retry_after = (
                    self._retry_after(exc.response)
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None
                    else None
                )
                delay = self._retry_delay(attempt, retry_after)
                if permit is not None and delay:
                    permit.defer_for(delay)
                self._emit(
                    "source_http_response",
                    context,
                    provider=provider,
                    endpoint_class=endpoint_class,
                    attempt=attempt,
                    status=(
                        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    ),
                    retry_after=retry_after,
                    rate_limit_headers=(
                        self.provider_limiter.observe_headers(exc.response.headers)
                        if self.provider_limiter is not None
                        and isinstance(exc, httpx.HTTPStatusError)
                        and exc.response is not None
                        else {}
                    ),
                    retry_delay=round(delay, 3),
                    retry_decision="retry" if attempt < self.max_retries else "attempts_exhausted",
                    outcome=type(exc).__name__,
                )
                if attempt < self.max_retries:
                    self._emit(
                        "source_http_retry",
                        context,
                        provider=provider,
                        endpoint_class=endpoint_class,
                        attempt=attempt,
                        status=(
                            exc.response.status_code
                            if isinstance(exc, httpx.HTTPStatusError)
                            else None
                        ),
                        retry_after=retry_after,
                        scheduled_delay=round(delay, 3),
                    )
                if attempt < self.max_retries and self.provider_limiter is None:
                    await asyncio.sleep(delay)
            except RateLimitDeadlineExceeded:
                self._emit(
                    "source_rate_limit_stopped",
                    context,
                    provider=provider,
                    endpoint_class=endpoint_class,
                    attempt=attempt,
                    reason=(
                        "cooldown_exceeds_workflow_deadline"
                        if context is not None and context.deadline is not None
                        else "cooldown_exceeds_safe_wait_bound"
                    ),
                )
                raise
            finally:
                if permit_context is not None and permit_entered:
                    await permit_context.__aexit__(None, None, None)

        endpoint = self._safe_endpoint(url)
        raise RuntimeError(
            f"failed to fetch {provider} {endpoint_class} ({endpoint}) after "
            f"{self.max_retries} attempts"
        ) from last_error

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        delay = min(2 ** (attempt - 1), 30)
        return max(delay, retry_after or 0.0)

    @staticmethod
    def _endpoint_class(url: str, params: Mapping[str, Any] | None) -> str:
        from urllib.parse import urlsplit

        path = urlsplit(url).path.casefold()
        if "arxiv.org" in url or "dblp.org" in url:
            return "search"
        if "crossref.org" in url:
            return "list_search"
        if "openalex.org" in url:
            return "works_filter" if params and "filter" in params else "works_search"
        if "semanticscholar.org" in url:
            if path.endswith("/references"):
                return "references"
            if path.endswith("/citations"):
                return "citations"
            return "paper_search"
        return "request"

    @staticmethod
    def _safe_endpoint(url: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        return f"{parsed.hostname or 'unknown'}{parsed.path}"

    @staticmethod
    def _emit(kind: str, context, **payload: Any) -> None:
        if context is not None and context.emit is not None:
            context.emit(kind, payload)
