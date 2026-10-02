"""Shared exception types."""

from __future__ import annotations


class RlaError(RuntimeError):
    """Base class for errors this project raises deliberately.

    Subclasses `RuntimeError` so the ordinary "this call failed, degrade and
    record it" handlers across the pipeline catch it without special-casing.
    """


class SourceFormatError(RlaError):
    """A source answered, but not in the format its adapter expects.

    Distinct from a transport failure on purpose: a bot-protection interstitial
    or an HTML error page is a "this source is unusable right now" signal, not
    "this topic has no papers". Silently returning zero results would hide it.
    """


class ModelResolutionError(RuntimeError):
    """A model id could not be resolved to exactly one provider.

    Raised during configuration resolution, before any request is made. It is a
    configuration fault rather than a provider fault, so it is deliberately not a
    `ProviderError`: the router must not retry it or fail over on it, because no
    other model will fix a malformed id.
    """
