"""Decide which failures are safe to repeat."""

from __future__ import annotations

import re

from roblox_studio_adapter.results import ToolResult

_RETRYABLE = re.compile(
    r"(timeout|timed out|temporarily|try again|connection reset|econnreset|\b503\b|\b429\b)",
    re.IGNORECASE,
)


def is_retryable_text(text: str) -> bool:
    return _RETRYABLE.search(text or "") is not None


def is_retryable_result(result: ToolResult) -> bool:
    return result.is_error and is_retryable_text(result.text)


def backoff_seconds(attempt: int) -> float:
    """attempt is 0 for the first retry."""
    schedule = (0.4, 1.0, 2.5)
    if attempt < 0:
        return schedule[0]
    if attempt >= len(schedule):
        return schedule[-1]
    return schedule[attempt]
