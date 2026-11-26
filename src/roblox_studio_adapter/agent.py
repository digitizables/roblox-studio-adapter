"""Facade an external agent imports."""

from __future__ import annotations

from pathlib import Path

from roblox_studio_adapter.client import StudioClient
from roblox_studio_adapter.context import Context
from roblox_studio_adapter.results import StudioInfo
from roblox_studio_adapter.services.assets import AssetService
from roblox_studio_adapter.services.capture import CaptureService
from roblox_studio_adapter.services.cloud import CloudService
from roblox_studio_adapter.services.datamodel import DataModelService
from roblox_studio_adapter.services.docs import DocsService
from roblox_studio_adapter.services.input_sim import InputService
from roblox_studio_adapter.services.luau import LuauService
from roblox_studio_adapter.services.playtest import PlaytestService
from roblox_studio_adapter.services.scripts import ScriptService
from roblox_studio_adapter.services.skills import SkillService
from roblox_studio_adapter.session import Session
from roblox_studio_adapter.workflows import Loop


class RobloxStudio:
    """A connected Studio place plus the services that sit on its MCP tools.

    Use it as a context manager. One agent talks to one Studio window.
    Calls on a single agent are serialized. Do not share one agent across threads.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.context = session.context
        self.scripts = ScriptService(session)
        self.luau = LuauService(session)
        self.datamodel = DataModelService(session)
        self.capture = CaptureService(session)
        self.playtest = PlaytestService(session)
        self.assets = AssetService(session)
        self.docs = DocsService(session)
        self.cloud = CloudService(session)
        self.skills = SkillService(session)
        self.input = InputService(session)
        self.loop = Loop(self)

    @classmethod
    def connect(
        cls,
        command: list[str] | None = None,
        *,
        artifacts_dir: str | Path | None = None,
        studio_id: str | None = None,
        name_contains: str | None = None,
    ) -> RobloxStudio:
        client = StudioClient.launch(command)
        try:
            context = Context()
            if artifacts_dir is not None:
                context.artifacts = Path(artifacts_dir)
            session = Session(client, context)
            session.start()
            agent = cls(session)
            agent.select(studio_id=studio_id, name_contains=name_contains)
        except Exception:
            client.close()
            raise
        return agent

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> RobloxStudio:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def select(
        self,
        studio_id: str | None = None,
        *,
        place_id: str | None = None,
        name_contains: str | None = None,
    ) -> StudioInfo:
        return self.session.select(studio_id, place_id=place_id, name_contains=name_contains)

    def studios(self) -> list[StudioInfo]:
        return self.session.list_studios()

    def tools(self) -> list[str]:
        return self.session.registry.names()

    def call(self, name: str, arguments: dict | None = None, **kwargs: object):
        """Call any advertised tool, including ones this catalog has never seen."""
        return self.session.call(name, arguments, **kwargs)  # type: ignore[arg-type]

    def save(self, notes: str | None = None):
        """Save the place. Never publishes. Pass notes only when the user asked for a label."""
        from roblox_studio_adapter.errors import NeedsUserAction, ToolFailed
        from roblox_studio_adapter.parsers import parse_save

        result = self.session.call("save_place", {"notes": notes} if notes else {})
        status = parse_save(result.text)
        if status.status == "Busy":
            self.playtest.sleep(1.0)
            result = self.session.call("save_place", {"notes": notes} if notes else {})
            status = parse_save(result.text)
        if status.status == "NeedsUserAction":
            raise NeedsUserAction(status.message)
        if status.status == "Failed":
            raise ToolFailed("save_place", status.message)
        return status

    def feedback(self, text: str) -> str:
        """Send one piece of Studio-tool feedback. This is never called automatically."""
        if len(text.encode("utf-8")) > 4000:
            raise ValueError("Feedback must be at most 4000 bytes, and must not include source, personal data, or credentials.")
        return self.session.call("submit_feedback", {"feedback": text}).text
