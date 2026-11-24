"""Command line for a quick connection check. It does not modify the place."""

from __future__ import annotations

import argparse
import json
import sys

from roblox_studio_adapter import __version__
from roblox_studio_adapter.catalog import static_tools
from roblox_studio_adapter.results import plain
from roblox_studio_adapter.workflows import recommended_steps


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(prog="roblox-studio-adapter", description="Roblox Studio MCP compatibility layer")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("catalog", help="Print the static tool catalog. Does not connect.")
    sub.add_parser("steps", help="Print the recommended agent loop. Does not connect.")
    doctor = sub.add_parser("doctor", help="Connect, list tools and studios, print state. Read-only.")
    doctor.add_argument("--name", help="Select the Studio whose name contains this text")
    tree = sub.add_parser("tree", help="Print a shallow tree of one service. Read-only.")
    tree.add_argument("--path", default="Workspace")
    tree.add_argument("--depth", type=int, default=2)
    tree.add_argument("--name", help="Select the Studio whose name contains this text")
    args = parser.parse_args(argv)
    if args.command in {None, "steps"}:
        print("\n".join(f"{index}. {step}" for index, step in enumerate(recommended_steps(), start=1)))
        return 0
    if args.command == "catalog":
        for spec in static_tools().values():
            mark = "docs-only" if spec.documented_only else spec.retry
            print(f"{spec.name:28} {spec.group:12} {mark:12} {spec.summary}")
        return 0
    from roblox_studio_adapter.agent import RobloxStudio

    with RobloxStudio.connect(name_contains=args.name) as agent:
        if args.command == "doctor":
            return _doctor(agent)
        page = agent.datamodel.tree(args.path, max_depth=args.depth, head_limit=40)
        print(json.dumps(plain(page), indent=2))
        return 0


def _doctor(agent) -> int:
    registry = agent.session.registry
    print(f"protocol: {agent.session.client.protocol}")
    print(f"tools advertised: {len(registry.names())}")
    missing = registry.missing_from_live()
    extra = registry.unknown_to_overlay()
    print("catalog tools missing from this Studio: " + (", ".join(missing) if missing else "(none)"))
    print("advertised tools with no overlay: " + (", ".join(extra) if extra else "(none)"))
    print("studios:")
    for studio in agent.studios():
        cloud = "cloud" if studio.persisted_to_cloud else "local"
        place = studio.place_id or studio.file or ""
        print(f"  {studio.name}  id={studio.id}  mode={studio.mode}  {cloud}  {place}")
    state = agent.playtest.state()
    print(f"state: mode={state.mode} available={','.join(state.available)} focused={state.focused}")
    print("doctor did not modify the place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
