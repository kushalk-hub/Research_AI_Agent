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

#: USD per 1M tokens, used only for the rough cost report printed at run end.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    # Free on AI Studio today, so a zero estimate understates nothing yet.
    "gemini-embedding-001": (0.0, 0.0),
}


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
    """Accumulates token usage so every stage can report what it cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, stage: str, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        bucket = self.by_stage.setdefault(stage, {"calls": 0, "input": 0, "output": 0})
        bucket["calls"] += 1
        bucket["input"] += input_tokens
        bucket["output"] += output_tokens

    @staticmethod
    def _price(model: str) -> tuple[float, float]:
        for key, price in MODEL_PRICING.items():
            if key in model:
                return price
        return (0.0, 0.0)

    @staticmethod
    def _is_priced(model: str) -> bool:
        """False means the estimate is unknown, not that the model is free.

        Without this a misconfigured or newly released model reports a confident
        $0.00, which is indistinguishable from actually costing nothing.
        """
        return any(key in model for key in MODEL_PRICING)

    def estimate_usd(self, model: str) -> float:
        in_rate, out_rate = self._price(model)
        return (self.input_tokens * in_rate + self.output_tokens * out_rate) / 1_000_000

    def to_dict(self, model: str = "") -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": round(self.estimate_usd(model), 4) if model else None,
            "model_priced": self._is_priced(model) if model else None,
            "by_stage": self.by_stage,
        }

    def stage_report(self, stage: str, model: str = "") -> dict[str, Any]:
        """Cost of one stage alone, so a long pipeline can attribute spend."""
        bucket = self.by_stage.get(stage, {"calls": 0, "input": 0, "output": 0})
        in_rate, out_rate = self._price(model)
        return {
            "calls": bucket["calls"],
            "input_tokens": bucket["input"],
            "output_tokens": bucket["output"],
            "estimated_usd": round(
                (bucket["input"] * in_rate + bucket["output"] * out_rate) / 1e6, 4
            )
            if model
            else None,
            "model_priced": self._is_priced(model) if model else None,
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
    ) -> None:
        self.cache = cache
        self.client = client
        self.limiter = limiter or RateLimiter(0.0)
        self.max_retries = max_retries
        self.timeout = timeout

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        """Seconds the server asked us to wait, per the standard header."""
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None  # an HTTP-date, which we do not bother to parse

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
        for attempt in range(self.max_retries):
            await self.limiter.acquire()
            try:
                response = await self.client.get(
                    url, params=dict(params or {}), timeout=self.timeout
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if response.status_code == 429:
                        wait = self._retry_after(response)
                        if wait is not None and wait > self.MAX_HONOURED_RETRY_AFTER:
                            # Exponential backoff would burn all four attempts in
                            # seconds and still fail, so stop and say why.
                            raise RuntimeError(
                                f"rate limited by {url}; the server asks for "
                                f"{int(wait)}s ({wait / 3600:.1f}h) before retrying"
                            ) from None
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                self.cache.set(key, response.text)
                return response.text
            except (httpx.HTTPError, UnicodeDecodeError) as exc:
                last_error = exc
                # Honour a short Retry-After when the server sends one: it is
                # more accurate than our own guess at the backoff curve.
                wait = (
                    self._retry_after(exc.response)
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None
                    else None
                )
                delay = min(2**attempt, 30)
                if wait is not None:
                    delay = max(delay, wait)
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"failed to fetch {url} after {self.max_retries} attempts"
        ) from last_error
