"""Viewport screenshots. Image bytes are written under the session artifacts folder."""

from __future__ import annotations

from roblox_studio_adapter.session import Session


class CaptureService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def screenshot(
        self,
        *,
        capture_id: str | None = None,
        position: tuple[float, float, float] | None = None,
        look_at: tuple[float, float, float] | None = None,
    ) -> list[str]:
        """Capture the viewport. Returns file paths, not base64.

        Pass ``position`` and ``look_at`` together when you want a framed
        edit-time shot. Leave both empty during a playtest.
        """
        if (position is None) ^ (look_at is None):
            from roblox_studio_adapter.errors import EditError

            raise EditError("Pass both camera position and look_at, or neither.")
        arguments: dict = {"capture_id": capture_id or self.session.context.next_capture_id()}
        if position is not None and look_at is not None:
            arguments["camera_position"] = list(position)
            arguments["look_at_position"] = list(look_at)
        result = self.session.call("screen_capture", arguments)
        return list(result.image_paths)
