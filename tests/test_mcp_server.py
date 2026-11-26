"""MCP server protocol, error mapping, and the Rojo sourcemap reader. No Studio needed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from roblox_studio_adapter.errors import NoStudioError, StudioConnectionError
from roblox_studio_adapter.mcp_server import TOOLS, Connection, Server, Tool
from roblox_studio_adapter.rojo_sync import managed_roots, rojo_serve_project, script_rows, studio_scripts_luau, sync

ROOT = Path(__file__).resolve().parents[1]


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class ProtocolTests(unittest.TestCase):
    def test_initialize_echoes_a_supported_version(self) -> None:
        server = Server(Connection(factory=lambda: None))
        reply = server.handle(_request("initialize", {"protocolVersion": "2025-03-26"}))
        assert reply is not None
        self.assertEqual(reply["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", reply["result"]["capabilities"])

    def test_initialize_falls_back_on_an_unknown_version(self) -> None:
        reply = Server(Connection(factory=lambda: None)).handle(_request("initialize", {"protocolVersion": "1999-01-01"}))
        assert reply is not None
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")

    def test_notifications_get_no_reply(self) -> None:
        server = Server(Connection(factory=lambda: None))
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_is_32601(self) -> None:
        reply = Server(Connection(factory=lambda: None)).handle(_request("bogus/method"))
        assert reply is not None
        self.assertEqual(reply["error"]["code"], -32601)

    def test_tools_list_has_schemas_and_unique_names(self) -> None:
        reply = Server(Connection(factory=lambda: None)).handle(_request("tools/list"))
        assert reply is not None
        tools = reply["result"]["tools"]
        names = [tool["name"] for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])
        self.assertIn("rojo_sync", names)
        self.assertIn("playtest", names)


class CallTests(unittest.TestCase):
    def test_no_studio_returns_the_enable_hint_as_a_tool_error(self) -> None:
        def factory():
            raise NoStudioError("none")

        reply = Server(Connection(factory=factory)).handle(_request("tools/call", {"name": "studio_status"}))
        assert reply is not None
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("Enable Studio as MCP server", reply["result"]["content"][0]["text"])

    def test_read_only_tool_reconnects_once_after_a_dropped_pipe(self) -> None:
        made: list[int] = []
        calls = {"n": 0}

        def factory():
            made.append(1)
            return SimpleNamespace(close=lambda: None)

        def handler(_agent, _args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise StudioConnectionError("pipe dropped")
            return [{"type": "text", "text": "ok"}]

        tool = Tool("probe", "test", {"type": "object"}, handler, read_only=True)
        reply = Server(Connection(factory=factory), tools=[tool]).handle(_request("tools/call", {"name": "probe"}))
        assert reply is not None
        self.assertFalse(reply["result"]["isError"])
        self.assertEqual(len(made), 2, "a dropped pipe should reconnect")

    def test_write_tool_is_not_retried_after_a_dropped_pipe(self) -> None:
        calls = {"n": 0}

        def handler(_agent, _args):
            calls["n"] += 1
            raise StudioConnectionError("pipe dropped")

        tool = Tool("write", "test", {"type": "object"}, handler, read_only=False)
        server = Server(Connection(factory=lambda: SimpleNamespace(close=lambda: None)), tools=[tool])
        reply = server.handle(_request("tools/call", {"name": "write"}))
        assert reply is not None
        self.assertTrue(reply["result"]["isError"])
        self.assertEqual(calls["n"], 1, "a write may have landed; never resend it")
        self.assertIn("read back", reply["result"]["content"][0]["text"])

    def test_handler_exceptions_become_tool_errors(self) -> None:
        def handler(_agent, _args):
            raise ValueError("bad input")

        tool = Tool("boom", "test", {"type": "object"}, handler)
        server = Server(Connection(factory=lambda: SimpleNamespace(close=lambda: None)), tools=[tool])
        reply = server.handle(_request("tools/call", {"name": "boom"}))
        assert reply is not None
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("ValueError: bad input", reply["result"]["content"][0]["text"])

    def test_every_catalog_tool_has_a_handler(self) -> None:
        for tool in TOOLS:
            self.assertTrue(callable(tool.handler), tool.name)


SOURCEMAP = {
    "name": "Game",
    "className": "DataModel",
    "filePaths": ["default.project.json"],
    "children": [
        {
            "name": "ReplicatedStorage",
            "className": "ReplicatedStorage",
            "children": [
                {
                    "name": "Shared",
                    "className": "Folder",
                    "children": [
                        {"name": "Rules", "className": "ModuleScript", "filePaths": ["src/shared/Rules.luau"]},
                        {
                            "name": "Inputs",
                            "className": "ModuleScript",
                            "filePaths": ["src/shared/Inputs/init.luau"],
                            "children": [
                                {"name": "Keys", "className": "ModuleScript", "filePaths": ["src/shared/Inputs/Keys.luau"]}
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "name": "ServerScriptService",
            "className": "ServerScriptService",
            "children": [
                {
                    "name": "Server",
                    "className": "Folder",
                    "children": [{"name": "Main", "className": "Script", "filePaths": ["src/server/Main.server.luau"]}],
                }
            ],
        },
    ],
}


class RojoSyncTests(unittest.TestCase):
    def test_script_rows_map_paths_classes_and_files(self) -> None:
        project = Path("C:/proj")
        rows = {row.path: row for row in script_rows(SOURCEMAP, project)}
        self.assertEqual(
            set(rows),
            {
                "game.ReplicatedStorage.Shared.Rules",
                "game.ReplicatedStorage.Shared.Inputs",
                "game.ReplicatedStorage.Shared.Inputs.Keys",
                "game.ServerScriptService.Server.Main",
            },
        )
        self.assertEqual(rows["game.ServerScriptService.Server.Main"].class_name, "Script")
        self.assertTrue(str(rows["game.ReplicatedStorage.Shared.Inputs"].file).endswith("init.luau"))

    def test_managed_roots_are_directory_folders(self) -> None:
        self.assertEqual(
            managed_roots(SOURCEMAP),
            ["game.ReplicatedStorage.Shared", "game.ServerScriptService.Server"],
        )

    def test_studio_scripts_luau_quotes_roots(self) -> None:
        code = studio_scripts_luau(["game.ReplicatedStorage.Shared"])
        self.assertIn('"ReplicatedStorage.Shared"', code)
        self.assertIn("LuaSourceContainer", code)

    def test_sync_writes_changes_recreates_class_flips_and_reports_stale(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            for relative, text in {
                "src/shared/Rules.luau": "return 1\r\n",
                "src/shared/Inputs/init.luau": "return {}\n",
                "src/shared/Inputs/Keys.luau": "return 2\n",
                "src/server/Main.server.luau": "print('hi')\n",
            }.items():
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))

            writes: list[tuple[str, str, str]] = []
            destroyed: list[str] = []

            def write(path, source, class_name=None):
                writes.append((path, source, class_name))
                return SimpleNamespace(created=path.endswith("Keys"), unchanged=path.endswith("Inputs"))

            agent = SimpleNamespace(
                luau=SimpleNamespace(run_json=lambda *a, **k: {
                    "ReplicatedStorage.Shared.Rules": "Script",  # class flipped to ModuleScript in Git
                    "ReplicatedStorage.Shared.Inputs": "ModuleScript",
                    "ServerScriptService.Server.Main": "Script",
                    "ServerScriptService.Server.Old": "Script",  # gone from Git
                }),
                scripts=SimpleNamespace(write=write),
                datamodel=SimpleNamespace(destroy=lambda path, datamodel=None: destroyed.append(path)),
                context=SimpleNamespace(forget_script=lambda path: None),
            )
            report = sync(agent, project, sourcemap=SOURCEMAP, serve_probe=None)

            self.assertEqual(report.errors, [])
            self.assertIn("ReplicatedStorage.Shared.Rules", destroyed)
            self.assertTrue(any("Rules" in item for item in report.recreated))
            self.assertIn("game.ReplicatedStorage.Shared.Inputs.Keys", report.created)
            self.assertIn("game.ReplicatedStorage.Shared.Inputs", report.unchanged)
            self.assertEqual(report.stale, ["game.ServerScriptService.Server.Old"])
            self.assertNotIn("ServerScriptService.Server.Old", destroyed, "stale scripts stay unless prune")
            rules = next(source for path, source, _ in writes if path.endswith("Rules"))
            self.assertEqual(rules, "return 1\n", "CRLF is normalized before writing")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            for relative in ("src/shared/Rules.luau", "src/shared/Inputs/init.luau",
                             "src/shared/Inputs/Keys.luau", "src/server/Main.server.luau"):
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("return nil\n", encoding="utf-8")

            def fail(*_a, **_k):
                raise AssertionError("dry run must not write")

            agent = SimpleNamespace(
                luau=SimpleNamespace(run_json=lambda *a, **k: {}),
                scripts=SimpleNamespace(write=fail),
                datamodel=SimpleNamespace(destroy=fail),
                context=SimpleNamespace(forget_script=lambda path: None),
            )
            report = sync(agent, project, sourcemap=SOURCEMAP, dry_run=True, serve_probe=None)
            self.assertEqual(len(report.created), 4)
            self.assertTrue(report.summary().startswith("dry run"))

    def _project(self, folder: str) -> Path:
        project = Path(folder)
        for relative, text in {
            "src/shared/Rules.luau": "return 1\r\n",
            "src/shared/Inputs/init.luau": "return {}\n",
            "src/shared/Inputs/Keys.luau": "return 2\n",
            "src/server/Main.server.luau": "print('hi')\n",
        }.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return project

    def test_dry_run_compares_sources(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)

            def fail(*_a, **_k):
                raise AssertionError("dry run must not write")

            agent = SimpleNamespace(
                luau=SimpleNamespace(run_json=lambda *a, **k: {
                    "ReplicatedStorage.Shared.Rules": {"c": "ModuleScript", "s": "return 1\n"},
                    "ReplicatedStorage.Shared.Inputs": {"c": "ModuleScript", "s": "return 'old'\n"},
                    "ServerScriptService.Server.Main": {"c": "Script", "s": "print('hi')\r\n"},
                }),
                scripts=SimpleNamespace(write=fail),
                datamodel=SimpleNamespace(destroy=fail),
                context=SimpleNamespace(forget_script=lambda path: None),
            )
            report = sync(agent, project, sourcemap=SOURCEMAP, dry_run=True, serve_probe=None)
            self.assertEqual(sorted(report.unchanged),
                             ["game.ReplicatedStorage.Shared.Rules", "game.ServerScriptService.Server.Main"],
                             "same text, line endings aside, is unchanged")
            self.assertEqual(report.written, ["game.ReplicatedStorage.Shared.Inputs"])
            self.assertEqual(report.created, ["game.ReplicatedStorage.Shared.Inputs.Keys"])

    def test_scripts_outside_a_root_are_queried_by_path(self) -> None:
        code = studio_scripts_luau([], ["game.StarterPlayer.StarterCharacterScripts.Health"])
        self.assertIn('"StarterPlayer.StarterCharacterScripts.Health"', code)

    def test_refuses_to_write_while_rojo_serve_serves_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)

            def fail(*_a, **_k):
                raise AssertionError("must not write while rojo serve is the writer")

            agent = SimpleNamespace(
                luau=SimpleNamespace(run_json=fail),
                scripts=SimpleNamespace(write=fail),
                datamodel=SimpleNamespace(destroy=fail),
                context=SimpleNamespace(forget_script=lambda path: None),
            )
            report = sync(agent, project, sourcemap=SOURCEMAP, serve_probe=lambda: "Game")
            self.assertEqual(len(report.errors), 1)
            self.assertIn("rojo serve", report.errors[0])

            agent.luau = SimpleNamespace(run_json=lambda *a, **k: {})
            dry = sync(agent, project, sourcemap=SOURCEMAP, dry_run=True, serve_probe=lambda: "Game")
            self.assertEqual(dry.errors, [])
            self.assertEqual(len(dry.warnings), 1, "a dry run still reports, with a warning")

            other = sync(agent, project, sourcemap=SOURCEMAP, dry_run=True, serve_probe=lambda: "SomeOtherGame")
            self.assertEqual(other.warnings, [], "a different project's serve is not this one's writer")

    def test_msgpack_reply_from_rojo_7_7(self) -> None:
        from roblox_studio_adapter.rojo_sync import _msgpack_map

        # The head of a real /api/rojo reply from rojo 7.7.1, re-counted as a 4-entry map.
        body = (b"\x84\xa9sessionId\xd9$28ca1d03-b6ec-4029-acc4-ad6918500c64\xadserverVersion\xa57.7.1"
                b"\xafprotocolVersion\x05\xabprojectName\xacJetpackMania")
        decoded = _msgpack_map(body)
        assert decoded is not None
        self.assertEqual(decoded["projectName"], "JetpackMania")
        self.assertEqual(decoded["protocolVersion"], 5)
        self.assertIsNone(_msgpack_map(b'{"projectName": "x"}'), "JSON is not mistaken for msgpack")
        self.assertIsNone(_msgpack_map(b"\x81\xa1a"), "a truncated reply is refused, not guessed")

    def test_serve_probe_is_none_when_nothing_listens(self) -> None:
        self.assertIsNone(rojo_serve_project(port=1, timeout=0.2))


class StdioTests(unittest.TestCase):
    def test_subprocess_handshake_over_stdio(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        frames = "\n".join(json.dumps(item) for item in [
            _request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "0"}}, 1),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _request("tools/list", None, 2),
            _request("ping", None, 3),
        ]) + "\n"
        completed = subprocess.run(
            [sys.executable, "-m", "roblox_studio_adapter", "mcp"],
            input=frames, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
        )
        lines = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual([line["id"] for line in lines], [1, 2, 3], completed.stderr)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "roblox-studio-adapter")
        self.assertGreaterEqual(len(lines[1]["result"]["tools"]), 10)
        self.assertEqual(lines[2]["result"], {})


if __name__ == "__main__":
    unittest.main()
