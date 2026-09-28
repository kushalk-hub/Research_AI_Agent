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
