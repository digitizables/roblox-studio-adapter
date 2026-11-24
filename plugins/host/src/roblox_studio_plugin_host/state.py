"""Install records and per-plugin configuration on disk.

The directory is ``%USERPROFILE%/.roblox-studio-plugins`` unless
``ROBLOX_STUDIO_PLUGIN_HOME`` is set. The open place is not involved.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_home() -> Path:
    override = os.environ.get("ROBLOX_STUDIO_PLUGIN_HOME")
    if override:
        return Path(override)
    return Path.home() / ".roblox-studio-plugins"


@dataclass
class PluginHome:
    """Files the host owns for install state, config, and plugin caches."""

    root: Path

    @classmethod
    def open(cls, root: Path | None = None) -> PluginHome:
        home = cls(root or default_home())
        home.root.mkdir(parents=True, exist_ok=True)
        return home

    @property
    def installed_path(self) -> Path:
        return self.root / "installed.json"

    def config_path(self, plugin_id: str) -> Path:
        return self.root / "config" / f"{plugin_id}.json"

    def cache_dir(self, plugin_id: str) -> Path:
        path = self.root / "cache" / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def read_installed(self) -> dict[str, Any]:
        return _read_json(self.installed_path, {"schema": 1, "plugins": {}})

    def write_installed(self, payload: dict[str, Any]) -> None:
        _write_json(self.installed_path, payload)

    def record_install(self, plugin_id: str, *, version: str, source: str, path: str | None) -> dict[str, Any]:
        payload = self.read_installed()
        plugins = payload.setdefault("plugins", {})
        plugins[plugin_id] = {
            "enabled": True,
            "version": version,
            "source": source,
            "path": path,
            "installed_at": _now(),
        }
        payload["schema"] = 1
        self.write_installed(payload)
        return plugins[plugin_id]

    def record_uninstall(self, plugin_id: str) -> bool:
        payload = self.read_installed()
        plugins = payload.setdefault("plugins", {})
        if plugin_id not in plugins:
            return False
        del plugins[plugin_id]
        self.write_installed(payload)
        return True

    def is_installed(self, plugin_id: str) -> bool:
        record = self.read_installed().get("plugins", {}).get(plugin_id)
        return bool(record and record.get("enabled", True))

    def read_config(self, plugin_id: str) -> dict[str, Any]:
        return _read_json(self.config_path(plugin_id), {})

    def write_config(self, plugin_id: str, values: dict[str, Any]) -> None:
        self.config_path(plugin_id).parent.mkdir(parents=True, exist_ok=True)
        _write_json(self.config_path(plugin_id), values)


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
