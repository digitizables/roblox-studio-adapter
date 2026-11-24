"""Keyboard, mouse, and character movement during a client playtest."""

from __future__ import annotations

from roblox_studio_adapter.errors import EditError, ModeError
from roblox_studio_adapter.keys import KEYBOARD_ACTIONS, MOUSE_ACTIONS, MOUSE_BUTTONS, require_key
from roblox_studio_adapter.services.playtest import PlaytestService
from roblox_studio_adapter.session import Session


class InputService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def press(self, key: str, *, times: int = 1, target: str | None = None, gap_ms: float = 30) -> str:
        require_key(key)
        if times < 1:
            raise EditError("times must be at least 1")
        actions: list[dict] = []
        for index in range(times):
            step: dict = {"action": "keyPress", "key_code": key}
            if target:
                step["instance_path"] = target
            actions.append(step)
            if index != times - 1:
                actions.append({"action": "wait", "wait_time_ms": gap_ms})
        return self._keyboard(actions)

    def type_text(self, text: str, *, target: str | None = None) -> str:
        step: dict = {"action": "textInput", "text_inputs": text}
        if target:
            step["instance_path"] = target
        return self._keyboard([step])

    def click(
        self,
        *,
        instance_path: str | None = None,
        x: float | None = None,
        y: float | None = None,
        button: str = "left",
    ) -> str:
        if button not in MOUSE_BUTTONS:
            raise EditError("mouse button must be 'left' or 'right'")
        if instance_path is None and (x is None or y is None):
            raise EditError("click needs an instance_path or both x and y")
        step: dict = {"action": "mouseButtonClick", "mouse_button": button}
        if instance_path:
            step["instance_path"] = instance_path
        else:
            step["x"] = x
            step["y"] = y
        return self._mouse([step])

    def walk_to(
        self,
        *,
        instance_path: str | None = None,
        position: tuple[float, float, float] | None = None,
        speed: float = 1.0,
    ) -> str:
        if speed < 0.1 or speed > 10:
            raise EditError("speed must be between 0.1 and 10")
        if instance_path is None and position is None:
            raise EditError("walk_to needs an instance_path or a position")
        self._ensure_client()
        arguments: dict = {"speed_multiplier": speed}
        if instance_path:
            arguments["instance_path"] = instance_path
        if position:
            arguments["x"], arguments["y"], arguments["z"] = position
        result = self.session.call("character_navigation", arguments, datamodel="Client")
        return result.text

    def _keyboard(self, actions: list[dict]) -> str:
        for action in actions:
            if action.get("action") not in KEYBOARD_ACTIONS:
                raise EditError(f"Unknown keyboard action {action.get('action')!r}")
            if action.get("action") == "wait":
                wait = action.get("wait_time_ms")
                if wait is None or not 0 <= float(wait) <= 10000:
                    raise EditError("wait_time_ms must be from 0 to 10000")
        self._ensure_client()
        return self.session.call("user_keyboard_input", {"actions": actions}, datamodel="Client").text

    def _mouse(self, actions: list[dict]) -> str:
        for action in actions:
            if action.get("action") not in MOUSE_ACTIONS:
                raise EditError(f"Unknown mouse action {action.get('action')!r}")
        self._ensure_client()
        return self.session.call("user_mouse_input", {"actions": actions}, datamodel="Client").text

    def _ensure_client(self) -> None:
        state = self.session.refresh_state(force=True)
        if not state.playing:
            raise ModeError("Input simulation runs on the Client datamodel. Start a playtest first, or use playtest.run().")
        if "Client" not in state.available and state.mode.lower() != "play":
            PlaytestService(self.session).start()
