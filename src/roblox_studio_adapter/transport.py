"""stdio transport for the Studio MCP process."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import IO

from roblox_studio_adapter.errors import McpRpcError, ProtocolError, StudioConnectionError, TimeoutError
from roblox_studio_adapter.framing import FrameDecoder, encode_message

_CREATE_NO_WINDOW = 0x08000000


def default_command() -> list[str]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise StudioConnectionError("LOCALAPPDATA is not set, so the Studio MCP launcher cannot be found.")
    bat = Path(local) / "Roblox" / "mcp.bat"
    if not bat.is_file():
        raise StudioConnectionError(
            f"Studio MCP launcher not found at {bat}. Install the current Roblox Studio, "
            "then enable Assistant, Manage MCP Servers, Enable Studio as MCP server."
        )
    return ["cmd.exe", "/c", str(bat)]


class StdioTransport:
    """One StudioMCP.exe process, one in-flight request at a time per id."""

    def __init__(self, command: list[str] | None = None) -> None:
        self.command = command or default_command()
        self.proc: subprocess.Popen[bytes] | None = None
        self._decoder = FrameDecoder()
        self._pending: dict[int, queue.Queue[dict]] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr: list[str] = []
        self._closed = False
        self._reader: threading.Thread | None = None
        self._err_reader: threading.Thread | None = None

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self._closed = False
        self._decoder = FrameDecoder()
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise StudioConnectionError(f"Could not start Studio MCP: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, name="studio-mcp-stdout", daemon=True)
        self._err_reader = threading.Thread(target=self._read_stderr, name="studio-mcp-stderr", daemon=True)
        self._reader.start()
        self._err_reader.start()

    def request(self, method: str, params: dict | None, timeout: float) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            raise StudioConnectionError(self._dead_message())
        message_id = self._next_id()
        box: queue.Queue[dict] = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[message_id] = box
        payload: dict = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        try:
            message = box.get(timeout=timeout)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(message_id, None)
            raise TimeoutError(f"{method} did not return within {timeout:.0f}s. {self.stderr_tail()}") from exc
        if "error" in message:
            error = message["error"]
            if not isinstance(error, dict):
                error = {"code": None, "message": str(error)}
            if error.get("code") == -32000:
                raise StudioConnectionError(str(error.get("message") or "Studio MCP connection dropped"))
            raise McpRpcError(error)
        result = message.get("result")
        if not isinstance(result, dict):
            return {"value": result}
        return result

    def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        self._write(payload)

    def close(self) -> None:
        self._closed = True
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
        self._fail_all(StudioConnectionError("Studio MCP transport closed"))

    def stderr_tail(self) -> str:
        if not self._stderr:
            return ""
        return "stderr: " + " | ".join(self._stderr[-4])

    def _next_id(self) -> int:
        with self._lock:
            self._next = getattr(self, "_next", 0) + 1
            return self._next

    def _write(self, payload: dict) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise StudioConnectionError(self._dead_message())
        data = encode_message(payload)
        with self._write_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except OSError as exc:
                raise StudioConnectionError(f"Write to Studio MCP failed: {exc}") from exc

    def _read_stdout(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        stream: IO[bytes] = proc.stdout
        try:
            while not self._closed:
                chunk = stream.read(65536)
                if not chunk:
                    break
                try:
                    messages = self._decoder.feed(chunk)
                except ProtocolError as exc:
                    self._fail_all(exc)
                    return
                for message in messages:
                    self._dispatch(message)
        finally:
            self._fail_all(StudioConnectionError(self._dead_message()))

    def _read_stderr(self) -> None:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr.append(text)
                del self._stderr[:-20]

    def _dispatch(self, message: dict) -> None:
        if "method" in message and "id" in message:
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"roblox-studio-adapter does not implement {message['method']}"},
                }
            )
            return
        message_id = message.get("id")
        if message_id is None:
            return
        with self._lock:
            box = self._pending.pop(message_id, None)
        if box is not None:
            box.put(message)

    def _fail_all(self, exc: BaseException) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for box in pending:
            box.put({"error": {"code": -32000, "message": str(exc)}})

    def _dead_message(self) -> str:
        code = None if self.proc is None else self.proc.poll()
        hint = (
            "Open Roblox Studio with a place, then Assistant, Manage MCP Servers, "
            "and turn on Enable Studio as MCP server."
        )
        tail = self.stderr_tail()
        return f"Studio MCP is not running (exit {code}). {hint} {tail}".strip()
