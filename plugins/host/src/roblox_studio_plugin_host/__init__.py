"""Discover, configure, and run plugins that sit on roblox-studio-adapter.

The core adapter does not import this package. Plugins depend on the host.
The host depends on the adapter only when a command actually opens Studio.
"""

from __future__ import annotations

__version__ = "0.1.0"

from roblox_studio_plugin_host.contract import (
    CommandSpec,
    InvokeContext,
    ParameterSpec,
    PluginManifest,
    ProgressFn,
)
from roblox_studio_plugin_host.discovery import discover, load_installed
from roblox_studio_plugin_host.state import PluginHome

__all__ = [
    "CommandSpec",
    "InvokeContext",
    "ParameterSpec",
    "PluginHome",
    "PluginManifest",
    "ProgressFn",
    "__version__",
    "discover",
    "load_installed",
]
