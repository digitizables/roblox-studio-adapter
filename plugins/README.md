# Plugins

Plugins sit beside `roblox-studio-adapter`. The adapter stays a client for Studio's MCP server. A plugin depends on the adapter. The adapter does not import plugins.

```
plugins/host/    roblox-studio-plugin-host, and the roblox-plugins CLI
```

A plugin is a Python object with `manifest()` and `invoke()`. The host discovers it from a `plugin.json` folder or from the `roblox_studio.plugins` entry point, records an install under `%USERPROFILE%/.roblox-studio-plugins`, and opens Studio only when a command is about to edit the place and the caller has confirmed.

Programmatic use of a plugin is the primary path. The CLI is there for people and for agents that would rather shell out.

The terrain plugin is not in this repository. It lives at [github.com/digitizables/roblox-terrain](https://github.com/digitizables/roblox-terrain) and depends on this host.

See `plugins/host/README.md` for the contract. `docs/plugins.md` is the short version from the adapter's point of view.
