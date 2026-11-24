"""Structured values handed back to an agent.

Raw tool text is kept on every value. When Studio changes a payload, the
caller still has the original text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class ImageBlob:
    data_b64: str
    mime_type: str = "image/png"


@dataclass
class ToolResult:
    name: str
    text: str
    is_error: bool = False
    images: list[ImageBlob] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    raw: dict | None = None

    def json_value(self) -> Any:
        from roblox_studio_adapter.parsers import extract_json

        return extract_json(self.text)


@dataclass
class StudioInfo:
    id: str
    name: str
    mode: str
    persisted_to_cloud: bool | None = None
    place_id: str | None = None
    universe_id: str | None = None
    file: str | None = None
    state_text: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class StudioState:
    mode: str
    available: tuple[str, ...]
    focused: str | None
    playing: bool
    raw_text: str
    unparsed: bool = False

    @property
    def can_edit_scripts(self) -> bool:
        return (not self.playing) and (self.mode == "Edit" or "Edit" in self.available)


@dataclass
class TreeNode:
    name: str
    class_name: str
    full_path: str
    parent_name: str | None = None
    child_summary: str | None = None
    unexplored_child_count: int | None = None


@dataclass
class TreePage:
    nodes: list[TreeNode]
    truncated: bool
    note: str = ""
    raw_text: str = ""


@dataclass
class Inspected:
    name: str
    class_name: str
    path: str
    unique_id: str | None
    properties: dict[str, Any]
    attributes: dict[str, Any]
    children: list[dict[str, str]]
    children_count: int
    total_descendants: int
    properties_missing: bool
    raw_text: str = ""


@dataclass
class InspectResult:
    matches: list[Inspected]
    truncated_matches: bool = False
    raw_text: str = ""


@dataclass
class ScriptDocument:
    path: str
    source: str
    numbered: bool
    raw_text: str


@dataclass
class SaveStatus:
    status: str
    message: str
    version: str | None = None
    file_path: str | None = None
    notes_saved: bool | None = None
    notes_error: str | None = None
    raw_text: str = ""


@dataclass
class JobStatus:
    status: str
    job_id: str | None
    raw_text: str


@dataclass
class ConsoleDelta:
    text: str
    reset: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlaytestReport:
    mode_before: str
    mode_after: str
    started: bool
    stopped: bool
    seconds: float
    console: ConsoleDelta
    screenshots: list[str] = field(default_factory=list)
    video: dict | None = None
    passed: bool | None = None
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ScriptWriteResult:
    path: str
    created: bool
    unchanged: bool
    class_name: str | None
    note: str = ""


def plain(value: Any) -> Any:
    """Convert dataclasses and paths into JSON-friendly objects."""
    if is_dataclass(value) and not isinstance(value, type):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
