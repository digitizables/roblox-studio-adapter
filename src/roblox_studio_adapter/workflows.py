"""The plan, build, play, read, fix loop as ordinary method calls.

An agent should still decide what to build. These methods only remove the
repeated raw MCP choreography.
"""

from __future__ import annotations

from typing import Any

from roblox_studio_adapter.evidence import evidence_record
from roblox_studio_adapter.results import PlaytestReport, ScriptWriteResult


class Loop:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def explore(self, path: str | None = None) -> dict:
        """Shallow tree of the usual containers, plus a one-line studio brief."""
        state = self.agent.playtest.state()
        datamodel = "Server" if state.playing else "Edit"
        pages = self.agent.datamodel.overview(datamodel=datamodel)
        summary = {
            name: [f"{node.class_name} {node.full_path}" for node in page.nodes[:30]]
            for name, page in pages.items()
        }
        return {
            "studio_id": self.agent.session.studio_id,
            "mode": state.mode,
            "datamodel": datamodel,
            "services": summary,
            "truncated": [name for name, page in pages.items() if page.truncated],
        }

    def change_and_verify(
        self,
        *,
        scripts: list[dict] | None = None,
        instances: list[dict] | None = None,
        seconds: float = 3,
        expect_contains: list[str] | None = None,
        expect_absent: list[str] | None = None,
        forbid_errors: bool = True,
        screenshot: bool = True,
        intent_id: str | None = None,
    ) -> dict:
        """Stop play, apply edits, play, collect evidence, stop again.

        ``scripts`` items are ``{"path", "source", "class_name"}``.
        ``instances`` items are the datamodel.apply specs.

        ``evidence`` is the JSON record to store. ``playtest`` remains a
        ``PlaytestReport``. ``passed`` mirrors ``evidence["passed"]``.
        """
        self.agent.playtest.stop()
        script_results: list[ScriptWriteResult] = []
        for item in scripts or []:
            script_results.append(
                self.agent.scripts.write(
                    item["path"],
                    item["source"],
                    class_name=item.get("class_name", "auto"),
                )
            )
        instance_paths: list[str] = []
        if instances:
            instance_paths = self.agent.datamodel.apply(instances)
        report: PlaytestReport = self.agent.playtest.run(
            seconds=seconds,
            screenshot=screenshot,
            stop=True,
            expect_contains=expect_contains,
            expect_absent=expect_absent,
            forbid_errors=forbid_errors,
        )
        evidence = evidence_record(
            report,
            studio_id=self.agent.session.studio_id,
            intent_id=intent_id,
        )
        return {
            "scripts": script_results,
            "instances": instance_paths,
            "playtest": report,
            "passed": report.passed,
            "evidence": evidence,
            "memory": self.agent.context.brief(),
        }


def recommended_steps() -> list[str]:
    """Order of work the MCP docs and the playtest tools imply."""
    return [
        "List Studio windows and select the place. Do not guess when several are open.",
        "Load the Studio skill that matches the task (list_skills, then skill) before inventing an API.",
        "Read latest-features.json and the engine class page before using an API you remember.",
        "Explore the focus services. Do not dump the whole DataModel; the tree call truncates.",
        "Edit scripts and instances in Edit mode. multi_edit does not run during play.",
        "Playtest with start_stop_play, then read only the new console lines. Persist the JSON evidence record.",
        "Screenshot for a still check. Record video only for motion, timing, stutter, or flicker.",
        "Stop the playtest before the next edit. Runtime copies are discarded on stop.",
        "Save only when the person asked. save_place never publishes.",
        "For Open Cloud, ask for the missing scope. Do not work around a 403.",
    ]
