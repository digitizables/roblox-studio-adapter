"""Short memory for one Studio session.

The point is to keep script source, console snapshots, and tool chatter from
swallowing the agent's context window. Images are stored as file paths.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Context:
    max_chars: int = 80_000
    artifacts: Path = field(default_factory=lambda: Path.cwd() / ".studio-adapter" / "artifacts")
    journal_path: Path | None = None
    scripts: dict[str, str] = field(default_factory=dict)
    console_snapshot: str = ""
    events: deque = field(default_factory=lambda: deque(maxlen=40))
    capture_serial: int = 0

    def remember_script(self, path: str, source: str) -> None:
        self.scripts[path] = source
        self._trim_scripts()

    def forget_script(self, path: str) -> None:
        self.scripts.pop(path, None)

    def cached_script(self, path: str) -> str | None:
        return self.scripts.get(path)

    def note(self, tool: str, summary: str) -> None:
        text = summary if len(summary) <= 240 else summary[:240] + "…"
        self.events.append(f"{tool}: {text}")

    def next_capture_id(self) -> str:
        self.capture_serial += 1
        return f"ScreenCapture_{self.capture_serial}"

    def brief(self) -> str:
        """A compact status an agent can paste back into its own context."""
        lines = ["Studio agent memory:"]
        if self.scripts:
            lines.append("Cached scripts:")
            for path in sorted(self.scripts):
                lines.append(f"- {path} ({len(self.scripts[path])} chars)")
        else:
            lines.append("Cached scripts: none")
        if self.events:
            lines.append("Recent calls:")
            lines.extend(f"- {event}" for event in self.events)
        text = "\n".join(lines)
        if len(text) > self.max_chars:
            return text[: self.max_chars] + "\n…(memory brief truncated)"
        return text

    def _trim_scripts(self) -> None:
        total = sum(len(source) for source in self.scripts.values())
        if total <= self.max_chars:
            return
        # Drop the oldest insertions first. dict preserves insertion order.
        for path in list(self.scripts):
            if total <= self.max_chars:
                break
            total -= len(self.scripts.pop(path))
