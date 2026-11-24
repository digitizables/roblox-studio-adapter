"""Stop play, write a script, add a part, play, check Output, stop.

This edits the open place and runs a solo playtest. It does not save or publish.
Set ROBLOX_STUDIO_CONFIRM=1 to run it:

    $env:ROBLOX_STUDIO_CONFIRM = "1"
    python examples/05_change_and_verify.py
"""

import os
import sys

from roblox_studio_adapter import RobloxStudio


def main() -> None:
    if os.environ.get("ROBLOX_STUDIO_CONFIRM") != "1":
        print("Refusing to edit. Set ROBLOX_STUDIO_CONFIRM=1. Nothing was written.")
        sys.exit(2)
    with RobloxStudio.connect() as agent:
        result = agent.loop.change_and_verify(
            scripts=[
                {
                    "path": "game.ServerScriptService.HelloAgent",
                    "source": "print('hello from the agent')\n",
                    "class_name": "auto",
                }
            ],
            instances=[
                {
                    "parent": "Workspace",
                    "name": "AgentMarker",
                    "class_name": "Part",
                    "properties": {
                        "Anchored": True,
                        "Size": {"x": 4, "y": 1, "z": 4},
                    },
                }
            ],
            seconds=3,
            expect_contains=["hello from the agent"],
        )
        print("passed:", result["passed"])
        print("instances:", result["instances"])
        print(result["memory"])


if __name__ == "__main__":
    main()
