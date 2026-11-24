from __future__ import annotations

import json
import unittest

from roblox_studio_adapter.framing import FrameDecoder, encode_message
from roblox_studio_adapter.luau_gen import apply_chunk, luau_literal, luau_string, yield_risk
from roblox_studio_adapter.parsers import (
    console_delta,
    parse_inspect,
    parse_script_read,
    parse_studio_state,
    parse_studios,
    parse_tree,
)
from roblox_studio_adapter.paths import recommend_script_class, script_tool_path, tree_path
from roblox_studio_adapter.services.cloud import assess_cloud_call
from roblox_studio_adapter.services.scripts import escape_luau_pattern
from roblox_studio_adapter.errors import EditError, HighRiskRefused, UnyieldingLuau


class FramingTests(unittest.TestCase):
    def test_ndjson_and_split_chunks(self) -> None:
        decoder = FrameDecoder()
        first = decoder.feed(b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n{"json')
        self.assertEqual(first[0]["id"], 1)
        second = decoder.feed(b'rpc":"2.0","id":2,"result":{}}\n')
        self.assertEqual(second[0]["id"], 2)

    def test_content_length(self) -> None:
        body = b'{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}'
        frame = b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        messages = FrameDecoder().feed(frame)
        self.assertEqual(messages[0]["id"], 7)

    def test_encode_is_one_line(self) -> None:
        raw = encode_message({"a": "line\nbreak"})
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertIn("line\\nbreak", raw.decode())


class ParserTests(unittest.TestCase):
    def test_studios_payload(self) -> None:
        text = json.dumps(
            {
                "studios": [
                    {
                        "id": "abc",
                        "mode": "Edit",
                        "name": "Place1",
                        "persistedToCloud": False,
                        "state": "- Current Studio Mode: Edit\n- Available DataModels: Edit\n",
                    }
                ]
            }
        )
        studios = parse_studios(text)
        self.assertEqual(studios[0].id, "abc")
        self.assertFalse(studios[0].persisted_to_cloud)

    def test_state_bullets(self) -> None:
        edit = parse_studio_state(
            "- Current Studio Mode: Edit\n- Available DataModels: Edit\n- Focused DataModel in the viewport: Edit\n"
        )
        self.assertFalse(edit.playing)
        self.assertTrue(edit.can_edit_scripts)
        play = parse_studio_state(
            "- Current Studio Mode: Play\n- Available DataModels: Client, Server\n- Focused DataModel in the viewport: Client\n"
        )
        self.assertTrue(play.playing)
        self.assertEqual(play.available, ("Client", "Server"))

    def test_tree_with_truncation_note(self) -> None:
        text = 'Note: Output limited to 30 nodes (results truncated)\n\n[{"name":"Workspace","className":"Workspace","fullPath":"Workspace","parentName":"Place1"}]'
        page = parse_tree(text)
        self.assertTrue(page.truncated)
        self.assertEqual(page.nodes[0].full_path, "Workspace")

    def test_inspect_empty_property_list(self) -> None:
        text = json.dumps(
            {
                "path": "Workspace",
                "name": "Workspace",
                "className": "Workspace",
                "uniqueId": "u",
                "properties": [],
                "children": {"immediateChildren": [{"path": "Workspace.Baseplate", "className": "Part"}], "childrenCount": 1, "totalDescendants": 1},
            }
        )
        inspected = parse_inspect(text).matches[0]
        self.assertTrue(inspected.properties_missing)
        self.assertEqual(inspected.children[0]["path"], "Workspace.Baseplate")

    def test_script_round_trip(self) -> None:
        raw = "1→local value = 1\n2→print(value)\n"
        document = parse_script_read("game.ServerScriptService.Hello", raw)
        self.assertEqual(document.source, "local value = 1\nprint(value)")
        self.assertTrue(document.numbered)

    def test_console_delta_and_stack(self) -> None:
        previous = "old line\n"
        current = "old line\nServerScriptService.Hello:3: attempt to index nil\nStack Begin\nScript 'Hello', Line 3\nStack End\n"
        delta = console_delta(previous, current)
        self.assertFalse(delta.reset)
        self.assertTrue(any("Stack Begin" in item for item in delta.errors))


class LuauTests(unittest.TestCase):
    def test_string_escape_and_enum(self) -> None:
        self.assertEqual(luau_string('say "hi"\n'), '"say \\"hi\\"\\n"')
        self.assertEqual(luau_literal("Enum.Material.Plastic"), "Enum.Material.Plastic")
        self.assertTrue(luau_literal("not an enum").startswith('"'))

    def test_chunk_waits_and_refuses_source(self) -> None:
        code = apply_chunk(
            [
                {
                    "parent": "Workspace",
                    "name": "Pad",
                    "class_name": "Part",
                    "properties": {"Anchored": True, "Size": {"type": "Vector3", "x": 4, "y": 1, "z": 4}},
                }
            ]
        )
        self.assertIn("task.wait()", code)
        self.assertIn("ipairs(specs)", code)
        self.assertIn("Vector3.new(4, 1, 4)", code)
        with self.assertRaises(EditError):
            apply_chunk([{"parent": "ServerScriptService", "name": "A", "class_name": "Script", "properties": {"Source": "print(1)"}}])

    def test_yield_guard(self) -> None:
        self.assertIsNotNone(yield_risk("while not ready do\nend"))
        self.assertIsNotNone(yield_risk("for i = 1, 100 do Instance.new('Part') end"))
        self.assertIsNone(yield_risk("for i = 1, 10 do Instance.new('Part') end\ntask.wait()"))
        with self.assertRaises(UnyieldingLuau):
            from roblox_studio_adapter.services.luau import LuauService

            class Dummy:
                pass

            LuauService.run(Dummy(), "while true do end")  # type: ignore[arg-type]


class PathAndCloudTests(unittest.TestCase):
    def test_path_dialects(self) -> None:
        self.assertEqual(script_tool_path("ServerScriptService.Hello"), "game.ServerScriptService.Hello")
        self.assertEqual(script_tool_path("game.ServerScriptService.Hello"), "game.ServerScriptService.Hello")
        self.assertEqual(tree_path("game.Workspace.Baseplate"), "Workspace.Baseplate")
        self.assertEqual(recommend_script_class("game.StarterGui.Hud")[0], "LocalScript")
        self.assertEqual(escape_luau_pattern("a.b-c"), "a%.b%-c")

    def test_cloud_guard(self) -> None:
        assess_cloud_call("GET", "/cloud/v2/universes/1", ["universe:read"], allow_high_risk=False)
        with self.assertRaises(HighRiskRefused):
            assess_cloud_call("POST", "/cloud/v2/universes/1:publish", ["universe:write"], allow_high_risk=False)
        assess_cloud_call("POST", "/cloud/v2/universes/1:publish", ["universe:write"], allow_high_risk=True)


if __name__ == "__main__":
    unittest.main()
