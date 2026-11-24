"""List Studio windows and print play state. Does not edit the place.

Run from the repo with PYTHONPATH=src, or after `pip install -e .`:

    python examples/01_list_studios.py
"""

from roblox_studio_adapter import RobloxStudio


def main() -> None:
    with RobloxStudio.connect() as agent:
        for studio in agent.studios():
            cloud = "cloud" if studio.persisted_to_cloud else "local"
            print(f"{studio.name}  id={studio.id}  mode={studio.mode}  {cloud}")
        state = agent.playtest.state()
        print(f"focused={state.focused} available={','.join(state.available)}")
        print(f"tools={len(agent.tools())}")


if __name__ == "__main__":
    main()
