"""One open place: studio id, mode, retries, and tool calls."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from roblox_studio_adapter.catalog import Registry, ToolSpec
from roblox_studio_adapter.client import StudioClient
from roblox_studio_adapter.context import Context
from roblox_studio_adapter.errors import (
    AmbiguousOutcome,
    AmbiguousStudioError,
    ModeError,
    NoStudioError,
    RetryExhausted,
    StateParseError,
    StudioConnectionError,
    StudioError,
    TimeoutError,
    ToolFailed,
)
from roblox_studio_adapter.parsers import parse_studio_state, parse_studios
from roblox_studio_adapter.results import StudioInfo, StudioState, ToolResult
from roblox_studio_adapter.retry import backoff_seconds, is_retryable_result

log = logging.getLogger("roblox_studio_adapter")

_READ_ATTEMPTS = 3


class Session:
    def __init__(self, client: StudioClient, context: Context | None = None) -> None:
        self.client = client
        self.context = context or Context()
        self.registry = Registry()
        self.studio_id: str | None = None
        self._state: StudioState | None = None
        self._state_at = 0.0
        self._lock = threading.Lock()
        self._studios: list[StudioInfo] = []
        self.reconnect_hook = None

    def start(self) -> None:
        listed = self.client.list_tools()
        self.registry.refresh(listed)
        self.context.note("tools/list", f"{len(listed)} tools")

    def close(self) -> None:
        self.client.close()

    def reconnect(self) -> None:
        log.info("reconnecting to Studio MCP")
        self.client.close()
        restarted = StudioClient.launch(getattr(self.client.transport, "command", None))
        self.client = restarted
        self.registry.refresh(self.client.list_tools())
        self._state = None

    def list_studios(self) -> list[StudioInfo]:
        result = self.call("list_roblox_studios", {})
        self._studios = parse_studios(result.text)
        return self._studios

    def select(
        self,
        studio_id: str | None = None,
        *,
        place_id: str | None = None,
        name_contains: str | None = None,
    ) -> StudioInfo:
        studios = self.list_studios()
        if studio_id:
            match = next((item for item in studios if item.id == studio_id), None)
            if match is None:
                raise NoStudioError(f"No connected Studio has id {studio_id}.")
            self.studio_id = match.id
            self._state = None
            return match
        narrowed = studios
        if place_id:
            narrowed = [item for item in narrowed if item.place_id == str(place_id)]
        if name_contains:
            needle = name_contains.lower()
            narrowed = [item for item in narrowed if needle in item.name.lower()]
        if len(narrowed) == 1:
            self.studio_id = narrowed[0].id
            self._state = None
            return narrowed[0]
        if not studios:
            raise NoStudioError(
                "No Roblox Studio instance is connected. Open a place and enable the built-in MCP server."
            )
        raise AmbiguousStudioError([{"id": item.id, "name": item.name} for item in narrowed or studios])

    def require_studio(self) -> str:
        if self.studio_id:
            return self.studio_id
        chosen = self.select()
        return chosen.id

    def refresh_state(self, *, force: bool = False) -> StudioState:
        now = time.monotonic()
        if not force and self._state is not None and now - self._state_at < 1.0:
            return self._state
        result = self.call("get_studio_state", {})
        state = parse_studio_state(result.text)
        self._state = state
        self._state_at = time.monotonic()
        if state.unparsed:
            raise StateParseError(state.raw_text)
        return state

    def invalidate_state(self) -> None:
        self._state = None
        self._state_at = 0.0

    def call(
        self,
        name: str,
        arguments: dict | None = None,
        *,
        timeout: float | None = None,
        retry: str | None = None,
        datamodel: str | None = None,
    ) -> ToolResult:
        spec = self._spec(name)
        policy = retry or spec.retry
        if spec.datamodels and (self._state is None or time.monotonic() - self._state_at > 1.0):
            self.refresh_state(force=True)
        prepared = self.prepare(spec, arguments or {}, datamodel=datamodel)
        limit = timeout if timeout is not None else spec.timeout
        with self._lock:
            if policy == "read":
                result = self._read(spec, prepared, limit)
            else:
                result = self._once(spec, prepared, limit, ambiguous_on_drop=spec.mutates or policy == "mutation")
        self._store_images(result)
        self.context.note(name, _summarize(prepared, result))
        if result.is_error:
            raise ToolFailed(name, result.text)
        return result

    def _store_images(self, result: ToolResult) -> None:
        if not result.images:
            return
        import base64

        folder = self.context.artifacts
        folder.mkdir(parents=True, exist_ok=True)
        for image in result.images:
            suffix = "jpg" if "jpeg" in image.mime_type or image.mime_type.endswith("/jpg") else "png"
            path = folder / f"{self.context.next_capture_id()}.{suffix}"
            path.write_bytes(base64.b64decode(image.data_b64))
            result.image_paths.append(str(path))
        result.images.clear()

    def prepare(self, spec: ToolSpec, arguments: dict, *, datamodel: str | None = None) -> dict:
        args = {key: value for key, value in arguments.items() if value is not None}
        if spec.requires_studio_id:
            args["studio_id"] = args.get("studio_id") or self.require_studio()
        if datamodel is not None:
            args["datamodel_type"] = datamodel
        if spec.datamodels and "datamodel_type" not in args:
            chosen = self._choose_datamodel(spec)
            if chosen is None:
                playing = bool(self._state and self._state.playing)
                if playing and spec.datamodels == ("Edit",):
                    raise ModeError(
                        f"{spec.name} only runs in the Edit datamodel. Stop the playtest before editing scripts or the saved place."
                    )
                if not playing and "Edit" not in spec.datamodels:
                    raise ModeError(f"{spec.name} only runs during a playtest ({', '.join(spec.datamodels)}).")
                raise ModeError(
                    f"{spec.name} needs datamodel_type ({', '.join(spec.datamodels)}). "
                    "During a playtest, Client and Server are different copies. Pass the one you mean."
                )
            args["datamodel_type"] = chosen
        if "datamodel_type" in args and spec.datamodels and args["datamodel_type"] not in spec.datamodels:
            raise ModeError(f"{spec.name} does not accept datamodel_type {args['datamodel_type']!r}.")
        return args

    def _choose_datamodel(self, spec: ToolSpec) -> str | None:
        playing = bool(self._state and self._state.playing)
        if not playing:
            if "Edit" in spec.datamodels:
                return "Edit"
            return None
        if spec.datamodels == ("Client",):
            return "Client"
        if spec.datamodels == ("Edit",):
            return None
        return None

    def _read(self, spec: ToolSpec, arguments: dict, timeout: float) -> ToolResult:
        last: BaseException | None = None
        for attempt in range(_READ_ATTEMPTS):
            try:
                result = self.client.call_tool_raw(spec.name, arguments, timeout)
            except (StudioConnectionError, TimeoutError) as exc:
                last = exc
                if attempt == _READ_ATTEMPTS - 1:
                    break
                self._reconnect_quietly()
                time.sleep(backoff_seconds(attempt))
                continue
            if is_retryable_result(result) and attempt < _READ_ATTEMPTS - 1:
                last = ToolFailed(spec.name, result.text)
                time.sleep(backoff_seconds(attempt))
                continue
            return result
        raise RetryExhausted(spec.name, last or ToolFailed(spec.name, "read failed"))

    def _once(self, spec: ToolSpec, arguments: dict, timeout: float, *, ambiguous_on_drop: bool) -> ToolResult:
        try:
            return self.client.call_tool_raw(spec.name, arguments, timeout)
        except TimeoutError as exc:
            if ambiguous_on_drop:
                raise TimeoutError(
                    f"{spec.name} exceeded {timeout:.0f}s. It may still be running in Studio. "
                    "Do not retry a mutation until you have checked the place."
                ) from exc
            raise
        except StudioConnectionError as exc:
            if ambiguous_on_drop:
                self._reconnect_quietly()
                raise AmbiguousOutcome(spec.name) from exc
            raise

    def _spec(self, name: str) -> ToolSpec:
        if self.registry.refreshed:
            return self.registry.get(name)
        found = self.registry.overlay.get(name)
        if found is not None:
            return found
        return self.registry.get(name)

    def _reconnect_quietly(self) -> None:
        if self.reconnect_hook is not None:
            self.reconnect_hook()
            self._state = None
            return
        try:
            command = getattr(self.client.transport, "command", None)
            self.client.close()
            self.client = StudioClient.launch(command)
            self.registry.refresh(self.client.list_tools())
            self._state = None
        except StudioError:
            log.warning("reconnect after a dropped Studio MCP call failed", exc_info=True)


def _summarize(arguments: dict, result: ToolResult) -> str:
    parts = []
    for key, value in arguments.items():
        if key in {"studio_id", "code", "edits", "skill_body", "new_skill_body", "body"}:
            continue
        text = str(value)
        parts.append(f"{key}={text if len(text) < 60 else text[:60] + '…'}")
    status = "error" if result.is_error else f"{len(result.text)} chars"
    if result.images:
        status += f", {len(result.images)} image(s)"
    detail = ", ".join(parts)
    return f"{status}" + (f" ({detail})" if detail else "")


def drop_none(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if value is not None}
