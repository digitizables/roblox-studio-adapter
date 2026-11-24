"""JSON-RPC client for the Studio MCP server."""

from __future__ import annotations

from typing import Protocol

from roblox_studio_adapter import __version__
from roblox_studio_adapter.errors import McpRpcError, StudioConnectionError
from roblox_studio_adapter.results import ImageBlob, ToolResult
from roblox_studio_adapter.transport import StdioTransport

_PROTOCOL_CANDIDATES = ("2025-06-18", "2025-03-26", "2024-11-05")


class Transport(Protocol):
    def start(self) -> None: ...
    def request(self, method: str, params: dict | None, timeout: float) -> dict: ...
    def notify(self, method: str, params: dict | None = None) -> None: ...
    def close(self) -> None: ...


class StudioClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.protocol: str | None = None
        self.server_info: dict = {}

    @classmethod
    def launch(cls, command: list[str] | None = None) -> StudioClient:
        transport = StdioTransport(command)
        transport.start()
        client = cls(transport)
        client.initialize()
        return client

    def initialize(self) -> dict:
        candidates = list(_PROTOCOL_CANDIDATES)
        tried: set[str] = set()
        last: Exception | None = None
        while candidates:
            version = candidates.pop(0)
            if version in tried:
                continue
            tried.add(version)
            try:
                result = self.transport.request(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": {"name": "roblox-studio-adapter", "version": __version__},
                    },
                    timeout=30,
                )
            except McpRpcError as exc:
                last = exc
                for extra in _supported_versions(exc):
                    if extra not in tried:
                        candidates.append(extra)
                continue
            self.protocol = str(result.get("protocolVersion") or version)
            self.server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
            self.transport.notify("notifications/initialized")
            return result
        raise StudioConnectionError(f"Studio MCP rejected every protocol version tried ({', '.join(tried)}). Last error: {last}")

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict = {}
            if cursor:
                params["cursor"] = cursor
            result = self.transport.request("tools/list", params, timeout=30)
            batch = result.get("tools") or []
            if isinstance(batch, list):
                tools.extend(item for item in batch if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool_raw(self, name: str, arguments: dict, timeout: float) -> ToolResult:
        result = self.transport.request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )
        return _parse_tool_result(name, result)

    def close(self) -> None:
        self.transport.close()


def _parse_tool_result(name: str, result: dict) -> ToolResult:
    content = result.get("content")
    texts: list[str] = []
    images: list[ImageBlob] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                texts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "text":
                texts.append(str(item.get("text") or ""))
            elif kind == "image":
                data = item.get("data")
                if isinstance(data, str) and data:
                    images.append(ImageBlob(data_b64=data, mime_type=str(item.get("mimeType") or "image/png")))
            elif "text" in item:
                texts.append(str(item.get("text") or ""))
    elif isinstance(content, str):
        texts.append(content)
    elif "value" in result:
        texts.append(str(result.get("value")))
    is_error = bool(result.get("isError") or result.get("is_error"))
    return ToolResult(name=name, text="\n".join(texts).strip(), is_error=is_error, images=images, raw=result)


def _supported_versions(exc: McpRpcError) -> list[str]:
    data = exc.error.get("data")
    found: list[str] = []
    if isinstance(data, dict):
        for key in ("supported", "supportedVersions", "versions"):
            value = data.get(key)
            if isinstance(value, list):
                found.extend(str(item) for item in value)
    message = str(exc.error.get("message") or "")
    for candidate in _PROTOCOL_CANDIDATES:
        if candidate in message and candidate not in found:
            found.append(candidate)
    return found
