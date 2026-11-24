"""Errors the host raises before a plugin starts its own work."""

from __future__ import annotations


class PluginHostError(Exception):
    """Base type for host failures."""


class PluginNotFound(PluginHostError):
    """No discovered plugin has this id."""

    def __init__(self, plugin_id: str, available: list[str]):
        self.plugin_id = plugin_id
        self.available = available
        listed = ", ".join(available) if available else "(none discovered)"
        super().__init__(f"No plugin named {plugin_id!r}. Discovered: {listed}.")


class NotInstalled(PluginHostError):
    """The plugin is on disk or an entry point, but it has not been installed."""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        super().__init__(
            f"Plugin {plugin_id!r} is not installed. Run `roblox-plugins install {plugin_id}`."
        )


class UnknownCommand(PluginHostError):
    """The plugin does not register this command."""

    def __init__(self, plugin_id: str, command: str, commands: list[str]):
        self.plugin_id = plugin_id
        self.command = command
        listed = ", ".join(commands) if commands else "(none)"
        super().__init__(f"{plugin_id!r} has no command {command!r}. Commands: {listed}.")


class BadParameter(PluginHostError):
    """A config value or command argument does not match the manifest."""

    def __init__(self, message: str):
        super().__init__(message)
