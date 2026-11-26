"""Start a solo playtest, watch the output, and stop back in Edit."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from roblox_studio_adapter.errors import TimeoutError
from roblox_studio_adapter.parsers import console_delta, parse_video_capture
from roblox_studio_adapter.results import CheckResult, ConsoleDelta, PlaytestReport
from roblox_studio_adapter.session import Session


class PlaytestService:
    def __init__(self, session: Session, sleep: Callable[[float], None] | None = None) -> None:
        self.session = session
        self.sleep = sleep or time.sleep

    def state(self):
        return self.session.refresh_state(force=True)

    def start(self, *, timeout: float = 30) -> None:
        state = self.state()
        if state.playing:
            return
        self.session.context.console_snapshot = self.console()
        self.session.call("start_stop_play", {"is_start": True})
        self.session.invalidate_state()
        self._wait_until(lambda: self.state().playing, timeout, "playtest did not reach Play mode")

    def stop(self, *, timeout: float = 30) -> None:
        state = self.state()
        if not state.playing and state.can_edit_scripts:
            return
        self.session.call("start_stop_play", {"is_start": False})
        self.session.invalidate_state()
        self._wait_until(lambda: self.state().can_edit_scripts, timeout, "Studio did not return to Edit mode")

    def console(self) -> str:
        return self.session.call("get_console_output", {}).text

    def console_since_snapshot(self) -> ConsoleDelta:
        current = self.console()
        delta = console_delta(self.session.context.console_snapshot, current)
        self.session.context.console_snapshot = current
        return delta

    def run(
        self,
        *,
        seconds: float = 3,
        screenshot: bool = True,
        stop: bool = True,
        expect_contains: list[str] | None = None,
        expect_absent: list[str] | None = None,
        forbid_errors: bool = True,
        probes: list[dict] | None = None,
    ) -> PlaytestReport:
        """Play, wait, collect new output and an optional screenshot, then stop.

        ``seconds`` is waited in this process. Studio keeps simulating. Do not
        busy-wait inside execute_luau. The playtest camera is left alone;
        frame an edit-time shot with CaptureService instead.

        ``expect_contains`` and ``expect_absent`` are matched against the
        console delta. Empty strings are rejected before play starts.
        ``probes`` are Luau expressions run on Server or Client while the
        playtest is still going, before stop deletes that copy. Each probe
        is ``{"id", "expression", "datamodel"}`` and may set ``equals``.
        ``passed`` is true when every named check succeeded. It is null when
        the caller asked for no judgment (``forbid_errors`` false, both lists
        empty, and no probes). Store the JSON form with ``evidence_record``.
        """
        contains = _needles(expect_contains, "expect_contains")
        absent = _needles(expect_absent, "expect_absent")
        probe_specs = _probe_specs(probes)
        before = self.state()
        started = not before.playing
        if started:
            self.start()
        else:
            self.session.context.console_snapshot = self.console()
        shots: list[str] = []
        delta = ConsoleDelta(text="", reset=False)
        probe_rows: list[dict] = []
        probe_checks: list[CheckResult] = []
        try:
            if seconds > 0:
                self.sleep(seconds)
            if probe_specs:
                probe_rows, probe_checks = self._collect_probes(probe_specs)
            if screenshot:
                from roblox_studio_adapter.services.capture import CaptureService

                shots = CaptureService(self.session).screenshot()
            delta = self.console_since_snapshot()
        finally:
            stopped = False
            if stop:
                self.stop()
                stopped = True
        after = self.state()
        checks, failures = _checks(delta, forbid_errors=forbid_errors, contains=contains, absent=absent)
        checks.extend(probe_checks)
        failures.extend(check.detail for check in probe_checks if not check.passed)
        judged = forbid_errors or bool(contains) or bool(absent) or bool(probe_specs)
        passed = (not failures) if judged else None
        notes = [
            "start_stop_play runs a solo playtest. It does not start Team Test or a multi-client session.",
            "Runtime changes disappear when the playtest stops. Edit scripts only after stop.",
        ]
        if delta.reset:
            notes.append(
                "Console snapshot did not match the later log. Checks used the full log from after the playtest."
            )
        return PlaytestReport(
            mode_before=before.mode,
            mode_after=after.mode,
            started=started,
            stopped=stopped,
            seconds=seconds,
            console=delta,
            screenshots=shots,
            passed=passed,
            failures=failures,
            checks=checks,
            probes=probe_rows,
            notes=notes,
        )

    def record(self, perform: Callable[[], None]) -> dict:
        """Record motion while ``perform`` runs. Client playtest only.

        Prefer a few screenshots unless the question is about movement over time.
        """
        self.start()
        self.session.call("video_capture", {"is_start": True}, datamodel="Client")
        try:
            perform()
        finally:
            result = self.session.call("video_capture", {"is_start": False}, datamodel="Client")
        return parse_video_capture(result.text)

    def _wait_until(self, predicate: Callable[[], bool], timeout: float, message: str) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(message)
            self.sleep(0.4)

    def _collect_probes(self, probes: list[dict]) -> tuple[list[dict], list[CheckResult]]:
        from roblox_studio_adapter.services.luau import LuauService

        luau = LuauService(self.session)
        rows: list[dict] = []
        checks: list[CheckResult] = []
        for probe in probes:
            try:
                value = luau.query(probe["expression"], datamodel=probe["datamodel"])
            except Exception as exc:
                rows.append(
                    {
                        "id": probe["id"],
                        "datamodel": probe["datamodel"],
                        "ok": False,
                        "value": None,
                        "error": str(exc),
                    }
                )
                checks.append(
                    CheckResult(
                        f"probe.{probe['id']}",
                        "probe",
                        probe["expression"],
                        False,
                        f"probe {probe['id']} failed: {exc}",
                    )
                )
                continue
            ok = True
            detail = f"probe {probe['id']} returned {value!r}"
            if probe["has_equals"] and value != probe["equals"]:
                ok = False
                detail = f"probe {probe['id']} returned {value!r}, expected {probe['equals']!r}"
            rows.append(
                {
                    "id": probe["id"],
                    "datamodel": probe["datamodel"],
                    "ok": ok,
                    "value": _jsonable(value),
                    "error": None,
                }
            )
            checks.append(CheckResult(f"probe.{probe['id']}", "probe", probe["expression"], ok, detail))
        return rows, checks


def _needles(items: list[str] | None, label: str) -> list[str]:
    if not items:
        return []
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str) or item == "":
            raise ValueError(f"{label} entries must be non-empty strings")
        cleaned.append(item)
    return cleaned


def _checks(
    delta: ConsoleDelta,
    *,
    forbid_errors: bool,
    contains: list[str],
    absent: list[str],
) -> tuple[list[CheckResult], list[str]]:
    checks: list[CheckResult] = []
    failures: list[str] = []

    def add(check: CheckResult) -> None:
        checks.append(check)
        if not check.passed:
            failures.append(check.detail)

    if forbid_errors:
        ok = not delta.errors
        detail = "no output errors" if ok else f"{len(delta.errors)} output error(s)"
        add(CheckResult("output.error_free", "error_free", "", ok, detail))
    for index, needle in enumerate(contains, start=1):
        ok = needle in delta.text
        detail = f"output contained {needle!r}" if ok else f"output did not contain {needle!r}"
        add(CheckResult(f"output.contains.{index}", "contains", needle, ok, detail))
    for index, needle in enumerate(absent, start=1):
        ok = needle not in delta.text
        detail = f"output omitted {needle!r}" if ok else f"output contained forbidden {needle!r}"
        add(CheckResult(f"output.absent.{index}", "absent", needle, ok, detail))
    return checks, failures


def _probe_specs(items: list[dict] | None) -> list[dict]:
    if not items:
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        label = f"probes[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        probe_id = item.get("id")
        expression = item.get("expression")
        datamodel = item.get("datamodel")
        if not isinstance(probe_id, str) or probe_id == "":
            raise ValueError(f"{label}.id must be a non-empty string")
        if probe_id in seen:
            raise ValueError(f"{label}.id duplicates {probe_id!r}")
        seen.add(probe_id)
        if not isinstance(expression, str) or expression == "" or "\n" in expression:
            raise ValueError(f"{label}.expression must be one single-line Luau expression")
        if datamodel not in ("Server", "Client"):
            raise ValueError(f"{label}.datamodel must be Server or Client")
        cleaned.append(
            {
                "id": probe_id,
                "expression": expression,
                "datamodel": datamodel,
                "equals": item.get("equals"),
                "has_equals": "equals" in item,
            }
        )
    return cleaned


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value
