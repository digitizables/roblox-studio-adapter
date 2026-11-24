"""Find plugins from entry points and from ``plugins/*/plugin.json``.

A future plugin is a folder with ``plugin.json`` and a ``src`` layout. The
host inserts that ``src`` directory on ``sys.path`` while it imports the
module. Installing records the folder so later runs do not depend on the
current working directory.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roblox_studio_plugin_host.contract import Plugin, PluginManifest
from roblox_studio_plugin_host.state import PluginHome


@dataclass
class PluginRecord:
    """One discovered plugin, loaded or broken."""

    id: str
    plugin: Plugin | None
    manifest: PluginManifest | None
    source: str
    path: str | None
    error: str | None = None
    version: str = ""

    @property
    def ok(self) -> bool:
        return self.plugin is not None and self.manifest is not None and not self.error


@dataclass
class Discovery:
    records: list[PluginRecord] = field(default_factory=list)

    def get(self, plugin_id: str) -> PluginRecord | None:
        for record in self.records:
            if record.id == plugin_id:
                return record
        return None

    def ids(self) -> list[str]:
        return [record.id for record in self.records]


def discover(home: PluginHome | None = None, *, extra_roots: list[Path] | None = None) -> Discovery:
    """Load every plugin the process can see. A broken plugin is listed, not fatal."""
    found: dict[str, PluginRecord] = {}
    for record in _from_entry_points():
        found[record.id] = record
    roots = list(extra_roots or [])
    roots.extend(_default_roots())
    seen_dirs: set[Path] = set()
    for root in roots:
        for folder in _plugin_folders(root):
            resolved = folder.resolve()
            if resolved in seen_dirs:
                continue
            seen_dirs.add(resolved)
            record = _from_folder(folder)
            if record.id not in found or not found[record.id].ok:
                found[record.id] = record
    if home is not None:
        for plugin_id, info in home.read_installed().get("plugins", {}).items():
            if plugin_id in found:
                continue
            raw_path = info.get("path")
            if raw_path:
                record = _from_folder(Path(raw_path))
                found[record.id or plugin_id] = record
    ordered = sorted(found.values(), key=lambda record: record.id)
    return Discovery(ordered)


def load_installed(home: PluginHome, plugin_id: str) -> PluginRecord:
    """Return one installed, loadable plugin or raise."""
    from roblox_studio_plugin_host.errors import NotInstalled, PluginNotFound

    found = discover(home)
    record = found.get(plugin_id)
    if record is None:
        raise PluginNotFound(plugin_id, found.ids())
    if not home.is_installed(plugin_id):
        raise NotInstalled(plugin_id)
    if not record.ok or record.plugin is None or record.manifest is None:
        from roblox_studio_plugin_host.errors import PluginHostError

        raise PluginHostError(f"Plugin {plugin_id!r} failed to load: {record.error}")
    return record


def _from_entry_points() -> list[PluginRecord]:
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return []
    try:
        selected = entry_points()
    except Exception as exc:
        return [_broken("entry-points", "", "entry-point", None, f"entry point scan failed: {exc}")]
    group = selected.select(group="roblox_studio.plugins") if hasattr(selected, "select") else selected.get("roblox_studio.plugins", [])
    records: list[PluginRecord] = []
    for entry in group:
        try:
            loaded = entry.load()
            plugin = loaded() if callable(loaded) else loaded
            manifest = plugin.manifest()
            records.append(
                PluginRecord(
                    id=manifest.id,
                    plugin=plugin,
                    manifest=manifest,
                    source=f"entry-point:{entry.value}",
                    path=None,
                    version=manifest.version,
                )
            )
        except Exception as exc:
            name = getattr(entry, "name", "plugin")
            records.append(_broken(str(name), "", f"entry-point:{getattr(entry, 'value', '')}", None, str(exc)))
    return records


def _from_folder(folder: Path) -> PluginRecord:
    manifest_path = folder / "plugin.json"
    if not manifest_path.is_file():
        return _broken(folder.name, "", "path", str(folder), "plugin.json is missing")
    try:
        spec = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _broken(folder.name, "", "path", str(folder), f"plugin.json could not be read: {exc}")
    plugin_id = str(spec.get("id") or folder.name)
    module_name = spec.get("module")
    attribute = str(spec.get("attribute") or "PLUGIN")
    src = folder / str(spec.get("src") or "src")
    if not module_name:
        return _broken(plugin_id, "", "path", str(folder), "plugin.json needs a module")
    src_text = str(src)
    if src.is_dir() and src_text not in sys.path:
        sys.path.insert(0, src_text)
    try:
        module = importlib.import_module(str(module_name))
        if os.environ.get("ROBLOX_PLUGIN_RELOAD") == "1":
            module = importlib.reload(module)
        loaded = getattr(module, attribute)
        plugin = loaded() if callable(loaded) else loaded
        manifest = plugin.manifest()
        if manifest.id != plugin_id:
            return _broken(
                plugin_id,
                "",
                "path",
                str(folder),
                f"plugin.json id is {plugin_id!r} but the manifest id is {manifest.id!r}",
            )
        return PluginRecord(
            id=manifest.id,
            plugin=plugin,
            manifest=manifest,
            source="path",
            path=str(folder),
            version=manifest.version,
        )
    except Exception as exc:
        return _broken(plugin_id, "", "path", str(folder), f"{type(exc).__name__}: {exc}")


def _plugin_folders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    if (root / "plugin.json").is_file():
        return [root]
    folders = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "plugin.json").is_file():
            folders.append(child)
    return folders


def _default_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get("ROBLOX_STUDIO_PLUGIN_ROOT")
    if override:
        roots.append(Path(override))
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        plugins = candidate / "plugins"
        marker = candidate / "pyproject.toml"
        if plugins.is_dir() and marker.is_file():
            roots.append(plugins)
            break
    return roots


def _broken(plugin_id: str, version: str, source: str, path: str | None, error: str) -> PluginRecord:
    return PluginRecord(
        id=plugin_id,
        plugin=None,
        manifest=None,
        source=source,
        path=path,
        error=error,
        version=version,
    )


def coerce_params(specs: tuple[Any, ...], values: dict[str, Any], *, allow_unknown: bool = False) -> dict[str, Any]:
    """Coerce a stringly dict (CLI) into the types the manifest declares."""
    from roblox_studio_plugin_host.errors import BadParameter

    known = {spec.name: spec for spec in specs}
    parsed: dict[str, Any] = {}
    for key, raw in values.items():
        spec = known.get(key)
        if spec is None:
            if allow_unknown:
                parsed[key] = raw
                continue
            names = ", ".join(sorted(known)) or "(none)"
            raise BadParameter(f"Unknown parameter {key!r}. Known parameters: {names}.")
        parsed[key] = _coerce(spec, raw)
    return parsed


def _coerce(spec: Any, raw: Any) -> Any:
    from roblox_studio_plugin_host.errors import BadParameter

    if raw is None:
        return None
    try:
        if spec.kind == "string":
            value: Any = str(raw)
        elif spec.kind == "integer":
            if isinstance(raw, bool):
                raise ValueError("boolean is not an integer")
            if isinstance(raw, str):
                value = int(raw, 10)
            else:
                value = int(raw)
                if isinstance(raw, float) and not raw.is_integer():
                    raise ValueError("expected an integer")
        elif spec.kind == "number":
            if isinstance(raw, bool):
                raise ValueError("boolean is not a number")
            value = float(raw)
        elif spec.kind == "boolean":
            value = _coerce_bool(raw)
        else:
            raise ValueError(f"unknown kind {spec.kind}")
    except (TypeError, ValueError) as exc:
        raise BadParameter(f"Parameter {spec.name!r} must be a {spec.kind}. Got {raw!r}.") from exc
    if spec.choices and str(value) not in spec.choices:
        listed = ", ".join(spec.choices)
        raise BadParameter(f"Parameter {spec.name!r} must be one of: {listed}. Got {value!r}.")
    return value


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in {0, 1}:
        return bool(raw)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected a boolean")
