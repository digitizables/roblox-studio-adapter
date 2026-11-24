"""Plugin host discovery and the install record. No Studio process."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "plugins" / "host" / "src"
if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

from roblox_studio_plugin_host.discovery import discover, load_installed
from roblox_studio_plugin_host.errors import NotInstalled
from roblox_studio_plugin_host.state import PluginHome


class HostTests(unittest.TestCase):
    def test_folder_plugin_can_be_installed_without_an_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = PluginHome.open(Path(tmp) / "home")
            plugin_dir = _write_sample_plugin(Path(tmp) / "sample")
            previous = os.environ.get("ROBLOX_STUDIO_PLUGIN_ROOT")
            os.environ["ROBLOX_STUDIO_PLUGIN_ROOT"] = str(plugin_dir)
            try:
                found = discover(home)
                record = found.get("sample")
                self.assertIsNotNone(record)
                assert record is not None
                self.assertTrue(record.ok, record.error)
                assert record.manifest is not None
                self.assertEqual(record.manifest.id, "sample")
                self.assertIsNotNone(record.manifest.command("status"))
                self.assertFalse(any(param.name == "apply" for param in record.manifest.config))
                with self.assertRaises(NotInstalled):
                    load_installed(home, "sample")
                home.record_install("sample", version=record.version, source=record.source, path=record.path)
                loaded = load_installed(home, "sample")
                assert loaded.plugin is not None
                status = loaded.plugin.invoke("status", {}, context=_context(home))
                self.assertEqual(status["plugin"], "sample")
            finally:
                if previous is None:
                    os.environ.pop("ROBLOX_STUDIO_PLUGIN_ROOT", None)
                else:
                    os.environ["ROBLOX_STUDIO_PLUGIN_ROOT"] = previous


def _write_sample_plugin(folder: Path) -> Path:
    source = folder / "src"
    source.mkdir(parents=True)
    (folder / "plugin.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "sample",
                "module": "sample_plugin",
                "attribute": "PLUGIN",
                "src": "src",
            }
        ),
        encoding="utf-8",
    )
    (source / "sample_plugin.py").write_text(
        textwrap.dedent(
            """
            from roblox_studio_plugin_host.contract import CommandSpec, PluginManifest

            class SamplePlugin:
                def manifest(self):
                    return PluginManifest(
                        id="sample",
                        name="Sample",
                        version="0.0.1",
                        summary="Fixture plugin for the host tests.",
                        capabilities=("sample.status",),
                        commands=(
                            CommandSpec("status", "Report that the fixture loaded.", mutates_place=False),
                        ),
                    )

                def invoke(self, command, params, *, context):
                    del params, context
                    return {"plugin": "sample", "command": command}

            PLUGIN = SamplePlugin()
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return folder


def _context(home: PluginHome):
    from roblox_studio_plugin_host.contract import InvokeContext

    return InvokeContext(
        config={},
        gateway=None,
        progress=lambda stage, fraction, detail="": None,
        confirmed=False,
        home=home.root,
        plugin_id="sample",
    )


if __name__ == "__main__":
    unittest.main()
