# Plugins

The adapter does not load plugins and does not generate terrain. `plugins/host` discovers plugins, stores their configuration, and opens Studio only for a confirmed place edit. A plugin depends on the adapter. The adapter does not import the host or any plugin.

Install the host from this repository:

```powershell
python -m pip install -e plugins/host
roblox-plugins list
```

The realistic terrain plugin is a separate project: [github.com/digitizables/roblox-terrain](https://github.com/digitizables/roblox-terrain). Clone it beside this repo (or install it after the host) and follow that repository's README. Its commands are `generate_realistic_terrain`, `inspect_scene`, `plan_tiles`, and `clear_generated_terrain`.

Another plugin uses the same `manifest()` / `invoke()` contract. The host contract, the CLI, and how a folder or an entry point is discovered are documented in `plugins/host/README.md`.
