"""Drive a running Roblox Studio session through its built-in MCP server."""

from __future__ import annotations

__version__ = "0.1.2"

__all__ = ["RobloxStudio", "__version__"]


def __getattr__(name: str):
    if name == "RobloxStudio":
        from roblox_studio_adapter.agent import RobloxStudio

        return RobloxStudio
    raise AttributeError(f"module roblox_studio_adapter has no attribute {name}")
