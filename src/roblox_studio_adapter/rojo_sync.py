"""Push a Rojo project's scripts into the open place, without the Rojo plugin.

Rojo's own ``sourcemap`` command maps every script in a project to its file.
This module turns that map into a list of (instance path, class, file) rows,
then ``sync`` writes each script whose Studio source differs.

Pick one writer. Do not run this while ``rojo serve`` is connected to the same
place: both would write the same scripts. ``sync`` checks for a ``rojo serve``
of the same project and refuses to write unless forced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_CLASSES = ("Script", "LocalScript", "ModuleScript")
_SOURCE_SUFFIXES = (".luau", ".lua")
ROJO_SERVE_PORT = 34872


@dataclass
class ScriptRow:
    path: str
    class_name: str
    file: Path


@dataclass
class SyncReport:
    written: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    recreated: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        parts = [
            f"created {len(self.created)}",
            f"updated {len(self.written)}",
            f"unchanged {len(self.unchanged)}",
        ]
        if self.recreated:
            parts.append(f"class-fixed {len(self.recreated)}")
        if self.stale:
            parts.append(f"stale-in-studio {len(self.stale)}")
        if self.pruned:
            parts.append(f"pruned {len(self.pruned)}")
        if self.errors:
            parts.append(f"errors {len(self.errors)}")
        if self.warnings:
            parts.append(f"warnings {len(self.warnings)}")
        head = "dry run: " if self.dry_run else ""
        return head + ", ".join(parts)


def generate_sourcemap(project_dir: Path, project_file: str = "default.project.json") -> dict[str, Any]:
    """Run ``rojo sourcemap`` and return the parsed tree."""
    rojo = shutil.which("rojo")
    if rojo is None:
        raise FileNotFoundError("rojo is not on PATH. Install it (rokit install) or pass a sourcemap.")
    completed = subprocess.run(
        [rojo, "sourcemap", project_file],
        cwd=project_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"rojo sourcemap failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return json.loads(completed.stdout)


def script_rows(sourcemap: dict[str, Any], project_dir: Path) -> list[ScriptRow]:
    """Every script node in a sourcemap, as a ``game.``-rooted path with its source file."""
    rows: list[ScriptRow] = []

    def visit(node: dict[str, Any], trail: list[str]) -> None:
        name = str(node.get("name") or "")
        class_name = str(node.get("className") or "")
        here = trail if class_name == "DataModel" else [*trail, name]
        if class_name in SCRIPT_CLASSES:
            source = _source_file(node, project_dir)
            if source is not None:
                rows.append(ScriptRow(path="game." + ".".join(here), class_name=class_name, file=source))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, here)

    visit(sourcemap, [])
    return rows


def _has_script(node: dict[str, Any]) -> bool:
    for child in node.get("children") or []:
        if isinstance(child, dict) and (child.get("className") in SCRIPT_CLASSES or _has_script(child)):
            return True
    return False


def managed_roots(sourcemap: dict[str, Any]) -> list[str]:
    """Outermost Folders that hold project scripts. Scripts under them that Git does not have are stale.

    rojo sourcemap 7.x gives a directory-mapped Folder no filePaths at all, so a Folder qualifies by
    holding scripts, not by having a directory listed. A Folder backed by a source file is a script.
    """
    roots: list[str] = []

    def visit(node: dict[str, Any], trail: list[str]) -> None:
        name = str(node.get("name") or "")
        class_name = str(node.get("className") or "")
        here = trail if class_name == "DataModel" else [*trail, name]
        files = [str(item) for item in node.get("filePaths") or []]
        if (
            class_name == "Folder"
            and not any(item.endswith(_SOURCE_SUFFIXES) for item in files)
            and _has_script(node)
        ):
            roots.append("game." + ".".join(here))
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, here)

    visit(sourcemap, [])
    return roots


def _source_file(node: dict[str, Any], project_dir: Path) -> Path | None:
    for item in node.get("filePaths") or []:
        text = str(item)
        if text.endswith(_SOURCE_SUFFIXES):
            return (project_dir / text).resolve()
    return None


def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def studio_scripts_luau(roots: list[str], paths: list[str] | None = None) -> str:
    """Luau that returns {fullName: {c = ClassName, s = Source}} for every script under the managed
    roots, plus each listed script path (scripts mapped outside a root, such as a service's own child)."""
    quoted = ", ".join(json.dumps(root.removeprefix("game.")) for root in roots)
    listed = ", ".join(json.dumps(path.removeprefix("game.")) for path in paths or [])
    return f"""
local HttpService = game:GetService("HttpService")
local found = {{}}
local function find(path)
    local current = game
    for _, segment in ipairs(string.split(path, ".")) do
        current = current and current:FindFirstChild(segment)
    end
    return current
end
local function add(item)
    if item:IsA("LuaSourceContainer") then
        found[item:GetFullName()] = {{ c = item.ClassName, s = item.Source }}
    end
end
for _, path in ipairs({{{quoted}}}) do
    local current = find(path)
    if current then
        for _, item in ipairs(current:GetDescendants()) do
            add(item)
        end
    end
end
for _, path in ipairs({{{listed}}}) do
    local current = find(path)
    if current then
        add(current)
    end
end
return HttpService:JSONEncode(found)
""".strip()


def _msgpack_map(data: bytes) -> dict[str, Any] | None:
    """Decode a top-level MessagePack map of scalar values. Enough for Rojo's /api/rojo reply;
    returns None on anything it does not understand rather than guessing."""
    pos = 0

    def take(count: int) -> bytes:
        nonlocal pos
        if pos + count > len(data):
            raise ValueError("truncated")
        chunk = data[pos:pos + count]
        pos += count
        return chunk

    def uint(count: int) -> int:
        return int.from_bytes(take(count), "big")

    def value() -> Any:
        tag = take(1)[0]
        if tag <= 0x7F:
            return tag
        if 0xA0 <= tag <= 0xBF:
            return take(tag & 0x1F).decode("utf-8")
        if tag >= 0xE0:
            return tag - 0x100
        simple = {0xC0: None, 0xC2: False, 0xC3: True}
        if tag in simple:
            return simple[tag]
        sized_str = {0xD9: 1, 0xDA: 2, 0xDB: 4}
        if tag in sized_str:
            return take(uint(sized_str[tag])).decode("utf-8")
        sized_uint = {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}
        if tag in sized_uint:
            return uint(sized_uint[tag])
        raise ValueError(f"unsupported msgpack tag {tag:#x}")

    try:
        head = take(1)[0]
        if 0x80 <= head <= 0x8F:
            count = head & 0x0F
        elif head == 0xDE:
            count = uint(2)
        else:
            return None
        out: dict[str, Any] = {}
        for _ in range(count):
            key = value()
            out[str(key)] = value()
        return out
    except (ValueError, UnicodeDecodeError):
        return None


def rojo_serve_project(port: int = ROJO_SERVE_PORT, timeout: float = 0.5) -> str | None:
    """The project name a local ``rojo serve`` is serving, or None when nothing answers.
    Rojo 7.7 replies in MessagePack; older servers reply in JSON. Both are read."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/rojo", timeout=timeout) as response:
            body = response.read()
    except (OSError, urllib.error.URLError):
        return None
    info: Any = _msgpack_map(body)
    if info is None:
        try:
            info = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    name = info.get("projectName") if isinstance(info, dict) else None
    return str(name) if name else None


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sync(agent: Any, project_dir: Path, *, dry_run: bool = False, prune: bool = False,
         sourcemap: dict[str, Any] | None = None, force: bool = False,
         serve_probe: Any = rojo_serve_project) -> SyncReport:
    """Write every changed script from the project into the open place (Edit mode).

    A script whose class changed (for example a Script that became a
    ModuleScript) is destroyed and recreated. Scripts under managed roots that
    the project does not have are reported as ``stale``; ``prune`` destroys them.
    A dry run compares sources, so it reports created, updated and unchanged exactly.
    When ``rojo serve`` is serving this same project it is already the writer: a real
    sync refuses unless ``force``, and a dry run says so in ``warnings``.
    """
    tree = sourcemap if sourcemap is not None else generate_sourcemap(project_dir)
    rows = script_rows(tree, project_dir)
    roots = managed_roots(tree)
    report = SyncReport(dry_run=dry_run)

    served = serve_probe() if serve_probe else None
    if served is not None and served == str(tree.get("name") or ""):
        note = (f"rojo serve is serving project '{served}' on port {ROJO_SERVE_PORT} and already syncs it. "
                "Use one writer; pass force to write anyway.")
        if not dry_run and not force:
            report.errors.append(note)
            return report
        report.warnings.append(note)

    query = studio_scripts_luau(roots, [row.path for row in rows])
    existing_raw = agent.luau.run_json(query, datamodel="Edit", allow_unyielding=True) if rows or roots else {}
    existing: dict[str, Any] = existing_raw if isinstance(existing_raw, dict) else {}
    # GetFullName omits "game.", the script tools want it. Entries are {c, s}; a bare class string is
    # accepted too, for callers that only know classes.
    studio: dict[str, str] = {}
    studio_source: dict[str, str] = {}
    for name, entry in existing.items():
        key = "game." + name
        if isinstance(entry, dict):
            studio[key] = str(entry.get("c") or "")
            if isinstance(entry.get("s"), str):
                studio_source[key] = _normalize(entry["s"])
        else:
            studio[key] = str(entry)
    wanted = {row.path for row in rows}

    for row in rows:
        try:
            source = read_source(row.file)
            current_class = studio.get(row.path)
            if current_class is not None and current_class != row.class_name:
                report.recreated.append(f"{row.path} {current_class}->{row.class_name}")
                if not dry_run:
                    agent.datamodel.destroy(row.path.removeprefix("game."), datamodel="Edit")
                    agent.context.forget_script(row.path)
                current_class = None
            if dry_run:
                if current_class is None:
                    report.created.append(row.path)
                elif studio_source.get(row.path) == source:
                    report.unchanged.append(row.path)
                else:
                    report.written.append(row.path)
                continue
            result = agent.scripts.write(row.path, source, class_name=row.class_name)
            if result.created:
                report.created.append(row.path)
            elif result.unchanged:
                report.unchanged.append(row.path)
            else:
                report.written.append(row.path)
        except Exception as exc:  # one bad file should not stop the rest
            report.errors.append(f"{row.path}: {type(exc).__name__}: {exc}")

    for path in sorted(set(studio) - wanted):
        report.stale.append(path)
        if prune and not dry_run:
            try:
                agent.datamodel.destroy(path.removeprefix("game."), datamodel="Edit")
                report.pruned.append(path)
            except Exception as exc:
                report.errors.append(f"prune {path}: {type(exc).__name__}: {exc}")
    return report
