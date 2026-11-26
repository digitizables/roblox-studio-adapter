from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from roblox_studio_adapter.catalog import static_tools
from roblox_studio_adapter.evidence import SCHEMA, evidence_record
from roblox_studio_adapter.parsers import parse_video_capture
from roblox_studio_adapter.results import CheckResult, ConsoleDelta, PlaytestReport, ScriptWriteResult, StudioState
from roblox_studio_adapter.services.playtest import PlaytestService
from roblox_studio_adapter.session import Session
from roblox_studio_adapter.workflows import Loop

_EDIT = "- Current Studio Mode: Edit\n- Available DataModels: Edit\n- Focused DataModel in the viewport: Edit\n"
_PLAY = "- Current Studio Mode: Play\n- Available DataModels: Client, Server\n- Focused DataModel in the viewport: Client\n"
_ROOT = Path(__file__).resolve().parents[1]


class PlayClient:
    def __init__(self, *, replace_log: bool = False, error: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.playing = False
        self.console = "boot\n"
        self.replace_log = replace_log
        self.error = error
        self.protocol = "test"
        self.transport = type("Transport", (), {"command": ["fake"]})()

    def call_tool_raw(self, name: str, arguments: dict, timeout: float):
        self.calls.append((name, dict(arguments)))
        if name == "get_studio_state":
            return ToolResultSafe(name, _PLAY if self.playing else _EDIT)
        if name == "start_stop_play":
            self.playing = bool(arguments.get("is_start"))
            if self.playing:
                line = "hello from the agent\n"
                if self.error:
                    line += "Zone is not a valid member\n"
                self.console = line if self.replace_log else self.console + line
            return ToolResultSafe(name, "ok")
        if name == "get_console_output":
            return ToolResultSafe(name, self.console)
        if name == "video_capture" and not arguments.get("is_start"):
            payload = {
                "recording_id": "rec-1",
                "status": "partial",
                "artifacts": {
                    "video": "C:/captures/rec-1.mp4",
                    "manifest": "C:/captures/rec-1.json",
                    "frame_times": "C:/captures/rec-1.frames",
                },
                "warnings": ["ended at the duration limit"],
            }
            return ToolResultSafe(name, json.dumps(payload))
        return ToolResultSafe(name, "{}")

    def list_tools(self) -> list[dict]:
        return [
            {"name": spec.name, "description": spec.summary, "inputSchema": {"type": "object"}}
            for spec in static_tools().values()
            if not spec.documented_only
        ]

    def close(self) -> None:
        return None


def ToolResultSafe(name: str, text: str):
    from roblox_studio_adapter.results import ToolResult

    return ToolResult(name=name, text=text)


def _service(client: PlayClient) -> PlaytestService:
    session = Session(client)  # type: ignore[arg-type]
    session.start()
    session.studio_id = "studio-1"
    session._state = StudioState(mode="Edit", available=("Edit",), focused="Edit", playing=False, raw_text=_EDIT)
    session._state_at = time.monotonic()
    return PlaytestService(session, sleep=lambda _seconds: None)


class PlaytestEvidenceTests(unittest.TestCase):
    def test_contains_and_absent_use_the_delta(self) -> None:
        service = _service(PlayClient())
        report = service.run(
            seconds=0,
            screenshot=False,
            expect_contains=["hello from the agent"],
            expect_absent=["boot"],
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.console.reset)
        self.assertEqual(report.console.text, "hello from the agent\n")
        ids = [check.id for check in report.checks]
        self.assertEqual(ids, ["output.error_free", "output.contains.1", "output.absent.1"])
        record = evidence_record(report, studio_id="studio-1", intent_id="intent:1", captured_at="2026-11-25T00:00:00Z")
        json.dumps(record)
        self.assertEqual(record["schema"], SCHEMA)
        self.assertTrue(record["passed"])
        self.assertEqual(record["intent_id"], "intent:1")
        self.assertEqual(record["console"]["excerpt"], "hello from the agent\n")

    def test_forbidden_line_and_output_error_fail(self) -> None:
        service = _service(PlayClient(error=True))
        report = service.run(
            seconds=0,
            screenshot=False,
            expect_contains=["hello from the agent"],
            expect_absent=["hello"],
        )
        self.assertFalse(report.passed)
        self.assertTrue(any(item.startswith("1 output error") for item in report.failures))
        self.assertTrue(any("forbidden" in item for item in report.failures))
        contains = next(check for check in report.checks if check.op == "contains")
        self.assertTrue(contains.passed)
        self.assertIn("hello from the agent", contains.detail)

    def test_empty_needle_does_not_start_play(self) -> None:
        client = PlayClient()
        service = _service(client)
        with self.assertRaises(ValueError):
            service.run(seconds=0, screenshot=False, expect_contains=[""])
        self.assertEqual(client.calls, [])

    def test_reset_log_is_flagged_and_still_checked(self) -> None:
        service = _service(PlayClient(replace_log=True))
        report = service.run(seconds=0, screenshot=False, expect_contains=["hello from the agent"])
        self.assertTrue(report.console.reset)
        self.assertTrue(report.passed)
        self.assertTrue(any("full log" in note for note in report.notes))

    def test_record_parses_video_artifacts(self) -> None:
        service = _service(PlayClient())
        recorded = service.record(lambda: None)
        self.assertEqual(recorded["status"], "partial")
        self.assertEqual(recorded["recording_id"], "rec-1")
        self.assertEqual(recorded["artifacts"]["video"], "C:/captures/rec-1.mp4")
        self.assertEqual(recorded["warnings"], ["ended at the duration limit"])

    def test_record_shape_matches_the_schema(self) -> None:
        schema = json.loads((_ROOT / "docs" / "evidence.schema.json").read_text(encoding="utf-8"))
        report = PlaytestReport(
            mode_before="Edit",
            mode_after="Edit",
            started=True,
            stopped=True,
            seconds=3,
            console=ConsoleDelta(text="ok", reset=False, errors=["e" * 600], warnings=["w"]),
            screenshots=["shot.png"],
            passed=False,
            failures=["1 output error(s)"],
            checks=[CheckResult("output.error_free", "error_free", "", False, "1 output error(s)")],
        )
        record = evidence_record(report, captured_at="2026-11-25T00:00:00Z")
        self.assertEqual(set(record), set(schema["properties"]))
        self.assertEqual(set(record["play"]), set(schema["properties"]["play"]["properties"]))
        self.assertEqual(set(record["console"]), set(schema["properties"]["console"]["properties"]))
        self.assertEqual(set(record["artifacts"]), set(schema["properties"]["artifacts"]["properties"]))
        self.assertEqual(set(record["checks"][0]), set(schema["properties"]["checks"]["items"]["properties"]))
        self.assertTrue(record["console"]["truncated"] is False)
        self.assertTrue(record["console"]["errors"][0].endswith("…"))
        self.assertLessEqual(len(record["console"]["errors"][0]), 501)

    def test_change_and_verify_returns_json_evidence(self) -> None:
        class Play:
            def stop(self) -> None:
                return None

            def run(self, **kwargs: object) -> PlaytestReport:
                self.kwargs = kwargs
                return PlaytestReport(
                    mode_before="Edit",
                    mode_after="Edit",
                    started=True,
                    stopped=True,
                    seconds=float(kwargs["seconds"]),
                    console=ConsoleDelta(text="hello from the agent", reset=False),
                    passed=True,
                    checks=[
                        CheckResult(
                            "output.contains.1",
                            "contains",
                            "hello from the agent",
                            True,
                            "output contained 'hello from the agent'",
                        )
                    ],
                )

        class Scripts:
            def write(self, path: str, source: str, class_name: str = "auto") -> ScriptWriteResult:
                return ScriptWriteResult(path=path, created=True, unchanged=False, class_name=class_name)

        class DataModel:
            def apply(self, specs: list[dict]) -> list[str]:
                return ["Workspace.AgentMarker"]

        class Context:
            def brief(self) -> str:
                return "memory"

        play = Play()
        agent = type("Agent", (), {})()
        agent.playtest = play
        agent.scripts = Scripts()
        agent.datamodel = DataModel()
        agent.context = Context()
        agent.session = type("Session", (), {"studio_id": "studio-1"})()
        result = Loop(agent).change_and_verify(
            scripts=[{"path": "game.ServerScriptService.Hello", "source": "print('hello from the agent')\n"}],
            instances=[{"parent": "Workspace", "name": "AgentMarker", "class_name": "Part"}],
            seconds=0,
            expect_contains=["hello from the agent"],
            expect_absent=["boom"],
            intent_id="intent:verify-hello",
        )
        self.assertEqual(play.kwargs["expect_absent"], ["boom"])
        self.assertEqual(result["evidence"]["intent_id"], "intent:verify-hello")
        self.assertEqual(result["evidence"]["studio_id"], "studio-1")
        self.assertEqual(result["passed"], True)
        json.dumps(result["evidence"])
        self.assertEqual(result["instances"], ["Workspace.AgentMarker"])


class VideoParserTests(unittest.TestCase):
    def test_flat_completed_payload(self) -> None:
        parsed = parse_video_capture(
            '{"status":"completed","recordingId":"rec-2","videoPath":"C:/v.mp4","manifestPath":"C:/m.json"}'
        )
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(parsed["recording_id"], "rec-2")
        self.assertEqual(parsed["artifacts"]["video"], "C:/v.mp4")
        self.assertEqual(parsed["artifacts"]["manifest"], "C:/m.json")

    def test_unknown_when_the_payload_is_prose(self) -> None:
        parsed = parse_video_capture("recording finished")
        self.assertEqual(parsed["status"], "unknown")
        self.assertIsNone(parsed["artifacts"]["video"])
        self.assertEqual(parsed["text"], "recording finished")


if __name__ == "__main__":
    unittest.main()
