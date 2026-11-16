"""Credential redaction for persisted and streamed runtime payloads."""

from __future__ import annotations

import re
from typing import Any


def redact_text(message: str) -> str:
    message = re.sub(r"AIza[\w-]{20,}", "[REDACTED]", message)
    message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        message,
    )
    return re.sub(
        r"(?i)\b(token|password|secret)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        message,
    )


def safe_value(value: Any) -> Any:
    """Recursively redact credential-like keys and text before recording it."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [safe_value(item) for item in value]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if re.search(r"(?i)(api[_-]?key|password|token|secret|authorization)", str(key)):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = safe_value(item)
        return cleaned
    return value


#: Workspace-absolute paths are evidence about *this machine*, not about the
#: research, so they never reach the browser (A-11). Spaces are allowed inside
#: intermediate segments (`C:\Users\Jane Doe\...`); the final segment must not
#: contain one, so ordinary prose after a path is not swallowed.
_WINDOWS_PATH = re.compile(
    r"(?<![\w.])[A-Za-z]:[\\/](?:[^\\/:*?\"<>|,;\r\n]+[\\/])*[^\\/:*?\"<>|,;\s\r\n]+"
)
_POSIX_PATH = re.compile(
    r"(?<![\w.])/(?:Users|home|root|tmp|var|opt|mnt|media|srv|private|workspace)"
    r"(?:/[^/:\s\"'<>|,;)\]]*)*"
)


def relative_path(text: str, roots: tuple[str, ...] = ()) -> str:
    """One absolute path -> a path relative to the first matching root."""
    normalised = text.replace("/", "\\")
    for root in roots:
        root_normalised = root.replace("/", "\\").rstrip("\\")
        if normalised.casefold() == root_normalised.casefold():
            return "."
        prefix = root_normalised + "\\"
        if normalised.casefold().startswith(prefix.casefold()):
            return normalised[len(prefix) :].replace("\\", "/")
    # Unknown root: keep the basename so the event still says *what*, not where.
    return "…/" + normalised.rstrip("\\").rsplit("\\", 1)[-1]


def sanitise_paths(value: Any, roots: tuple[str, ...] = ()) -> Any:
    """Recursively replace absolute paths in strings with relative ones.

    Applied at the serve layer (SSE, history, brief metadata, replay) so a
    record written before this rule existed is still scrubbed on the way out.
    Keys are left alone; only displayable values are rewritten.
    """

    def scrub(text: str) -> str:
        if not _WINDOWS_PATH.search(text) and not _POSIX_PATH.search(text):
            return text
        text = _WINDOWS_PATH.sub(lambda match: relative_path(match.group(0), roots), text)
        return _POSIX_PATH.sub(lambda match: relative_path(match.group(0), roots), text)

    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [sanitise_paths(item, roots) for item in value]
    if isinstance(value, tuple):
        return [sanitise_paths(item, roots) for item in value]
    if isinstance(value, dict):
        return {key: sanitise_paths(item, roots) for key, item in value.items()}
    return value
