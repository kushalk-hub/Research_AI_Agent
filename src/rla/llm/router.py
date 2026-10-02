"""Provider routing: capability gating, fallback, and model selection.

This sits *below* the application's `LLMClient` Protocol and *above* the backends. The
pipeline stages never see it; they receive an `LLMClient` and are unaware of which
provider or model served the call (ADR-001).

Three responsibilities, and deliberately only three:

1. **Model selection** per stage, so a stage never hard-codes a model id, with a
   transient session override above both the call site and the configured role.
2. **Capability gating** -- a model that cannot do what the stage needs is refused, not
   silently used in a degraded mode. This is what keeps the abstraction from collapsing
   to a lowest common denominator (ADR-004).
3. **Fallback** across the configured chain, on recoverable faults only.

What it deliberately does *not* own: retry, pacing, budget, caching. Those stay in
`llm/retry.py` and `store/cache.py`, so there is exactly one retry layer and a call can
never retry twice (ADR-003).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from pydantic import BaseModel

from rla.config import Settings
from rla.llm.base import LLMError
from rla.llm.errors import (
    ErrorCategory,
    ProviderError,
    ProviderQuotaExhausted,
    ProviderUnsupported,
    StructuredOutputError,
)
from rla.store.cache import Cache, CostTracker

#: Backends that can say whether they support schema-constrained output. A backend
#: that cannot answer is treated as *not* supporting it: assuming capability for an
#: unknown provider is how structured output silently degrades.
_SUPPORTS_STRUCTURED = "supports_structured_output"


class RoutingBackend(Protocol):
    """A concrete provider implementation the router can dispatch to."""

    name: str

    def supports(self, model: str, capability: str) -> bool: ...

    async def generate_text(
        self, prompt: str, *, model: str, temperature: float, stage: str
    ) -> tuple[str, Any]: ...

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str,
        temperature: float,
        stage: str,
        retries: int,
    ) -> tuple[BaseModel, Any]: ...

    def stream_text(
        self, prompt: str, *, model: str, temperature: float, stage: str
    ) -> AsyncIterator[str]: ...


class ProviderRouter:
    """Routes each call to a backend, gating on capability and falling back on fault."""

    def __init__(
        self,
        backend: RoutingBackend,
        settings: Settings,
        cache: Cache | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.backend = backend
        self.settings = settings
        self.cache = cache
        self.tracker = tracker or CostTracker()
        #: (stage, from_model, to_model, reason) for each fallback taken.
        self.fallbacks: list[tuple[str, str, str, str]] = []
        #: Transient per-role session overrides (the TUI model selector). Keyed by
        #: role name -- "structured" or "answer" -- not by stage, because the
        #: selector's whole purpose is "use this model for extraction", which
        #: covers both the extraction and resolution stages.
        self.overrides: dict[str, str] = {}
        #: Optional observer for fallback decisions. It is told what happened and
        #: owns none of it: eligibility, ordering and the retry/fallback split
        #: stay entirely inside this class and the backend's `call_with_retry`.
        self.on_fallback: Callable[[tuple[str, str, str, str]], None] | None = None

    # -- properties ---------------------------------------------------------
    @property
    def fast_model(self) -> str:
        return self.settings.fast_model

    @property
    def strong_model(self) -> str:
        return self.settings.strong_model

    # -- model selection ----------------------------------------------------
    def model_for(self, stage: str, explicit: str | None = None) -> str:
        """Resolve which model serves a stage.

        Four rungs, highest first:

        1. a **session override** -- a deliberate, higher-priority user control
           from the TUI model selector, which must be able to say "use Ollama for
           extraction in this run" even where a stage supplies a model explicitly;
        2. an **explicit `model=` argument** -- a call-site default, which still
           beats the configured role exactly as it did before P12;
        3. the stage's **configured role**;
        4. `fast_model`.

        Rungs 2 and 3 are the pre-P12 contract, unchanged. Rung 1 is new, and is
        deliberately transient: it lives on this instance and is never written
        back to settings.
        """
        override = self.overrides.get(self.role_for(stage))
        if override is not None and override != "":
            return override
        if explicit:
            return explicit
        match stage:
            case "answer":
                return self.settings.model_for_answer
            case "query_expansion" | "relevance_scoring" | "extraction" | "resolution":
                return self.settings.model_for_structured
            case _:
                return self.settings.fast_model

    def set_override(self, role: str, model: str | None) -> None:
        """Set or clear a transient session override for a role.

        Never written to settings or `.env`: a TUI selection is a choice for this
        run, and persisting it would turn an experiment into permanent
        configuration. `None` clears; an empty string is stored but does not win,
        because the lookup tests `is not None` and then falls through.
        """
        if model is None:
            self.overrides.pop(role, None)
        else:
            self.overrides[role] = model

    def clear_overrides(self) -> None:
        self.overrides.clear()

    @staticmethod
    def role_for(stage: str) -> str:
        """The override key a stage reads. Unmapped stages read no override."""
        if stage == "answer":
            return "answer"
        if stage in ("query_expansion", "relevance_scoring", "extraction", "resolution"):
            return "structured"
        return ""

    def _chain(self, model: str) -> list[str]:
        """Primary followed by the fallbacks available to that primary."""
        return [model, *self.settings.fallback_chain_for(model)]

    def _eligible(self, model: str, structured: bool) -> tuple[bool, str]:
        """Whether `model` may serve a structured or plain stage, and why not."""
        if not structured:
            return True, ""
        if self.backend.supports(model, _SUPPORTS_STRUCTURED):
            return True, ""
        return (
            False,
            f"model {model!r} does not support schema-constrained output, which "
            "this stage requires; refusing rather than degrading to unvalidated JSON",
        )

    def _candidates(self, model: str, structured: bool) -> list[str]:
        candidates: list[str] = []
        for candidate in self._chain(model):
            ok, _ = self._eligible(candidate, structured)
            if ok:
                candidates.append(candidate)
        return candidates

    # -- fallback -----------------------------------------------------------
    def _should_try_fallback(self, exc: BaseException) -> bool:
        """Whether routing to another model is appropriate for this failure.

        Deliberately narrow. An auth failure, a malformed request, an exhausted
        budget, or a schema failure will not be fixed by a different model, and
        fanning out across models in those cases multiplies the cost of what is
        usually a one-line fix.
        """
        if not isinstance(exc, ProviderError):
            return False
        # Quota is checked before `fallback_eligible` because that property is
        # False for every quota error by design; the opt-in is the one thing that
        # can override it, so it must be consulted here.
        if exc.category is ErrorCategory.QUOTA_EXHAUSTED:
            return self.settings.fallback_on_quota
        return exc.fallback_eligible

    def _quota_hint(self, exc: BaseException) -> str:
        """Actionable text naming the exhausted limit and the model with headroom."""
        if not isinstance(exc, ProviderQuotaExhausted):
            return ""
        spare = list(self.settings.fallback_chain)
        if spare and not self.settings.fallback_on_quota:
            return (
                f" A different model may still have budget ({', '.join(spare)}); "
                "set RLA_FALLBACK_ON_QUOTA=1 to fail over automatically, or switch "
                "the stage's model via RLA_STRUCTURED_MODEL / RLA_ANSWER_MODEL."
            )
        return ""

    async def _dispatch(
        self,
        stage: str,
        structured: bool,
        run: Callable[..., Any],
        **kwargs: Any,
    ) -> Any:
        """Try the primary model, then eligible fallbacks, normalising every error."""
        model = self.model_for(stage, kwargs.pop("model", None))
        candidates = self._candidates(model, structured)
        if not candidates:
            raise ProviderUnsupported(
                self._eligible(model, structured)[1]
                or f"no model configured for stage {stage!r}",
                stage=stage,
            )

        last: BaseException | None = None
        for index, candidate in enumerate(candidates):
            try:
                return await run(model=candidate, stage=stage, **kwargs)
            except Exception as exc:  # normalised below
                error = exc if isinstance(exc, ProviderError) else _normalize(exc, candidate, stage)
                last = error
                is_last = index == len(candidates) - 1
                if is_last or not self._should_try_fallback(error):
                    # Quota exhaustion is the case where an operator most needs to
                    # be told what else is available, so the hint is attached here
                    # rather than only in the log.
                    hint = self._quota_hint(error)
                    if hint:
                        error.args = (f"{error.args[0]}{hint}",)
                    raise error.with_context(stage=stage) from exc
                entry = (stage, candidate, candidates[index + 1], error.category)
                self.fallbacks.append(entry)
                if self.on_fallback is not None:
                    try:
                        self.on_fallback(entry)
                    except Exception:
                        # Observability must never become a second mechanism: a
                        # failing observer is dropped, not allowed to change the
                        # routing decision that was already made.
                        pass
        raise last if last else LLMError(f"stage {stage!r} produced no attempt")

    # -- public API ---------------------------------------------------------
    async def generate_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> str:
        return await self._dispatch_text(stage, prompt, model, temperature)

    async def _dispatch_text(
        self, stage: str, prompt: str, model: str | None, temperature: float
    ) -> tuple[str, Any]:
        """Dispatch a plain-text call and unwrap the backend's ``(value, response)``.

        Backends return the raw provider response alongside the value so they can
        meter usage. `LLMClient` consumers want the value alone, so the tuple is
        collapsed here — at the boundary between the router and the Protocol.
        """

        async def run(**kwargs: Any) -> Any:
            return await self.backend.generate_text(
                prompt=prompt, temperature=temperature, **kwargs
            )

        result = await self._dispatch(stage, False, run, model=model)
        return result[0] if isinstance(result, tuple) else result

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
        retries: int = 2,
    ) -> BaseModel:
        async def run(**kwargs: Any) -> Any:
            return await self.backend.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=temperature,
                retries=retries,
                **kwargs,
            )

        result = await self._dispatch(stage, True, run, model=model)
        return result[0] if isinstance(result, tuple) else result

    async def stream_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        stage: str = "llm",
    ) -> AsyncIterator[str]:
        """Stream from the first model that can serve the stage.

        Fallback mid-stream is not attempted: once bytes have reached the user,
        silently switching models would splice two different answers together. If
        the primary fails before any chunk, the error propagates and the stage's
        own degradation handles it.
        """
        resolved = self.model_for(stage, model)
        ok, why = self._eligible(resolved, False)
        if not ok:
            raise ProviderUnsupported(why, stage=stage)
        async for chunk in self.backend.stream_text(
            prompt, model=resolved, temperature=temperature, stage=stage
        ):
            yield chunk

    def describe(self) -> dict[str, Any]:
        """Routing state, for `rla doctor` and run summaries."""
        return {
            "backend": self.backend.name,
            "fast_model": self.fast_model,
            "strong_model": self.strong_model,
            "structured_model": self.settings.model_for_structured,
            "answer_model": self.settings.model_for_answer,
            "fallback_chain": self.settings.fallback_chain,
            "fallback_on_quota": self.settings.fallback_on_quota,
            "timeout_seconds": self.settings.llm_timeout_seconds,
        }


def _normalize(exc: BaseException, model: str, stage: str) -> ProviderError:
    from rla.llm.error_map import normalize

    return normalize(exc, model=model, stage=stage)


__all__ = ["ProviderRouter", "RoutingBackend", "StructuredOutputError"]
