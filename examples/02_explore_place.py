"""Print a shallow map of the usual services. Does not edit the place.

    python examples/02_explore_place.py
"""

from roblox_studio_adapter import RobloxStudio


def main() -> None:
    with RobloxStudio.connect() as agent:
        report = agent.loop.explore()
        print(f"mode={report['mode']} datamodel={report['datamodel']}")
        for name, rows in report["services"].items():
            print(f"\n{name}")
            for row in rows[:8]:
                print(f"  {row}")
            extra = len(rows) - 8
            if extra > 0:
                print(f"  … {extra} more in this page")
        if report["truncated"]:
            print("truncated:", ", ".join(report["truncated"]))
        print(agent.context.brief())


if __name__ == "__main__":
    main()
