"""Adapter-backed Studio port.

Imported only when a command is about to edit the open place. Listing plugins
does not start ``StudioMCP.exe``.
"""

from __future__ import annotations

from typing import Any

from roblox_studio_plugin_host.contract import ProgressFn


class AdapterPort:
    """Wrap one connected ``RobloxStudio`` agent.

    Voxel writes and instance batches go through the adapter's existing Luau
    and datamodel services, including their chunking and main-thread yield.
    """

    def __init__(self, agent: Any, progress: ProgressFn | None = None) -> None:
        self.agent = agent
        self._progress = progress or (lambda stage, fraction, detail: None)

    def ensure_edit(self) -> None:
        state = self.agent.playtest.state()
        if state.playing:
            self.agent.playtest.stop()

    def execute(self, code: str) -> dict[str, Any]:
        payload = self.agent.luau.run_json(code, datamodel="Edit", allow_unyielding=True)
        if isinstance(payload, str):
            raise RuntimeError(f"Studio returned text instead of JSON: {payload[:300]}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Studio returned {type(payload).__name__}, expected a JSON object")
        if payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or payload))
        return payload

    def apply_instances(self, specs: list[dict[str, Any]]) -> list[str]:
        return self.agent.datamodel.apply(specs, chunk_size=40, datamodel="Edit")

    def progress(self, stage: str, fraction: float, detail: str = "") -> None:
        self._progress(stage, fraction, detail)


def connect_port(
    progress: ProgressFn | None = None,
    *,
    studio_id: str | None = None,
    name_contains: str | None = None,
) -> tuple[Any, AdapterPort]:
    """Open the adapter and return ``(agent, port)``. The caller closes the agent."""
    from roblox_studio_adapter import RobloxStudio

    agent = RobloxStudio.connect(studio_id=studio_id, name_contains=name_contains)
    return agent, AdapterPort(agent, progress)
