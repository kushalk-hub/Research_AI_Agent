"""Provider-specific request pacing shared by source adapters.

The limiter is applied by :class:`Fetcher` immediately before every HTTP attempt.
Strict single-connection providers also hold a cross-process file lease until the
response completes. The lock directory is scoped to this repository's data root;
it coordinates CLI processes on this machine, not machines with separate local
filesystems.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    provider: str
    min_interval: float
    max_in_flight: int | None
    header_policy: str = "none"


PROVIDER_POLICIES: dict[str, ProviderPolicy] = {
    "arxiv": ProviderPolicy("arxiv", 3.0, 1),
    "dblp": ProviderPolicy("dblp", 2.0, 1),
    "crossref": ProviderPolicy("crossref", 1.0, 1, "crossref"),
    # A one-request-per-second default is below OpenAlex's documented anonymous
    # limit and also leaves room for concurrent independent provider tasks.
    "openalex": ProviderPolicy("openalex", 1.0, 1, "openalex"),
    "semantic_scholar": ProviderPolicy("semantic_scholar", 1.1, 1),
    "serpapi": ProviderPolicy("serpapi", 0.5, None),
}


def provider_policy(provider: str) -> ProviderPolicy:
    try:
        return PROVIDER_POLICIES[provider]
    except KeyError as exc:
        raise ValueError(f"no outbound rate policy for provider {provider!r}") from exc


def provider_lock_directory(data_dir: Path) -> Path:
    """Return a stable workspace-local lock directory shared by its CLI runs."""
    return data_dir / "fods" / "provider-locks"


class RateLimitDeadlineExceeded(RuntimeError):
    """A provider cooldown cannot fit before the active workflow deadline."""


class RequestAttemptBudgetExceeded(RuntimeError):
    """The configured hard HTTP-attempt budget is exhausted."""


class LiveCollectionInProgress(RuntimeError):
    """Another FODS live collection currently owns this workspace's lock."""


class LiveCollectionLock:
    """Nonblocking workspace lock that prevents overlapping FODS live runs."""

    def __init__(self, data_dir: Path) -> None:
        self.path = provider_lock_directory(data_dir) / "live-collection.lock"
        self._handle = None

    def __enter__(self) -> LiveCollectionLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            raise LiveCollectionInProgress(
                "another live FODS collection is active in this workspace"
            ) from None
        self._handle = handle
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class RequestAttemptBudget:
    """Thread-safe hard ceiling shared by all Fetchers in one workflow run."""

    def __init__(self, maximum: int) -> None:
        if not 1 <= maximum <= 1000:
            raise ValueError("HTTP attempt budget must be between 1 and 1000")
        self.maximum = maximum
        self.used = 0
        self._guard = Lock()

    def claim(self, provider: str, endpoint_class: str, attempt: int) -> int:
        with self._guard:
            if self.used >= self.maximum:
                raise RequestAttemptBudgetExceeded(
                    f"HTTP attempt budget exhausted before {provider} {endpoint_class} attempt"
                )
            self.used += 1
            return self.used


@dataclass(slots=True)
class RequestExecutionContext:
    emit: Callable[[str, dict[str, Any]], None] | None = None
    deadline: float | None = None


_REQUEST_CONTEXT: contextvars.ContextVar[RequestExecutionContext | None] = contextvars.ContextVar(
    "rla_outbound_request_context", default=None
)


@contextlib.contextmanager
def outbound_request_context(
    *,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    deadline: float | None = None,
):
    """Attach run telemetry/deadline to transport calls made in this async task."""
    token = _REQUEST_CONTEXT.set(RequestExecutionContext(emit=emit, deadline=deadline))
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


def current_request_context() -> RequestExecutionContext | None:
    return _REQUEST_CONTEXT.get()


@dataclass(slots=True)
class Permit:
    provider: str
    endpoint_class: str
    attempt: int
    scheduled_delay: float
    actual_wait: float
    started_at: float
    limiter: ProviderRequestLimiter
    _held: bool

    def defer_for(self, seconds: float) -> None:
        if seconds > 0:
            self.limiter.defer_for(seconds)

    async def release(self) -> None:
        if self._held:
            self._held = False
            await self.limiter._release()


class ProviderRequestLimiter:
    """Coordinate provider request starts and, where required, in-flight calls."""

    MAX_POLICY_INTERVAL = 300.0
    MAX_AUTOMATIC_WAIT_SECONDS = 60.0
    LOCK_POLL_SECONDS = 0.05

    def __init__(
        self,
        policy: ProviderPolicy,
        *,
        lock_dir: Path | None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        if not 0 <= policy.min_interval <= self.MAX_POLICY_INTERVAL:
            raise ValueError("provider minimum interval must be between 0 and 300 seconds")
        if policy.max_in_flight is not None and not 1 <= policy.max_in_flight <= 16:
            raise ValueError("provider max_in_flight must be between 1 and 16")
        self.policy = policy
        self.lock_dir = lock_dir
        self.clock = clock
        self.sleeper = sleeper
        self._lock = asyncio.Lock()
        self._lock_handle = None
        self._last_start: float | None = None
        self._not_before = 0.0
        self._minimum_interval = policy.min_interval
        self._deferred_for = 0.0
        self._dynamic_headers: dict[str, Any] = {}
        self._in_flight = 0
        self._maximum_in_flight = 0

    @property
    def minimum_interval(self) -> float:
        return self._minimum_interval

    @property
    def dynamic_headers(self) -> dict[str, Any]:
        return dict(self._dynamic_headers)

    def tighten_interval(self, interval: float) -> None:
        if interval < 0 or interval > self.MAX_POLICY_INTERVAL:
            return
        self._minimum_interval = max(self._minimum_interval, interval)

    def defer_for(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._deferred_for = max(self._deferred_for, seconds)
        self._not_before = max(self._not_before, self.clock() + seconds)
        if self._lock_handle is not None:
            state = self._read_file_state(self._lock_handle)
            state["not_before"] = max(state.get("not_before", 0.0), self._not_before)
            state["last_start"] = max(state.get("last_start", 0.0), self._last_start or 0.0)
            self._write_file_state(self._lock_handle, state)

    @staticmethod
    def _read_file_state(handle) -> dict[str, float]:
        handle.seek(1)
        raw = handle.read()
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("ascii"))
            return {
                name: float(value)
                for name, value in payload.items()
                if name in {"last_start", "not_before"}
            }
        except (ValueError, TypeError, UnicodeDecodeError):
            return {}

    @staticmethod
    def _write_file_state(handle, state: Mapping[str, float]) -> None:
        handle.seek(1)
        handle.truncate()
        handle.write(json.dumps(dict(state), separators=(",", ":")).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())

    async def _acquire_file_lock(self, deadline: float | None) -> None:
        if self.lock_dir is None:
            return
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        path = self.lock_dir / f"{self.policy.provider}.lock"
        handle = path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_handle = handle
                return
            except (OSError, BlockingIOError):
                if deadline is not None and self.clock() >= deadline:
                    handle.close()
                    raise RateLimitDeadlineExceeded(
                        f"{self.policy.provider} provider lock wait exceeded workflow budget"
                    ) from None
                await self.sleeper(self.LOCK_POLL_SECONDS)

    def _release_file_lock(self) -> None:
        handle = self._lock_handle
        self._lock_handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @contextlib.asynccontextmanager
    async def request(
        self,
        endpoint_class: str,
        attempt: int,
        *,
        deadline: float | None = None,
    ) -> AsyncIterator[Permit]:
        await self._lock.acquire()
        process_lock_held = True
        held = self.policy.max_in_flight == 1
        started_waiting = self.clock()
        try:
            await self._acquire_file_lock(deadline)
            state = self._read_file_state(self._lock_handle) if self._lock_handle else {}
            known_starts = [
                value for value in (self._last_start, state.get("last_start")) if value is not None
            ]
            last_start = max(known_starts) if known_starts else None
            not_before = max(self._not_before, state.get("not_before", 0.0))
            now = self.clock()
            interval_wait = (
                max(0.0, self._minimum_interval - (now - last_start))
                if last_start is not None
                else 0.0
            )
            cooldown_wait = max(0.0, not_before - now)
            scheduled_delay = max(interval_wait, cooldown_wait)
            if scheduled_delay > self.MAX_AUTOMATIC_WAIT_SECONDS:
                raise RateLimitDeadlineExceeded(
                    f"{self.policy.provider} cooldown exceeds the bounded "
                    f"{self.MAX_AUTOMATIC_WAIT_SECONDS:g}s automatic wait"
                )
            if deadline is not None and now + scheduled_delay >= deadline:
                raise RateLimitDeadlineExceeded(
                    f"{self.policy.provider} cooldown exceeds workflow budget"
                )
            if scheduled_delay:
                await self.sleeper(scheduled_delay)
            start = self.clock()
            self._last_start = start
            self._not_before = not_before
            if self._lock_handle:
                self._write_file_state(
                    self._lock_handle,
                    {"last_start": start, "not_before": not_before},
                )
            permit = Permit(
                provider=self.policy.provider,
                endpoint_class=endpoint_class,
                attempt=attempt,
                scheduled_delay=scheduled_delay,
                actual_wait=max(0.0, start - started_waiting),
                started_at=start,
                limiter=self,
                _held=held,
            )
            self._in_flight = getattr(self, "_in_flight", 0) + 1
            self._maximum_in_flight = max(getattr(self, "_maximum_in_flight", 0), self._in_flight)
            if not held:
                self._release_file_lock()
                self._lock.release()
                process_lock_held = False
            yield permit
        finally:
            if "permit" in locals():
                self._in_flight = max(0, self._in_flight - 1)
            if process_lock_held:
                self._release_file_lock()
                self._lock.release()

    async def _release(self) -> None:
        # The async context manager releases the provider lock after the request.
        # This method remains for Permit compatibility and is intentionally a no-op.
        return None

    @property
    def maximum_in_flight_observed(self) -> int:
        return getattr(self, "_maximum_in_flight", 0)

    def observe_headers(self, headers: Mapping[str, str]) -> dict[str, Any]:
        """Record safe provider headers and tighten, never loosen, local policy."""
        normalized = {key.casefold(): str(value).strip() for key, value in headers.items()}
        safe_header_names = {
            "retry-after",
            "x-rate-limit-limit",
            "x-rate-limit-interval",
            "x-concurrency-limit",
            "x-api-pool",
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
        }
        safe: dict[str, Any] = {
            name: normalized[name] for name in safe_header_names if name in normalized
        }
        if self.policy.header_policy == "crossref":
            limit = self._positive_number(normalized.get("x-rate-limit-limit"))
            interval = self._seconds(normalized.get("x-rate-limit-interval"))
            if limit and interval:
                self.tighten_interval(interval / limit)
            concurrency = self._positive_number(normalized.get("x-concurrency-limit"))
            if concurrency and self.policy.max_in_flight is not None:
                # The initial public-pool limit is already one; this permits only
                # header-driven tightening, never relaxation.
                self.policy = ProviderPolicy(
                    self.policy.provider,
                    self._minimum_interval,
                    min(int(concurrency), self.policy.max_in_flight),
                    self.policy.header_policy,
                )
        elif self.policy.header_policy == "openalex":
            remaining = self._positive_number(normalized.get("x-ratelimit-remaining"))
            reset = self._seconds(normalized.get("x-ratelimit-reset"))
            if remaining == 0 and reset:
                self.defer_for(min(reset, self.MAX_POLICY_INTERVAL))
        self._dynamic_headers.update(safe)
        return safe

    @staticmethod
    def _positive_number(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except ValueError:
            return None
        return number if number >= 0 else None

    @staticmethod
    def _seconds(value: str | None) -> float | None:
        if not value:
            return None
        candidate = value.strip().casefold()
        if candidate.endswith("s"):
            candidate = candidate[:-1]
        try:
            seconds = float(candidate)
        except ValueError:
            try:
                when = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except ValueError:
                return None
        return max(0.0, seconds)


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse Retry-After delta seconds or HTTP-date as a nonnegative delay."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            when = datetime.strptime(value.strip(), "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
        except ValueError:
            return None
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return max(0.0, (when - current).total_seconds())
