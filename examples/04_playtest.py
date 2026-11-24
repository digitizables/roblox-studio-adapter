"""Start a solo playtest, wait, capture Output and one screenshot, then stop.

This changes play mode. It does not edit scripts and it does not save.
Set ROBLOX_STUDIO_CONFIRM=1 to run it:

    $env:ROBLOX_STUDIO_CONFIRM = "1"
    python examples/04_playtest.py
"""

import os
import sys

from roblox_studio_adapter import RobloxStudio


def main() -> None:
    if os.environ.get("ROBLOX_STUDIO_CONFIRM") != "1":
        print("Refusing to start play. Set ROBLOX_STUDIO_CONFIRM=1. The place was not modified.")
        sys.exit(2)
    with RobloxStudio.connect() as agent:
        report = agent.playtest.run(seconds=3, screenshot=True, stop=True, forbid_errors=False)
        print(f"before={report.mode_before} after={report.mode_after} stopped={report.stopped}")
        print("--- new output ---")
        print(report.console.text or "(no new lines)")
        print("screenshots:", report.screenshots)


if __name__ == "__main__":
    main()
