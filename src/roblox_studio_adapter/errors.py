"""Errors raised by the Studio compatibility layer.

Tool failures stay distinguishable from connection loss, from an edit that
may already have landed, and from a state that needs the person at the keyboard.
"""

from __future__ import annotations


class StudioError(Exception):
    """Base type for every error this package raises on purpose."""


class StudioConnectionError(StudioError):
    """The MCP process could not be started, or it died before a call was sent."""


class ProtocolError(StudioError):
    """Bytes from the MCP server were not a JSON-RPC message."""


class McpRpcError(StudioError):
    """The server returned a JSON-RPC error object."""

    def __init__(self, error: dict):
        self.error = error
        self.code = error.get("code")
        message = error.get("message", "MCP request failed")
        super().__init__(f"{message} (code {self.code})")


class ToolFailed(StudioError):
    """A tool ran and reported failure. The call was not applied, or the server said so."""

    def __init__(self, tool: str, detail: str):
        self.tool = tool
        self.detail = detail
        super().__init__(f"{tool} failed: {detail}")


class AmbiguousOutcome(StudioError):
    """A mutating call was sent, then the connection dropped before a result arrived.

    The edit, playtest toggle, or generation may have been applied. Read the
    place again before repeating the call.
    """

    def __init__(self, tool: str):
        self.tool = tool
        super().__init__(
            f"{tool} was sent, then the MCP connection dropped before a result arrived. "
            "It may already have been applied. Re-read the place before retrying."
        )


class RetryExhausted(StudioError):
    """A read was retried and still failed."""

    def __init__(self, tool: str, last: BaseException):
        self.tool = tool
        self.last = last
        super().__init__(f"{tool} failed after retries: {last}")


class NoStudioError(StudioError):
    """No Studio window is connected to the MCP server."""


class AmbiguousStudioError(StudioError):
    """More than one Studio is open, and the caller did not choose one."""

    def __init__(self, studios: list):
        self.studios = studios
        lines = [f"{item.get('name', '?')} ({item.get('id', '?')})" for item in studios]
        super().__init__(
            "More than one Roblox Studio is connected. Choose one with "
            "agent.select(studio_id=...) or agent.select(name_contains=...). Open windows: "
            + "; ".join(lines)
        )


class ModeError(StudioError):
    """The tool cannot run in the current play or edit mode."""


class StateParseError(StudioError):
    """get_studio_state returned text this layer does not understand yet."""

    def __init__(self, raw: str):
        self.raw = raw
        super().__init__(f"Could not parse Studio state. Raw response:\n{raw}")


class ParseError(StudioError):
    """A tool result did not match the shape this layer understands."""


class EditError(StudioError):
    """A script edit was refused locally, before Studio saw it."""


class NeedsUserAction(StudioError):
    """Studio can only finish this through a dialog the agent cannot click."""


class ToolUnavailable(StudioError):
    """The static catalog knows this tool, but this Studio build did not advertise it."""


class PermissionDenied(StudioError):
    """Open Cloud or a script capability was not granted for this game."""


class HighRiskRefused(StudioError):
    """A cloud call looks like it publishes, spends, bans, or writes live player data.

    Pass allow_high_risk=True after the person who owns the game has agreed.
    """


class UnyieldingLuau(StudioError):
    """The Luau snippet can freeze Studio's main thread."""


class TimeoutError(StudioError):
    """A call or a polled job exceeded its deadline."""
