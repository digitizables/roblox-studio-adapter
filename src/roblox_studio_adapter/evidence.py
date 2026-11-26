"""JSON evidence for one playtest.

``docs/evidence.schema.json`` is the field list. PROVE stores the object
this module builds on a ``prove.evidence/1`` record, under ``studio``.
The in-process value remains a ``PlaytestReport``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from roblox_studio_adapter.results import PlaytestReport, plain

SCHEMA = "roblox-studio-adapter.evidence/1"
_EXCERPT = 4000
_HEAD = 1800
_TAIL = 1800
_LIST = 10
_LINE = 500


def evidence_record(
    report: PlaytestReport,
    *,
    studio_id: str | None = None,
    intent_id: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-ready playtest record.

    Console text longer than 4000 characters is clipped to the head and the
    tail. The full text stays on ``report.console`` in this process.
    ``console.reset`` true means the snapshot was not a prefix of the later
    log, so the checks saw that whole log.
    """
    console = report.console
    excerpt, truncated = _excerpt(console.text)
    return {
        "schema": SCHEMA,
        "kind": "playtest",
        "captured_at": captured_at or _now(),
        "studio_id": studio_id,
        "intent_id": intent_id,
        "passed": report.passed,
        "failures": list(report.failures),
        "checks": plain(report.checks),
        "play": {
            "mode_before": report.mode_before,
            "mode_after": report.mode_after,
            "started": report.started,
            "stopped": report.stopped,
            "seconds": report.seconds,
        },
        "console": {
            "reset": console.reset,
            "truncated": truncated,
            "error_count": len(console.errors),
            "warning_count": len(console.warnings),
            "errors": [_clip(item) for item in console.errors[:_LIST]],
            "warnings": [_clip(item) for item in console.warnings[:_LIST]],
            "excerpt": excerpt,
        },
        "artifacts": {
            "screenshots": list(report.screenshots),
            "video": plain(report.video) if report.video is not None else None,
        },
        "notes": list(report.notes),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _excerpt(text: str) -> tuple[str, bool]:
    if len(text) <= _EXCERPT:
        return text, False
    return text[:_HEAD] + "\n…\n" + text[-_TAIL:], True


def _clip(text: str) -> str:
    if len(text) <= _LINE:
        return text
    return text[:_LINE] + "…"
