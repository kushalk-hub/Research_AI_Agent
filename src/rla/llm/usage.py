"""Provider-neutral token accounting.

The audit's most dangerous finding was not a wrong number but a *plausible* wrong
number. `usage_from_response` read `usage_metadata.prompt_token_count` -- a Gemini
attribute name -- and returned `(0, 0)` when it was missing. For any other provider the
attribute simply does not exist, so the cost report rendered $0.00 with no error and no
log. A provider swap that broke usage parsing would therefore have made the system look
*cheaper*, which is the one direction nobody checks.

`TokenUsage` makes "unknown" a first-class value instead of a zero. `None` means the
provider did not tell us; `0` means the provider told us zero. They are different claims
and the cost report renders them differently.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts for one call, with unknown represented explicitly.

    Any field may be `None` when the provider did not report it. `total_tokens` is
    derived when both sides are known and otherwise stays `None` rather than
    assuming an additive relationship the provider did not assert.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    #: Provider-reported token count for reasoning/thinking content, when the
    #: provider breaks it out separately. Not additive with output_tokens.
    reasoning_tokens: int | None = None

    @property
    def known(self) -> bool:
        """True when the provider gave us at least one real figure.

        Used to decide whether an estimate is meaningful. An unpriced model with
        known tokens still cannot be costed, and a priced model with unknown
        tokens cannot either; those are two different states, reported by
        `CostTracker` as distinct `cost_status` values.
        """
        return self.input_tokens is not None or self.output_tokens is not None

    def with_total(self) -> TokenUsage:
        """Fill in `total_tokens` when it is derivable and currently unknown."""
        if self.total_tokens is not None:
            return self
        if self.input_tokens is None or self.output_tokens is None:
            return self
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.input_tokens + self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Sum two usages, propagating unknownness rather than inventing a total.

        Adding a known and an unknown yields unknown, because the sum genuinely
        is not known. Conflating the two is precisely the defect this class
        exists to prevent.
        """
        if not self.known or not other.known:
            return TokenUsage()

        def _add(a: int | None, b: int | None) -> int | None:
            return None if a is None or b is None else a + b

        return TokenUsage(
            input_tokens=_add(self.input_tokens, other.input_tokens),
            output_tokens=_add(self.output_tokens, other.output_tokens),
            total_tokens=_add(self.total_tokens, other.total_tokens),
            reasoning_tokens=_add(self.reasoning_tokens, other.reasoning_tokens),
        ).with_total()

    @classmethod
    def unknown(cls) -> TokenUsage:
        return cls()


def usage_from_mapping(usage: object) -> TokenUsage:
    """Read a provider usage block by attribute *or* mapping key.

    LiteLLM and OpenAI-style responses expose `usage.prompt_tokens`, while the
    Gemini SDK exposes `usage_metadata.prompt_token_count`. Both spellings are
    accepted so a backend can hand over whatever its SDK produced without this
    module importing that SDK. Anything unrecognised stays `None`.
    """
    if usage is None:
        return TokenUsage.unknown()

    def _get(*names: str) -> int | None:
        for name in names:
            value = None
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    return TokenUsage(
        input_tokens=_get("prompt_tokens", "prompt_token_count", "input_tokens"),
        output_tokens=_get("completion_tokens", "candidates_token_count", "output_tokens"),
        total_tokens=_get("total_tokens", "total_token_count"),
        reasoning_tokens=_get("reasoning_tokens"),
    ).with_total()


__all__ = ["TokenUsage", "usage_from_mapping"]
