from __future__ import annotations

import time
import unittest

from roblox_studio_adapter.catalog import static_tools
from roblox_studio_adapter.errors import AmbiguousOutcome, AmbiguousStudioError, ModeError, StudioConnectionError, ToolFailed
from roblox_studio_adapter.results import StudioState, ToolResult
from roblox_studio_adapter.session import Session

_EDIT = "- Current Studio Mode: Edit\n- Available DataModels: Edit\n- Focused DataModel in the viewport: Edit\n"
_PLAY = "- Current Studio Mode: Play\n- Available DataModels: Client, Server\n- Focused DataModel in the viewport: Client\n"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: Exception | None = None
        self.protocol = "test"
        self.transport = type("Transport", (), {"command": ["fake"]})()

    def call_tool_raw(self, name: str, arguments: dict, timeout: float) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if self.fail_with is not None:
            raise self.fail_with
        if name == "get_studio_state":
            return ToolResult(name=name, text=_EDIT)
        if name == "list_roblox_studios":
            return ToolResult(
                name=name,
                text='{"studios":[{"id":"one","name":"Place1","mode":"Edit"},{"id":"two","name":"Other","mode":"Edit"}]}',
            )
        if name == "script_read":
            return ToolResult(name=name, text="1→print('hi')\n")
        return ToolResult(name=name, text='{"ok":true}')

    def list_tools(self) -> list[dict]:
        return [{"name": spec.name, "description": spec.summary, "inputSchema": {"type": "object"}} for spec in static_tools().values() if not spec.documented_only]

    def close(self) -> None:
        return None


class SessionTests(unittest.TestCase):
    def _session(self) -> tuple[Session, FakeClient]:
        client = FakeClient()
        session = Session(client)  # type: ignore[arg-type]
        session.start()
        session.studio_id = "one"
        session._state = StudioState(mode="Edit", available=("Edit",), focused="Edit", playing=False, raw_text=_EDIT)
        session._state_at = time.monotonic()
        return session, client

    def test_injects_studio_and_edit_datamodel(self) -> None:
        session, client = self._session()
        session.call("search_game_tree", {"path": "Workspace", "max_depth": 2})
        name, args = client.calls[-1]
        self.assertEqual(name, "search_game_tree")
        self.assertEqual(args["studio_id"], "one")
        self.assertEqual(args["datamodel_type"], "Edit")

    def test_refuses_script_edit_while_playing(self) -> None:
        session, _client = self._session()
        session._state = StudioState(mode="Play", available=("Client", "Server"), focused="Client", playing=True, raw_text=_PLAY)
        with self.assertRaises(ModeError):
            session.call("multi_edit", {"file_path": "game.ServerScriptService.A", "edits": []})

    def test_does_not_guess_client_or_server(self) -> None:
        session, _client = self._session()
        session._state = StudioState(mode="Play", available=("Client", "Server"), focused="Client", playing=True, raw_text=_PLAY)
        with self.assertRaises(ModeError):
            session.call("execute_luau", {"code": "return 1"})

    def test_mutation_drop_is_ambiguous_and_does_not_repeat(self) -> None:
        session, client = self._session()
        client.fail_with = StudioConnectionError("dropped")
        session.reconnect_hook = lambda: None
        with self.assertRaises(AmbiguousOutcome):
            session.call("execute_luau", {"code": "return 1"}, datamodel="Edit")
        self.assertEqual(len(client.calls), 1)

    def test_ambiguous_studios(self) -> None:
        session, _client = self._session()
        session.studio_id = None
        with self.assertRaises(AmbiguousStudioError):
            session.select()

    def test_tool_error_is_not_retried_when_it_is_a_real_failure(self) -> None:
        session, client = self._session()

        def boom(_name: str, _arguments: dict, _timeout: float) -> ToolResult:
            return ToolResult(name="script_read", text="Script was not found", is_error=True)

        client.call_tool_raw = boom  # type: ignore[method-assign]
        with self.assertRaises(ToolFailed):
            session.call("script_read", {"target_file": "game.ServerScriptService.Missing"})


if __name__ == "__main__":
    unittest.main()
