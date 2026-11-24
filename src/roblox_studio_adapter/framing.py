"""Decode MCP stdio frames.

Roblox's StudioMCP.exe speaks newline-delimited JSON (there is no
Content-Length string in the binary). The decoder also accepts LSP-style
Content-Length frames so a later Studio build does not break the client.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from roblox_studio_adapter.errors import ProtocolError


class FrameDecoder:
    """Pull complete JSON objects out of a byte stream."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        if data:
            self.buf.extend(data)
        return self._pull()

    def _pull(self) -> list[dict]:
        messages: list[dict] = []
        while self.buf:
            self._strip_ws()
            if not self.buf:
                break
            if self.buf.lower().startswith(b"content-length"):
                message = self._pull_length_frame()
                if message is None:
                    break
                messages.append(message)
                continue
            text, complete = self._decode_available()
            if text is None:
                break
            try:
                value, end = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError as exc:
                if _incomplete(exc, text):
                    break
                raise ProtocolError(f"Invalid JSON from Studio MCP: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ProtocolError("Studio MCP message was not a JSON object")
            raw = text[:end].encode("utf-8")
            del self.buf[: len(raw)]
            if not complete and len(raw) > len(self.buf):
                raise ProtocolError("Frame decoder lost bytes while splitting UTF-8")
            messages.append(value)
        return messages

    def _strip_ws(self) -> None:
        index = 0
        while index < len(self.buf) and self.buf[index] in b" \t\r\n":
            index += 1
        if index:
            del self.buf[:index]

    def _decode_available(self) -> tuple[str | None, bool]:
        try:
            return self.buf.decode("utf-8"), True
        except UnicodeDecodeError:
            pass
        for cut in range(len(self.buf) - 1, max(-1, len(self.buf) - 5), -1):
            try:
                return self.buf[:cut].decode("utf-8"), False
            except UnicodeDecodeError:
                continue
        return None, False

    def _pull_length_frame(self) -> dict | None:
        separator = self.buf.find(b"\r\n\r\n")
        if separator < 0:
            return None
        header = self.buf[:separator].decode("ascii", errors="replace")
        length: int | None = None
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None:
            raise ProtocolError("Content-Length frame is missing its length")
        start = separator + 4
        if len(self.buf) < start + length:
            return None
        body = bytes(self.buf[start : start + length])
        del self.buf[: start + length]
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Invalid Content-Length body: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ProtocolError("Content-Length body was not a JSON object")
        return value


def encode_message(payload: dict) -> bytes:
    """Encode one JSON-RPC message as a single NDJSON line."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _incomplete(exc: json.JSONDecodeError, text: str) -> bool:
    if "Unterminated" in exc.msg or "Expecting value" in exc.msg and exc.pos >= len(text):
        return True
    if exc.pos >= len(text):
        return True
    if "Expecting" in exc.msg and exc.pos >= max(0, len(text) - 1):
        return True
    return False


def iter_messages(chunks: Iterator[bytes]) -> Iterator[dict]:
    decoder = FrameDecoder()
    for chunk in chunks:
        yield from decoder.feed(chunk)
