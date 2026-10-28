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
