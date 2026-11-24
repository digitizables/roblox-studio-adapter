"""Start a solo playtest, watch the output, and stop back in Edit."""

from __future__ import annotations

import time
from collections.abc import Callable

from roblox_studio_adapter.errors import TimeoutError
from roblox_studio_adapter.parsers import console_delta, parse_job
from roblox_studio_adapter.results import ConsoleDelta, PlaytestReport
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
        forbid_errors: bool = True,
    ) -> PlaytestReport:
        """Play, wait, collect new output and an optional screenshot, then stop.

        ``seconds`` is waited in this process. Studio keeps simulating. Do not
        busy-wait inside execute_luau. The playtest camera is left alone;
        frame an edit-time shot with CaptureService instead.
        """
        before = self.state()
        started = not before.playing
        if started:
            self.start()
        else:
            self.session.context.console_snapshot = self.console()
        shots: list[str] = []
        delta = ConsoleDelta(text="", reset=False)
        try:
            if seconds > 0:
                self.sleep(seconds)
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
        failures: list[str] = []
        if forbid_errors and delta.errors:
            failures.append(f"{len(delta.errors)} output error(s)")
        for needle in expect_contains or []:
            if needle not in delta.text:
                failures.append(f"output did not contain {needle!r}")
        passed = not failures if (forbid_errors or expect_contains) else None
        notes = [
            "start_stop_play runs a solo playtest. It does not start Team Test or a multi-client session.",
            "Runtime changes disappear when the playtest stops. Edit scripts only after stop.",
        ]
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
        status = parse_job(result.text)
        return {"status": status.status, "text": result.text}

    def _wait_until(self, predicate: Callable[[], bool], timeout: float, message: str) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(message)
            self.sleep(0.4)
