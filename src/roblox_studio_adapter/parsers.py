"""Turn Studio tool text into structured values.

Shapes below were checked against a live Studio MCP session on 2026-11-23
(``list_roblox_studios``, ``get_studio_state``, ``search_game_tree``,
``inspect_instance``, ``script_search``, ``script_grep``, ``execute_luau``)
and against the tool descriptions for the calls that were not issued.
"""

from __future__ import annotations

import json
import re
from typing import Any

from roblox_studio_adapter.errors import ParseError
from roblox_studio_adapter.results import (
    ConsoleDelta,
    Inspected,
    InspectResult,
    JobStatus,
    SaveStatus,
    ScriptDocument,
    StudioInfo,
    StudioState,
    TreeNode,
    TreePage,
)

_LINE = re.compile(r"^(\d+)→(.*)$")
_MODE = re.compile(r"Current Studio Mode:\s*([A-Za-z]+)", re.IGNORECASE)
_AVAILABLE = re.compile(r"Available DataModels:\s*(.+)", re.IGNORECASE)
_FOCUSED = re.compile(r"Focused DataModel.*:\s*(.+)", re.IGNORECASE)
_ERROR_LINE = re.compile(
    r"(Stack Begin|Stack End|Requested module experienced an error while loading|"
    r"is not a valid member|attempt to |:\d+:\s)",
    re.IGNORECASE,
)
_WARN_LINE = re.compile(r"(Infinite yield possible|\bWarning\b|deprecated)", re.IGNORECASE)
_SAVE_STATUSES = ("NeedsUserAction", "NotNeeded", "Saved", "Failed", "Busy")
_JOB_STATUSES = ("Completed", "Cancelled", "Failed", "Running")


def extract_json(text: str) -> Any:
    """Return the first JSON object or array in ``text``, or None."""
    if not text:
        return None
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def parse_studios(text: str) -> list[StudioInfo]:
    data = extract_json(text)
    rows: list | None = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("studios", "instances", "results"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        if rows is None and ("id" in data or "studio_id" in data):
            rows = [data]
    if rows is None:
        raise ParseError(f"Could not find a studio list in:\n{text}")
    studios: list[StudioInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        studio_id = str(_pick(row, "id", "studio_id", "studioId") or "")
        if not studio_id:
            continue
        studios.append(
            StudioInfo(
                id=studio_id,
                name=str(_pick(row, "name", "displayName", "placeName") or ""),
                mode=str(_pick(row, "mode") or ""),
                persisted_to_cloud=_pick(row, "persistedToCloud", "persisted_to_cloud"),
                place_id=_as_str(_pick(row, "placeId", "place_id")),
                universe_id=_as_str(_pick(row, "universeId", "universe_id")),
                file=_as_str(_pick(row, "file", "filePath")),
                state_text=str(_pick(row, "state") or ""),
                raw=row,
            )
        )
    return studios


def parse_studio_state(text: str) -> StudioState:
    """Parse the bullet list ``get_studio_state`` returns, or a JSON object."""
    data = extract_json(text)
    if isinstance(data, dict) and _pick(data, "mode", "playState", "currentMode"):
        mode = str(_pick(data, "mode", "playState", "currentMode"))
        available_raw = _pick(data, "availableDatamodelTypes", "datamodelTypes", "available")
        if isinstance(available_raw, str):
            available = _split_datamodels(available_raw)
        elif isinstance(available_raw, list):
            available = tuple(str(item) for item in available_raw)
        else:
            available = tuple()
        focused = _as_str(_pick(data, "focused", "focusedDatamodel"))
        playing = mode.lower() == "play" or (mode.lower() != "edit" and any(item in available for item in ("Client", "Server")))
        return StudioState(mode=mode, available=available, focused=focused, playing=playing, raw_text=text)
    mode_match = _MODE.search(text)
    available_match = _AVAILABLE.search(text)
    if not mode_match or not available_match:
        return StudioState(mode="Unknown", available=tuple(), focused=None, playing=False, raw_text=text, unparsed=True)
    mode = mode_match.group(1).strip()
    available = _split_datamodels(available_match.group(1))
    focused_match = _FOCUSED.search(text)
    focused = focused_match.group(1).strip() if focused_match else None
    playing = mode.lower() == "play" or ("Edit" not in available and any(item in available for item in ("Client", "Server")))
    return StudioState(mode=mode, available=available, focused=focused, playing=playing, raw_text=text)


def parse_tree(text: str) -> TreePage:
    note = ""
    stripped = text.strip()
    truncated = stripped.lower().startswith("note:")
    if truncated:
        note = stripped.splitlines()[0]
    if "no matches" in stripped.lower() and extract_json(stripped) is None:
        return TreePage(nodes=[], truncated=False, note=stripped, raw_text=text)
    data = extract_json(stripped)
    if isinstance(data, dict):
        rows = data.get("nodes") or data.get("matches") or data.get("results")
    else:
        rows = data
    if not isinstance(rows, list):
        raise ParseError(f"Game tree result was not a list:\n{text[:500]}")
    nodes: list[TreeNode] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nodes.append(
            TreeNode(
                name=str(row.get("name") or ""),
                class_name=str(row.get("className") or row.get("class_name") or ""),
                full_path=str(row.get("fullPath") or row.get("path") or ""),
                parent_name=_as_str(row.get("parentName")),
                child_summary=_as_str(row.get("childSummary")),
                unexplored_child_count=_as_int(row.get("unexploredChildCount")),
            )
        )
    if "truncated" in note.lower() or "limited" in note.lower():
        truncated = True
    return TreePage(nodes=nodes, truncated=truncated, note=note, raw_text=text)


def parse_inspect(text: str) -> InspectResult:
    data = extract_json(text)
    if not isinstance(data, dict):
        raise ParseError(f"inspect_instance did not return an object:\n{text[:500]}")
    truncated = bool(data.get("truncated") or data.get("warning"))
    if "matches" in data and isinstance(data["matches"], list):
        matches = [_one_inspect(row, text) for row in data["matches"] if isinstance(row, dict)]
        return InspectResult(matches=matches, truncated_matches=truncated or len(matches) >= 20, raw_text=text)
    return InspectResult(matches=[_one_inspect(data, text)], truncated_matches=False, raw_text=text)


def parse_script_read(path: str, text: str) -> ScriptDocument:
    lines = text.splitlines()
    matched = [_LINE.match(line) for line in lines]
    hits = sum(match is not None for match in matched)
    numbered = bool(lines) and hits >= max(1, (len(lines) + 1) // 2)
    if numbered:
        source_lines = []
        for line, match in zip(lines, matched):
            source_lines.append(match.group(2) if match else line)
        source = "\n".join(source_lines)
    else:
        source = text
    return ScriptDocument(path=path, source=source, numbered=numbered, raw_text=text)


def parse_save(text: str) -> SaveStatus:
    data = extract_json(text)
    status = None
    message = text.strip()
    version = None
    file_path = None
    notes_saved = None
    notes_error = None
    if isinstance(data, dict):
        status = _as_str(_pick(data, "status"))
        message = str(_pick(data, "message") or message)
        version = _as_str(_pick(data, "version"))
        file_path = _as_str(_pick(data, "filePath", "file"))
        notes_saved = _pick(data, "notesSaved", "notes_saved")
        notes_error = _as_str(_pick(data, "notesError", "notes_error"))
    if status not in _SAVE_STATUSES:
        for candidate in _SAVE_STATUSES:
            if candidate in text:
                status = candidate
                break
    if status is None:
        status = "Unknown"
    return SaveStatus(
        status=status,
        message=message,
        version=version,
        file_path=file_path,
        notes_saved=notes_saved if isinstance(notes_saved, bool) else None,
        notes_error=notes_error,
        raw_text=text,
    )


def parse_job(text: str) -> JobStatus:
    data = extract_json(text)
    status = None
    job_id = None
    if isinstance(data, dict):
        status = _as_str(_pick(data, "status", "state"))
        job_id = _as_str(_pick(data, "jobId", "job_id"))
    if status not in _JOB_STATUSES:
        # Prefer a JSON status. Fall back to a whole-word match so "Failed"
        # inside a longer sentence still counts, while "Running" in prose
        # does not override a JSON status we already accepted.
        for candidate in _JOB_STATUSES:
            if re.search(rf"\b{candidate}\b", text):
                status = candidate
                break
    return JobStatus(status=status or "Unknown", job_id=job_id, raw_text=text)


def console_delta(previous: str, current: str) -> ConsoleDelta:
    reset = False
    if not previous:
        text = current
    elif current.startswith(previous):
        text = current[len(previous) :].lstrip("\r\n")
    elif previous in current:
        index = current.rfind(previous)
        text = current[index + len(previous) :].lstrip("\r\n")
    else:
        text = current
        reset = True
    errors: list[str] = []
    warnings: list[str] = []
    capturing = False
    block: list[str] = []
    for line in text.splitlines():
        if "Stack Begin" in line:
            capturing = True
            block = [line]
            continue
        if capturing:
            block.append(line)
            if "Stack End" in line:
                errors.append("\n".join(block))
                capturing = False
                block = []
            continue
        if _ERROR_LINE.search(line):
            errors.append(line)
        elif _WARN_LINE.search(line):
            warnings.append(line)
    if capturing and block:
        errors.append("\n".join(block))
    return ConsoleDelta(text=text, reset=reset, errors=errors, warnings=warnings)


def _one_inspect(row: dict, raw_text: str) -> Inspected:
    children_block = row.get("children") if isinstance(row.get("children"), dict) else {}
    immediate = children_block.get("immediateChildren") or []
    children = []
    for child in immediate:
        if isinstance(child, dict):
            children.append(
                {
                    "className": str(child.get("className") or ""),
                    "path": str(child.get("path") or ""),
                }
            )
    properties = row.get("properties")
    if isinstance(properties, dict):
        prop_map = properties
        missing = len(prop_map) == 0
    else:
        # Workspace returned an empty list in the live session. Parts returned a dict.
        prop_map = {}
        missing = True
    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    return Inspected(
        name=str(row.get("name") or ""),
        class_name=str(row.get("className") or ""),
        path=str(row.get("path") or row.get("fullPath") or ""),
        unique_id=_as_str(row.get("uniqueId")),
        properties=prop_map,
        attributes=attributes,
        children=children,
        children_count=int(children_block.get("childrenCount") or len(children)),
        total_descendants=int(children_block.get("totalDescendants") or 0),
        properties_missing=missing,
        raw_text=raw_text,
    )


def _split_datamodels(text: str) -> tuple[str, ...]:
    found = []
    for name in ("Edit", "Client", "Server"):
        if re.search(rf"\b{name}\b", text):
            found.append(name)
    return tuple(found)


def _pick(row: dict, *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
