"""Expose the adapter as an MCP server over stdio.

The adapter is a client of Studio's built-in MCP server. This module turns it
around: an MCP host (Claude Code, another agent) launches

    python -m roblox_studio_adapter mcp

and gets the adapter's higher-level tools instead of Studio's raw ones:
playtests that return evidence, chunked instance creation, script writes that
stop play first, screenshots as real images, and a Rojo project sync.

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout, as MCP's stdio
transport specifies. Nothing but protocol frames is written to stdout; logs go
to stderr. Standard library only, like the rest of the package.

The Studio connection is lazy. The first tool call connects. A dropped pipe is
reconnected on the next call. Writes are never retried here; the adapter's own
policy applies (an ambiguous write raises ``AmbiguousOutcome``).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roblox_studio_adapter import __version__

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "roblox-studio-adapter"

ENABLE_HINT = (
    "No Roblox Studio window is offering itself to MCP. In Studio: Assistant → … → "
    "Manage MCP Servers → Enable Studio as MCP server. Then call studio_status again."
)


def _log(message: str) -> None:
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


def _artifacts_dir() -> Path:
    configured = os.environ.get("ROBLOX_STUDIO_ARTIFACTS")
    if configured:
        return Path(configured)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "roblox-studio-adapter" / "artifacts"


class Connection:
    """One lazily opened RobloxStudio, reopened after a dropped pipe."""

    def __init__(self, factory: Callable[[], Any] | None = None) -> None:
        self._factory = factory or self._connect
        self._agent: Any = None

    @staticmethod
    def _connect() -> Any:
        from roblox_studio_adapter.agent import RobloxStudio

        return RobloxStudio.connect(
            artifacts_dir=_artifacts_dir(),
            name_contains=os.environ.get("ROBLOX_STUDIO_NAME") or None,
        )

    def agent(self) -> Any:
        if self._agent is None:
            self._agent = self._factory()
        return self._agent

    def drop(self) -> None:
        if self._agent is not None:
            try:
                self._agent.close()
            except Exception:  # closing a dead pipe can fail; nothing to recover
                pass
        self._agent = None


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[Any, dict[str, Any]], list[dict[str, Any]]]
    # Read-only tools may connect without a selected window, so they can report why.
    read_only: bool = False


def _text(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    return [{"type": "text", "text": json.dumps(value, indent=2, default=_plain_default)}]


def _plain_default(value: Any) -> Any:
    from roblox_studio_adapter.results import plain

    converted = plain(value)
    if converted is value:
        return str(value)
    return converted


def _images(paths: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for path in paths:
        file = Path(path)
        if not file.is_file():
            continue
        mime = "image/jpeg" if file.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        blocks.append({"type": "image", "data": base64.b64encode(file.read_bytes()).decode("ascii"), "mimeType": mime})
    return blocks


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_STRS = {"type": "array", "items": {"type": "string"}}
_DATAMODEL = {"type": "string", "enum": ["Edit", "Server", "Client"],
              "description": "Which datamodel during play. Leave empty in Edit mode."}


# --- handlers -------------------------------------------------------------


def _status(agent: Any, _: dict[str, Any]) -> list[dict[str, Any]]:
    state = agent.playtest.state()
    registry = agent.session.registry
    return _text({
        "studios": [{"name": s.name, "id": s.id, "mode": s.mode, "place_id": s.place_id} for s in agent.studios()],
        "state": {"mode": state.mode, "playing": state.playing, "available": list(state.available)},
        "tools_advertised": len(registry.names()),
        "catalog_missing": registry.missing_from_live(),
        "no_overlay": registry.unknown_to_overlay(),
    })


def _tree(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    page = agent.datamodel.tree(
        args.get("path") or None,
        instance_type=args.get("instance_type"),
        keywords=args.get("keywords"),
        max_depth=int(args.get("depth", 2)),
        head_limit=int(args.get("head_limit", 120)),
        datamodel=args.get("datamodel"),
    )
    rows = [f"{n.full_path} [{n.class_name}]" + (f"  ({n.child_summary})" if n.child_summary else "") for n in page.nodes]
    header = f"{len(rows)} nodes" + (" (truncated)" if page.truncated else "") + (f" — {page.note}" if page.note else "")
    return _text(header + "\n" + "\n".join(rows))


def _inspect(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    path = args["path"]
    names = args.get("properties") or []
    if names:
        return _text(agent.datamodel.read_properties(path, names, datamodel=args.get("datamodel")))
    result = agent.datamodel.inspect(path)
    return _text({"matches": result.matches, "truncated": result.truncated_matches})


def _luau(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    text = agent.luau.run(
        args["code"],
        datamodel=args.get("datamodel"),
        allow_unyielding=bool(args.get("allow_unyielding", False)),
        timeout=args.get("timeout"),
    )
    return _text(text or "(no output)")


def _script_read(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    start, end = args.get("start"), args.get("end")
    document = agent.scripts.read(args["path"], start=start, end=end)
    return _text(document.source)


def _script_write(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    result = agent.scripts.write(args["path"], args["source"], class_name=args.get("class_name") or "auto")
    return _text(result)


def _script_replace(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    result = agent.scripts.replace(args["path"], args["old"], args["new"], replace_all=bool(args.get("replace_all")))
    return _text(result)


def _apply(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    made = agent.datamodel.apply(args["instances"], chunk_size=int(args.get("chunk_size", 50)),
                                 datamodel=args.get("datamodel"))
    return _text({"created_or_updated": made})


def _destroy(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    return _text({"destroyed": agent.datamodel.destroy(args["path"], datamodel=args.get("datamodel"))})


def _playtest(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    from roblox_studio_adapter.evidence import evidence_record

    report = agent.playtest.run(
        seconds=float(args.get("seconds", 4)),
        screenshot=bool(args.get("screenshot", True)),
        stop=bool(args.get("stop", True)),
        expect_contains=args.get("expect_contains") or None,
        expect_absent=args.get("expect_absent") or None,
        forbid_errors=bool(args.get("forbid_errors", True)),
        probes=args.get("probes") or None,
    )
    return _text(evidence_record(report)) + _images(report.screenshots)


def _screenshot(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    position = args.get("position")
    look_at = args.get("look_at")
    paths = agent.capture.screenshot(
        position=tuple(position) if position else None,
        look_at=tuple(look_at) if look_at else None,
    )
    blocks = _images(paths)
    return blocks or _text("Studio returned no image.")


def _console(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    if args.get("since_last", True):
        delta = agent.playtest.console_since_snapshot()
        return _text(delta.text or "(no new output)")
    return _text(agent.playtest.console())


def _play(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    if args.get("start", True):
        agent.playtest.start()
    else:
        agent.playtest.stop()
    state = agent.playtest.state()
    return _text({"mode": state.mode, "playing": state.playing})


def _rojo_sync(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    from roblox_studio_adapter.rojo_sync import sync

    project = Path(args.get("project_dir") or os.environ.get("ROJO_PROJECT_DIR") or os.getcwd())
    dry_run = bool(args.get("dry_run"))
    # A dry run only reads the Edit datamodel, which exists during play. Only a real write needs Edit mode.
    if not dry_run and agent.playtest.state().playing:
        agent.playtest.stop()
    report = sync(agent, project, dry_run=dry_run, prune=bool(args.get("prune")), force=bool(args.get("force")))
    return _text({"summary": report.summary(), "report": report})


def _raw(agent: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {}
    if args.get("datamodel"):
        kwargs["datamodel"] = args["datamodel"]
    if args.get("timeout"):
        kwargs["timeout"] = float(args["timeout"])
    result = agent.call(args["tool"], args.get("arguments") or {}, **kwargs)
    blocks = _text(result.text or "(empty)")
    return blocks + _images(list(getattr(result, "image_paths", []) or []))


def _brief(agent: Any, _: dict[str, Any]) -> list[dict[str, Any]]:
    return _text(agent.context.brief())


TOOLS: list[Tool] = [
    Tool("studio_status", "Which Studio window is connected, its play mode, and tool coverage. Read-only. "
         "Call first; it explains how to enable Studio's MCP server if nothing is connected.",
         _obj({}), _status, read_only=True),
    Tool("tree", "Shallow page of the instance tree under a path such as 'Workspace' or "
         "'ReplicatedStorage.JetpackMania' (no 'game.' prefix). Read-only.",
         _obj({"path": _STR, "depth": _INT, "keywords": _STR, "instance_type": _STR, "head_limit": _INT,
               "datamodel": _DATAMODEL}), _tree, read_only=True),
    Tool("inspect", "One instance's properties, attributes, and children. Pass 'properties' to read named "
         "properties through Luau when inspect returns none. Path has no 'game.' prefix. Read-only.",
         _obj({"path": _STR, "properties": _STRS, "datamodel": _DATAMODEL}, ["path"]), _inspect, read_only=True),
    Tool("luau", "Run Luau in Studio (execute_luau). Return a value to see it. Refuses code that looks like it "
         "would stall the main thread unless allow_unyielding is true. Edits made in Edit mode persist in the place.",
         _obj({"code": _STR, "datamodel": _DATAMODEL, "allow_unyielding": _BOOL, "timeout": _NUM}, ["code"]), _luau),
    Tool("script_read", "Read a script. Path like 'game.ServerScriptService.Main'. Read-only.",
         _obj({"path": _STR, "start": _INT, "end": _INT}, ["path"]), _script_read, read_only=True),
    Tool("script_write", "Create a script or replace its whole source. Stops a running playtest first. "
         "class_name: Script, LocalScript, ModuleScript, or auto.",
         _obj({"path": _STR, "source": _STR, "class_name": _STR}, ["path", "source"]), _script_write),
    Tool("script_replace", "Replace one exact snippet in a script; refuses ambiguous matches.",
         _obj({"path": _STR, "old": _STR, "new": _STR, "replace_all": _BOOL}, ["path", "old", "new"]), _script_replace),
    Tool("apply_instances", "Create or update instances in chunks. Each item: {parent, name, class_name, "
         "properties?, attributes?}. Vector3 as {x,y,z}, Color3 as {r,g,b} 0-1, enums as 'Enum.Material.Metal'.",
         _obj({"instances": {"type": "array", "items": {"type": "object"}}, "chunk_size": _INT,
               "datamodel": _DATAMODEL}, ["instances"]), _apply),
    Tool("destroy", "Destroy one instance (not a service). Path has no 'game.' prefix.",
         _obj({"path": _STR, "datamodel": _DATAMODEL}, ["path"]), _destroy),
    Tool("playtest", "Solo playtest: play for N seconds, run probes, screenshot, stop. Returns a "
         "roblox-studio-adapter.evidence/1 record (passed, failures, console excerpt, probe values) plus the image. "
         "probes: [{id, expression, datamodel: Server|Client, equals?}].",
         _obj({"seconds": _NUM, "expect_contains": _STRS, "expect_absent": _STRS, "forbid_errors": _BOOL,
               "probes": {"type": "array", "items": {"type": "object"}}, "screenshot": _BOOL, "stop": _BOOL}),
         _playtest),
    Tool("play", "Start (start=true) or stop (start=false) a solo playtest and leave it in that state.",
         _obj({"start": _BOOL}), _play),
    Tool("screenshot", "Capture the viewport as an image. In Edit mode pass position and look_at "
         "([x,y,z] each) to frame a shot; during play leave both empty.",
         _obj({"position": {"type": "array", "items": _NUM}, "look_at": {"type": "array", "items": _NUM}}),
         _screenshot, read_only=True),
    Tool("console", "Studio Output. since_last (default true) returns only lines since the previous call.",
         _obj({"since_last": _BOOL}), _console, read_only=True),
    Tool("rojo_sync", "Write every changed script of a Rojo project into the open place (Edit mode) using "
         "'rojo sourcemap'. If 'rojo serve' is serving the same project it already syncs; the write is "
         "refused unless force. project_dir defaults to ROJO_PROJECT_DIR or the server's working directory. "
         "dry_run compares sources and lists created/updated/unchanged without stopping a playtest; "
         "prune deletes Studio scripts under managed folders that Git lacks.",
         _obj({"project_dir": _STR, "dry_run": _BOOL, "prune": _BOOL, "force": _BOOL}), _rojo_sync),
    Tool("studio_call", "Call any raw Studio MCP tool by name (escape hatch). 'arguments' is passed through.",
         _obj({"tool": _STR, "arguments": {"type": "object"}, "datamodel": _DATAMODEL, "timeout": _NUM}, ["tool"]),
         _raw),
    Tool("context_brief", "The adapter's compact memory of this session (cached scripts, recent calls).",
         _obj({}), _brief, read_only=True),
]


class Server:
    def __init__(self, connection: Connection | None = None, tools: list[Tool] | None = None) -> None:
        self.connection = connection or Connection()
        self.tools = {tool.name: tool for tool in (tools or TOOLS)}

    # JSON-RPC ---------------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        is_request = "id" in message
        if not isinstance(method, str):
            if is_request:
                return _error(request_id, -32600, "Invalid request")
            return None
        try:
            if method == "initialize":
                result = self._initialize(message.get("params") or {})
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [self._describe(tool) for tool in self.tools.values()]}
            elif method == "tools/call":
                result = self._call(message.get("params") or {})
            elif method.startswith("notifications/"):
                return None
            else:
                return _error(request_id, -32601, f"Method not found: {method}") if is_request else None
        except Exception as exc:  # protocol-level failure, not a tool failure
            _log(traceback.format_exc())
            return _error(request_id, -32603, f"{type(exc).__name__}: {exc}") if is_request else None
        return {"jsonrpc": "2.0", "id": request_id, "result": result} if is_request else None

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": (
                "Drives the open Roblox Studio window. Call studio_status first. "
                "Edit-mode changes persist in the place but are not saved; nothing here saves or publishes. "
                "For Rojo projects, run rojo_sync before playtest so Studio has the Git code."
            ),
        }

    @staticmethod
    def _describe(tool: Tool) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.schema,
            "annotations": {"readOnlyHint": tool.read_only},
        }

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return _tool_error(f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _tool_error("arguments must be an object")
        from roblox_studio_adapter.errors import NoStudioError, StudioConnectionError

        for attempt in (1, 2):
            try:
                agent = self.connection.agent()
                return {"content": tool.handler(agent, arguments), "isError": False}
            except NoStudioError:
                self.connection.drop()
                return _tool_error(ENABLE_HINT)
            except StudioConnectionError as exc:
                self.connection.drop()
                # Reconnect once for read-only tools. A write may already have landed.
                if attempt == 1 and tool.read_only:
                    _log(f"reconnecting after: {exc}")
                    continue
                return _tool_error(f"StudioConnectionError: {exc}. The connection was reset; "
                                   "read back before repeating a write.")
            except Exception as exc:
                _log(traceback.format_exc())
                return _tool_error(f"{type(exc).__name__}: {exc}")
        return _tool_error("unreachable")

    # stdio loop -----------------------------------------------------------

    def serve(self, stdin: Any = None, stdout: Any = None) -> None:
        source = stdin or sys.stdin
        sink = stdout or sys.stdout
        _log(f"ready (v{__version__}, {len(self.tools)} tools)")
        try:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    _write(sink, _error(None, -32700, "Parse error"))
                    continue
                batch = message if isinstance(message, list) else [message]
                replies = [reply for item in batch if isinstance(item, dict) for reply in [self.handle(item)] if reply]
                if isinstance(message, list):
                    if replies:
                        _write(sink, replies)
                else:
                    for reply in replies:
                        _write(sink, reply)
        finally:
            self.connection.drop()


def _write(sink: Any, payload: Any) -> None:
    sink.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sink.flush()


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, OSError):
        pass
    Server().serve()
    return 0
