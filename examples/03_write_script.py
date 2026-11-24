"""Create or replace ServerScriptService.HelloAgent in the open place.

This edits the place. It does not save and it does not publish.
Set ROBLOX_STUDIO_CONFIRM=1 to run it. Point it at a place you are willing to change:

    $env:ROBLOX_STUDIO_CONFIRM = "1"
    python examples/03_write_script.py
"""

import os
import sys

from roblox_studio_adapter import RobloxStudio

SOURCE = """-- Created by examples/03_write_script.py. Safe to delete.
print("hello from the agent")
"""


def main() -> None:
    if os.environ.get("ROBLOX_STUDIO_CONFIRM") != "1":
        print("Refusing to edit. Set ROBLOX_STUDIO_CONFIRM=1 to create HelloAgent. Nothing was saved.")
        sys.exit(2)
    with RobloxStudio.connect() as agent:
        result = agent.scripts.write(
            "game.ServerScriptService.HelloAgent",
            SOURCE,
            class_name="auto",
        )
        print(f"path={result.path} created={result.created} unchanged={result.unchanged}")
        print(result.note)
        document = agent.scripts.read(result.path)
        print(document.source)


if __name__ == "__main__":
    main()
