"""The contract every Studio plugin implements.

A plugin is a Python object with ``manifest`` and ``invoke``. It registers
capabilities, commands, and configuration. It does not own the MCP transport.
The host passes a gateway only when a command is allowed to touch Studio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


ProgressFn = Callable[[str, float, str], None]


@dataclass(frozen=True)
class ParameterSpec:
    """One configuration key or command argument.

    ``kind`` is ``string``, ``integer``, ``number``, or ``boolean``.
    ``choices`` is empty when any value of that kind is accepted.
    """

    name: str
    kind: str
    summary: str
    default: Any = None
    required: bool = False
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"string", "integer", "number", "boolean"}:
            raise ValueError(f"Parameter {self.name!r} has unknown kind {self.kind!r}")
        if not self.name.isidentifier():
            raise ValueError(f"Parameter name {self.name!r} is not an identifier")


@dataclass(frozen=True)
class CommandSpec:
    """A command an agent or the terminal can run by name."""

    name: str
    summary: str
    mutates_place: bool
    parameters: tuple[ParameterSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"Command name {self.name!r} is not an identifier")
        seen: set[str] = set()
        for param in self.parameters:
            if param.name in seen:
                raise ValueError(f"Command {self.name!r} repeats parameter {param.name!r}")
            seen.add(param.name)


@dataclass(frozen=True)
class PluginManifest:
    """What the host needs in order to list, configure, and invoke a plugin."""

    id: str
    name: str
    version: str
    summary: str
    capabilities: tuple[str, ...]
    commands: tuple[CommandSpec, ...]
    config: tuple[ParameterSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.isidentifier():
            raise ValueError(f"Plugin id {self.id!r} is not an identifier")
        if not self.commands:
            raise ValueError(f"Plugin {self.id!r} must register at least one command")
        names = [command.name for command in self.commands]
        if len(names) != len(set(names)):
            raise ValueError(f"Plugin {self.id!r} repeats a command name")
        config_names = [param.name for param in self.config]
        if len(config_names) != len(set(config_names)):
            raise ValueError(f"Plugin {self.id!r} repeats a config key")

    def command(self, name: str) -> CommandSpec | None:
        for command in self.commands:
            if command.name == name:
                return command
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "capabilities": list(self.capabilities),
            "commands": [
                {
                    "name": command.name,
                    "summary": command.summary,
                    "mutates_place": command.mutates_place,
                    "parameters": [_param_dict(param) for param in command.parameters],
                }
                for command in self.commands
            ],
            "config": [_param_dict(param) for param in self.config],
        }


def _param_dict(param: ParameterSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": param.name,
        "kind": param.kind,
        "summary": param.summary,
        "required": param.required,
    }
    if param.default is not None:
        payload["default"] = param.default
    if param.choices:
        payload["choices"] = list(param.choices)
    return payload


@dataclass
class InvokeContext:
    """Everything a plugin may use during one command.

    ``gateway`` is None until the caller has confirmed a place edit. Read-only
    commands leave it None. ``confirmed`` is true when the person or the agent
    passed the same confirmation the adapter uses for edits.
    """

    config: dict[str, Any]
    gateway: Any | None
    progress: ProgressFn
    confirmed: bool
    home: Path
    plugin_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class StudioPort(Protocol):
    """The slice of the adapter a plugin is allowed to call.

    The host's ``AdapterPort`` is the production implementation. Tests pass
    a fake. Plugins should not import ``StudioClient`` themselves.
    """

    def ensure_edit(self) -> None:
        """Stop a solo playtest so the Edit datamodel can be changed."""

    def execute(self, code: str) -> dict[str, Any]:
        """Run one yielding Luau program and return its JSON object."""

    def apply_instances(self, specs: list[dict[str, Any]]) -> list[str]:
        """Create or update instances through the adapter's chunked apply."""

    def progress(self, stage: str, fraction: float, detail: str = "") -> None:
        """Report progress that the host prints or forwards."""


class Plugin(Protocol):
    """Object registered by an entry point or a ``plugin.json`` file."""

    def manifest(self) -> PluginManifest:
        """Return the static description. Must not touch Studio or the network."""

    def invoke(self, command: str, params: dict[str, Any], *, context: InvokeContext) -> dict[str, Any]:
        """Run one command. Return a JSON-serializable dictionary."""
