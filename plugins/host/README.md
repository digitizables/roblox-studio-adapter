# roblox-studio-plugin-host

A small host for packages that drive Roblox Studio through `roblox-studio-adapter`. It lists plugins, stores install state and configuration, and runs one command at a time. It does not generate terrain or know about voxels.

The first plugin built on this contract is [roblox-terrain](https://github.com/digitizables/roblox-terrain), in its own repository. Install this host, then install that package.

## Install

From the repository root, with the adapter already installed:

```powershell
python -m pip install -e plugins/host
roblox-plugins list
```

Or, without installing:

```powershell
$env:PYTHONPATH = "src;plugins/host/src"
python -m roblox_studio_plugin_host list
```

State lives in `%USERPROFILE%/.roblox-studio-plugins` unless `ROBLOX_STUDIO_PLUGIN_HOME` is set. `ROBLOX_STUDIO_PLUGIN_ROOT` adds a directory to scan for `plugin.json` folders.

## Commands

```text
roblox-plugins list
roblox-plugins install terrain
roblox-plugins update terrain
roblox-plugins uninstall terrain
roblox-plugins status terrain
roblox-plugins config terrain --set preset=synthetic-valley
roblox-plugins run terrain generate_realistic_terrain --set seed=2
roblox-plugins run terrain generate_realistic_terrain --apply --yes
roblox-plugins ui
```

`--json` prints one object and suppresses progress lines. Exit codes are `0` success, `2` bad arguments or a missing confirmation, `3` the plugin failed, `4` elevation or land cover was not available.

`ui` is a numbered menu for a person at a terminal. It is not required. Agents should use the subcommands.

## Confirmation

A command edits the open place only when it says so. If the command has an `apply` parameter, Studio opens only when `apply` is true. Otherwise `mutates_place` decides. The host still waits for `--yes` or `ROBLOX_STUDIO_CONFIRM=1` before it connects. The same phrase the adapter uses for edits.

`apply` is not a config key. A saved config cannot turn the next dry run into a place edit.

## Contract

A plugin implements two methods.

`manifest()` returns a `PluginManifest`: id, name, version, summary, capabilities, commands, and config. It must not touch Studio or the network. Parameter names and command names are identifiers. Kinds are `string`, `integer`, `number`, and `boolean`.

`invoke(command, params, context)` returns a JSON-friendly dict. `context.gateway` is `None` until a confirmed edit is allowed. `context.progress(stage, fraction, detail)` is how a long command reports work. `context.home` is the plugin state directory. `context.config` is the saved config for this plugin.

The gateway implements `ensure_edit`, `execute` (one Luau program that returns a JSON object), `apply_instances`, and `progress`. `execute` raises when the program's `ok` field is false. The production gateway is `AdapterPort`, which chunks instance applies the way the adapter does.

To add a plugin, ship a folder:

```text
plugins/example/plugin.json
plugins/example/src/example_plugin/plugin.py   # PLUGIN = ...
```

`plugin.json` is `{ "schema": 1, "id": "example", "module": "example_plugin.plugin", "attribute": "PLUGIN", "src": "src" }`. A packaged plugin can also publish the entry point group `roblox_studio.plugins`. The host keeps the plugin's `src` directory on `sys.path` after a successful load.
