"""Terminal UI for humans and a JSON mode for agents.

Subcommands are the stable interface. ``ui`` is an optional numbered menu
for a person at a terminal. It is not required to install or run a plugin.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from roblox_studio_plugin_host import __version__
from roblox_studio_plugin_host.contract import InvokeContext, ParameterSpec
from roblox_studio_plugin_host.discovery import coerce_params, discover, load_installed
from roblox_studio_plugin_host.errors import BadParameter, NotInstalled, PluginHostError, PluginNotFound, UnknownCommand
from roblox_studio_plugin_host.state import PluginHome


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        prog="roblox-plugins",
        description="Install and run plugins that drive Roblox Studio through roblox-studio-adapter.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--home", help="State directory. Defaults to %%USERPROFILE%%/.roblox-studio-plugins")
    parser.add_argument("--json", action="store_true", help="Print one JSON object. For agents.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List discovered plugins and whether they are installed.")
    install = sub.add_parser("install", help="Enable a discovered plugin and record its version.")
    install.add_argument("plugin")
    update = sub.add_parser("update", help="Re-read a plugin and refresh the recorded version.")
    update.add_argument("plugin")
    remove = sub.add_parser("uninstall", help="Forget an install record. Does not delete the package.")
    remove.add_argument("plugin")

    status = sub.add_parser("status", help="Show install state, config, and the plugin's own status.")
    status.add_argument("plugin", nargs="?")

    config = sub.add_parser("config", help="Show or change saved configuration.")
    config.add_argument("plugin")
    config.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    config.add_argument("--unset", action="append", default=[], metavar="KEY")
    config.add_argument("--show", action="store_true")

    run = sub.add_parser("run", help="Invoke one plugin command.")
    run.add_argument("plugin")
    run.add_argument("name", help="Command name, for example generate_realistic_terrain")
    run.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    run.add_argument("--apply", action="store_true", help="Ask the command to edit the open place.")
    run.add_argument("--yes", action="store_true", help="Confirm a place edit. Same gate as ROBLOX_STUDIO_CONFIRM=1.")
    run.add_argument("--studio-name", help="Select the Studio whose name contains this text")

    sub.add_parser("ui", help="Numbered menu. Requires a terminal. Agents should use subcommands.")

    args = parser.parse_args(argv)
    home = PluginHome.open(_home_path(args.home))
    as_json = bool(getattr(args, "json", False))
    try:
        if args.command in {None, "list"}:
            return _list(home, as_json)
        if args.command == "install":
            return _install(home, args.plugin, as_json, update=False)
        if args.command == "update":
            return _install(home, args.plugin, as_json, update=True)
        if args.command == "uninstall":
            return _uninstall(home, args.plugin, as_json)
        if args.command == "status":
            return _status(home, args.plugin, as_json)
        if args.command == "config":
            return _config(home, args.plugin, args.set, args.unset, as_json)
        if args.command == "run":
            return _run(home, args, as_json)
        if args.command == "ui":
            return _ui(home)
    except PluginHostError as exc:
        return _fail(as_json, exc, code=2)
    except Exception as exc:
        return _fail(as_json, exc, code=_exit_code(exc))
    parser.print_help()
    return 2


def _home_path(text: str | None):
    from pathlib import Path

    return Path(text) if text else None


def _list(home: PluginHome, as_json: bool) -> int:
    found = discover(home)
    installed = home.read_installed().get("plugins", {})
    rows = []
    for record in found.records:
        info = installed.get(record.id, {})
        rows.append(
            {
                "id": record.id,
                "name": record.manifest.name if record.manifest else record.id,
                "version": record.version,
                "installed": bool(info.get("enabled")),
                "installed_version": info.get("version"),
                "summary": record.manifest.summary if record.manifest else "",
                "source": record.source,
                "path": record.path,
                "ok": record.ok,
                "error": record.error,
                "capabilities": list(record.manifest.capabilities) if record.manifest else [],
                "commands": [command.name for command in record.manifest.commands] if record.manifest else [],
            }
        )
    if as_json:
        _emit({"ok": True, "plugins": rows, "home": str(home.root)})
        return 0
    if not rows:
        print("No plugins discovered.")
        print("Drop a folder with plugin.json under plugins/, or install a package that publishes the roblox_studio.plugins entry point.")
        return 0
    print(f"{'id':16} {'version':10} {'state':12} summary")
    for row in rows:
        if not row["ok"]:
            state = "broken"
        elif row["installed"]:
            state = "installed"
        else:
            state = "available"
        summary = row["summary"] or row["error"] or ""
        print(f"{row['id']:16} {row['version'] or '-':10} {state:12} {summary}")
    print(f"home: {home.root}")
    return 0


def _install(home: PluginHome, plugin_id: str, as_json: bool, *, update: bool) -> int:
    found = discover(home)
    record = found.get(plugin_id)
    if record is None or not record.ok or record.manifest is None:
        if record and record.error:
            raise PluginHostError(f"Cannot install {plugin_id!r}: {record.error}")
        raise PluginNotFound(plugin_id, found.ids())
    saved = home.record_install(
        record.id,
        version=record.manifest.version,
        source=record.source,
        path=record.path,
    )
    payload = {"ok": True, "action": "update" if update else "install", "plugin": record.id, "record": saved}
    if as_json:
        _emit(payload)
    else:
        verb = "Updated" if update else "Installed"
        print(f"{verb} {record.manifest.name} {record.manifest.version} ({record.id}).")
        print(f"Recorded in {home.installed_path}")
    return 0


def _uninstall(home: PluginHome, plugin_id: str, as_json: bool) -> int:
    removed = home.record_uninstall(plugin_id)
    if as_json:
        _emit({"ok": True, "removed": removed, "plugin": plugin_id})
    elif removed:
        print(f"Uninstalled {plugin_id}. The package files were left in place.")
    else:
        print(f"{plugin_id} was not installed.")
    return 0


def _status(home: PluginHome, plugin_id: str | None, as_json: bool) -> int:
    if not plugin_id:
        return _list(home, as_json)
    found = discover(home)
    record = found.get(plugin_id)
    if record is None:
        raise PluginNotFound(plugin_id, found.ids())
    installed = home.read_installed().get("plugins", {}).get(plugin_id)
    config = home.read_config(plugin_id)
    plugin_status: dict[str, Any] = {}
    if record.ok and record.plugin is not None and record.manifest is not None:
        status_command = record.manifest.command("status")
        if status_command is not None:
            context = InvokeContext(
                config=config,
                gateway=None,
                progress=_quiet,
                confirmed=False,
                home=home.root,
                plugin_id=plugin_id,
            )
            plugin_status = record.plugin.invoke("status", {}, context=context)
    payload = {
        "ok": record.ok,
        "id": plugin_id,
        "installed": installed,
        "config": config,
        "error": record.error,
        "manifest": record.manifest.to_dict() if record.manifest else None,
        "status": plugin_status,
        "home": str(home.root),
    }
    if as_json:
        _emit(payload)
        return 0 if record.ok else 3
    print(f"{plugin_id}  {'installed' if installed else 'not installed'}")
    if record.manifest:
        print(f"version: {record.manifest.version}")
        print(f"summary: {record.manifest.summary}")
        print("capabilities: " + ", ".join(record.manifest.capabilities))
        print("commands:")
        for command in record.manifest.commands:
            mark = "edits the place" if command.mutates_place else "read-only"
            print(f"  {command.name}  ({mark})  {command.summary}")
    if record.error:
        print(f"error: {record.error}")
    print("config: " + (json.dumps(config, sort_keys=True) if config else "(defaults)"))
    if plugin_status:
        print("plugin status:")
        print(json.dumps(plugin_status, indent=2, sort_keys=True))
    return 0 if record.ok else 3


def _config(home: PluginHome, plugin_id: str, sets: list[str], unsets: list[str], as_json: bool) -> int:
    record = _require(home, plugin_id)
    assert record.manifest is not None and record.plugin is not None
    current = home.read_config(plugin_id)
    if sets or unsets:
        updates = _parse_sets(sets)
        coerced = coerce_params(record.manifest.config, updates)
        current.update(coerced)
        for key in unsets:
            if key not in {param.name for param in record.manifest.config}:
                names = ", ".join(param.name for param in record.manifest.config) or "(none)"
                raise BadParameter(f"Unknown config key {key!r}. Known keys: {names}.")
            current.pop(key, None)
        home.write_config(plugin_id, current)
    if as_json:
        _emit({"ok": True, "plugin": plugin_id, "config": current, "schema": _schema(record.manifest.config)})
    else:
        print(f"config for {plugin_id} ({home.config_path(plugin_id)}):")
        if not record.manifest.config:
            print("  This plugin has no saved configuration.")
        for param in record.manifest.config:
            saved = current.get(param.name, param.default)
            print(f"  {param.name} = {saved!r}    {param.summary}")
    return 0


def _run(home: PluginHome, args: argparse.Namespace, as_json: bool) -> int:
    record = _require(home, args.plugin)
    assert record.manifest is not None and record.plugin is not None
    command = record.manifest.command(args.name)
    if command is None:
        raise UnknownCommand(args.plugin, args.name, [item.name for item in record.manifest.commands])
    params = coerce_params(command.parameters, _parse_sets(args.set))
    if args.apply:
        params["apply"] = True
    confirmed = bool(args.yes) or os.environ.get("ROBLOX_STUDIO_CONFIRM") == "1"
    param_names = {param.name for param in command.parameters}
    if "apply" in param_names:
        wants_studio = bool(params.get("apply"))
    else:
        wants_studio = bool(command.mutates_place)
    gateway = None
    agent = None
    def progress(stage: str, fraction: float, detail: str = "") -> None:
        if as_json:
            return
        clamped = max(0.0, min(1.0, float(fraction)))
        tail = f"  {detail}" if detail else ""
        print(f"[{args.plugin}] {clamped:0.2f} {stage}{tail}", flush=True)

    try:
        if wants_studio:
            if not confirmed:
                # The plugin raises the detailed confirmation error. Do not open Studio yet.
                pass
            else:
                from roblox_studio_plugin_host.gateway import connect_port

                agent, gateway = connect_port(progress, name_contains=args.studio_name)
        context = InvokeContext(
            config=home.read_config(args.plugin),
            gateway=gateway,
            progress=progress if not as_json else _quiet,
            confirmed=confirmed,
            home=home.root,
            plugin_id=args.plugin,
        )
        result = record.plugin.invoke(command.name, params, context=context)
    finally:
        if agent is not None:
            agent.close()
    payload = {"ok": True, "plugin": args.plugin, "command": command.name, "result": result}
    if as_json:
        _emit(payload)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _ui(home: PluginHome) -> int:
    if not sys.stdin.isatty():
        print("ui needs a terminal. Use list, install, config, status, and run.")
        return 2
    while True:
        print()
        print("Studio plugins")
        print("  1  List plugins")
        print("  2  Install or update")
        print("  3  Status")
        print("  4  Configure")
        print("  5  Run a command (dry unless you confirm an edit)")
        print("  q  Quit")
        choice = input("> ").strip().lower()
        if choice in {"q", "quit", "0"}:
            return 0
        if choice == "1":
            _list(home, False)
        elif choice == "2":
            plugin_id = input("plugin id: ").strip()
            if plugin_id:
                try:
                    _install(home, plugin_id, False, update=True)
                except PluginHostError as exc:
                    print(exc)
        elif choice == "3":
            plugin_id = input("plugin id (blank lists all): ").strip()
            try:
                _status(home, plugin_id or None, False)
            except PluginHostError as exc:
                print(exc)
        elif choice == "4":
            plugin_id = input("plugin id: ").strip()
            assignment = input("key=value (blank to show): ").strip()
            try:
                _config(home, plugin_id, [assignment] if assignment else [], [], False)
            except PluginHostError as exc:
                print(exc)
        elif choice == "5":
            plugin_id = input("plugin id: ").strip()
            name = input("command: ").strip()
            apply_answer = input("edit the open place? [y/N]: ").strip().lower()
            namespace = argparse.Namespace(
                plugin=plugin_id,
                name=name,
                set=[],
                apply=apply_answer in {"y", "yes"},
                yes=False,
                studio_name=None,
            )
            if namespace.apply:
                print("Set ROBLOX_STUDIO_CONFIRM=1 or answer yes to confirm.")
                namespace.yes = input("confirm the edit? [y/N]: ").strip().lower() in {"y", "yes"}
            try:
                _run(home, namespace, False)
            except (PluginHostError, Exception) as exc:
                print(exc)
        else:
            print("Choose 1, 2, 3, 4, 5, or q.")


def _require(home: PluginHome, plugin_id: str):
    return load_installed(home, plugin_id)


def _parse_sets(pairs: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise BadParameter(f"Expected key=value, got {item!r}.")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise BadParameter(f"Expected key=value, got {item!r}.")
        parsed[key] = value
    return parsed


def _schema(params: tuple[ParameterSpec, ...]) -> list[dict[str, Any]]:
    return [
        {
            "name": param.name,
            "kind": param.kind,
            "summary": param.summary,
            "default": param.default,
            "choices": list(param.choices),
        }
        for param in params
    ]


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _quiet(stage: str, fraction: float, detail: str = "") -> None:
    del stage, fraction, detail


def _fail(as_json: bool, exc: BaseException, *, code: int) -> int:
    if as_json:
        _emit({"ok": False, "error": str(exc), "type": type(exc).__name__})
    else:
        print(str(exc), file=sys.stderr)
    return code


def _exit_code(exc: BaseException) -> int:
    name = type(exc).__name__
    if name in {"ConfirmationRequired", "ValidationError", "BadParameter"}:
        return 2
    if name in {"DataUnavailable"}:
        return 4
    return 3
