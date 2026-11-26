# roblox-studio-adapter

A Python compatibility layer for the [Roblox Studio MCP server](https://create.roblox.com/docs/studio/mcp). It lets an external agent plan, edit, playtest, and iterate against the Studio window that is already open, with fewer raw MCP calls and with the failure modes the server actually has.

The package launches Studio's own `mcp.bat` over stdio. It does not talk through another client's tool prefix. Another MCP client can stay connected at the same time. Studio allows more than one.

This is a client library. It is not an autonomous agent, and it is not [Roblox's official assistant plugin](https://github.com/Roblox/roblox-studio-agent-plugin). It also does not replace the third-party Studio MCP servers, which connect through their own plugins. This package speaks to `StudioMCP.exe`, the server that ships inside Studio. It is not affiliated with Roblox Corporation.

```python
from roblox_studio_adapter import RobloxStudio

with RobloxStudio.connect() as agent:
    page = agent.datamodel.tree("Workspace", max_depth=2)
    print(page.note, len(page.nodes))
```

## What this is grounded in

The Creator Hub index (`llms.txt`) lists on the order of 2,400 pages. This project is not a dump of that index. It is built from the pages that define how an agent drives Studio, plus a live `tools/list` against Studio on 2026-11-23:

- [Connect to the Roblox Studio MCP server](https://create.roblox.com/docs/studio/mcp)
- [Use Open Cloud with the Studio MCP server](https://create.roblox.com/docs/studio/mcp-open-cloud)
- [Build with a coding harness](https://create.roblox.com/docs/en-us/ai/coding-harness)
- [AI on Roblox](https://create.roblox.com/docs/en-us/ai/accelerated-workflows)
- [MCP servers (Assistant, bring your own key)](https://create.roblox.com/docs/en-us/assistant/mcp)
- Data model, client-server runtime, and script locations (see `docs/sources.md`)
- The 39 tools that Studio advertised that day, which win when they disagree with the docs page

Anything else should be fetched on demand with `agent.docs.search` and `agent.docs.read`. Do not guess a docs URL. The agent instructions on the hub say to search, then append `.md`.

## Requirements

- Windows, because the launcher path is `%LOCALAPPDATA%\Roblox\mcp.bat`.
- Python 3.11 or newer. No third-party packages.
- Roblox Studio open on the place you mean to work in.
- Assistant → **…** → **Manage MCP Servers** → **Enable Studio as MCP server**.

## Setup

```powershell
git clone https://github.com/digitizables/roblox-studio-adapter.git
cd roblox-studio-adapter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
roblox-studio-adapter doctor
```

Or, without installing, from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m roblox_studio_adapter steps
```

Check the connection without changing the place:

```powershell
python -m roblox_studio_adapter doctor
python -m roblox_studio_adapter tree --path Workspace --depth 2
```

`doctor` prints the negotiated protocol, how many tools this Studio advertised, which catalog tools are missing, and which advertised tools have no overlay yet. `tree` prints one shallow page.

## Usage

List windows, then explore. Both are read-only.

```python
from roblox_studio_adapter import RobloxStudio

with RobloxStudio.connect() as agent:
    for studio in agent.studios():
        print(studio.name, studio.id, studio.mode)
    report = agent.loop.explore()
    print(report["mode"], report["services"].keys())
```

When more than one Studio window is open, `connect()` raises `AmbiguousStudioError`. Pass `name_contains="Place1"` or `studio_id=...`.

Write a script, then play long enough to see Output. This **does** change the open place. It does not save and it does not publish.

```python
with RobloxStudio.connect(name_contains="Place1") as agent:
    agent.scripts.write(
        "game.ServerScriptService.HelloAgent",
        "print('hello from the agent')\n",
        class_name="auto",
    )
    report = agent.playtest.run(seconds=3, expect_contains=["hello from the agent"])
    print(report.passed, report.console.text)
    print(agent.context.brief())
```

The same sequence as one call:

```python
result = agent.loop.change_and_verify(
    scripts=[{
        "path": "game.ServerScriptService.HelloAgent",
        "source": "print('hello from the agent')\n",
        "class_name": "auto",
    }],
    instances=[{
        "parent": "Workspace",
        "name": "AgentMarker",
        "class_name": "Part",
        "properties": {"Anchored": True, "Size": {"x": 4, "y": 1, "z": 4}},
    }],
    seconds=3,
    expect_contains=["hello from the agent"],
)
print(result["evidence"]["schema"], result["evidence"]["passed"])
```

`result["evidence"]` is JSON (`roblox-studio-adapter.evidence/1`). `result["playtest"]` stays a `PlaytestReport`. The field list is `docs/evidence.schema.json`.

Runnable copies live in `examples/`. Examples `03`, `04`, and `05` refuse to run until `ROBLOX_STUDIO_CONFIRM=1` is set, because they edit the place or start a playtest.

Save only when a person asked:

```python
status = agent.save()  # Saved, NotNeeded, or an exception
```

Call a tool this package has never wrapped. Unknown live tools stay callable.

```python
text = agent.call("list_plugin_actions").text
```

## What the agent should call

| Question | Call |
| --- | --- |
| Which Studio, and is it playing? | `agent.studios()`, `agent.playtest.state()` |
| What is in the place? | `agent.datamodel.overview()` or `tree(path, max_depth=2)` |
| One instance's properties | `agent.datamodel.inspect(path)`, then `read_properties` if the property list is empty |
| Find or read a script | `agent.scripts.find`, `grep`, `read` |
| Create or replace a script | `agent.scripts.write` (stops play first) |
| Patch a snippet | `agent.scripts.replace` |
| Create parts | `agent.datamodel.apply(specs)` in chunks of 50 |
| Run a probe | `agent.luau.query(expression)` |
| Did the change work? | `agent.playtest.run(seconds=..., expect_contains=[...], expect_absent=[...])` |
| Store that playtest | `evidence_record(report)` or `change_and_verify(...)["evidence"]` |
| Still picture | `agent.capture.screenshot()` |
| Motion, timing, stutter | `agent.playtest.record(perform)` |
| Creator docs | `agent.docs.search`, then `agent.docs.read` |
| Studio skill for this task | `agent.skills.ensure([...])` |
| Open Cloud | `agent.cloud.invoke("GET", "/cloud/v2/...")` |
| Remember what happened | `agent.context.brief()` |

`agent.loop.explore` and `agent.loop.change_and_verify` are the plan/build/test shortcuts. The agent still decides what to build.

## Errors, retries, context

Reads (`script_read`, tree search, console, docs) retry on a dropped connection, a timeout, or a 503/429-style result. Backoff is 0.4s, 1.0s, 2.5s, three attempts, then a reconnect.

Writes are not retried. If the connection drops after a write, you get `AmbiguousOutcome`: the edit may already be in the place. Read it back before you send it again. If a write times out, you get `TimeoutError` and the call may still be running inside Studio. The client does not kill the process just to clear a timeout.

Other errors worth catching:

- `NoStudioError`, `AmbiguousStudioError` — zero windows, or more than one and no selector.
- `ModeError` — the tool's datamodel does not match play state. Script edits need Edit. Keyboard, mouse, character navigation, and video need Client. During play, pass `datamodel="Client"` or `datamodel="Server"` yourself. The layer will not guess.
- `ToolUnavailable` — documented on the MCP page, not advertised by this Studio (`generate_animation`, `generate_avatar` on the 2026-11-23 probe).
- `UnyieldingLuau` — the snippet looks like it will stall Studio's main thread. Chunk the work and `task.wait()`, or pass `allow_unyielding=True` when you have read the code.
- `HighRiskRefused` — Open Cloud publish, bans, secrets, data-store writes, and similar. Pass `allow_high_risk=True` only after a person confirms.
- `NeedsUserAction` — `save_place` needs the user (often the first save of an unsaved place).
- `PermissionDenied` — Open Cloud returned 403. Ask the user to enable the scope. Do not route around it.

Screenshots are written under `.studio-adapter/artifacts` and the base64 is dropped. Script source is cached until it would exceed about 80,000 characters. `context.brief()` is the string to put back into the model, not the raw tool log.

## Plugins

This package does not generate terrain. `plugins/host` is a thin installer and CLI (`roblox-plugins`). A plugin depends on the adapter. The adapter does not import plugins.

The terrain plugin is its own repository: [digitizables/roblox-terrain](https://github.com/digitizables/roblox-terrain). Install the host from this repo, then install that package. See `docs/plugins.md` and `plugins/host/README.md`.

## Extending

When Roblox ships a tool, `doctor` lists it under "advertised tools with no overlay". Call it immediately:

```python
agent.call("some_new_tool", {"flag": True})
```

To teach the session how to retry and which datamodel it needs:

```python
from roblox_studio_adapter.catalog import ToolSpec

agent.session.registry.add_overlay(ToolSpec(
    name="some_new_tool",
    group="session",
    summary="What the new tool does.",
    datamodels=("Edit",),
    retry="mutation",
    mutates=True,
    timeout=120,
))
```

`retry` is `"read"`, `"mutation"`, or `"job"`. A tool marked `documented_only=True` raises `ToolUnavailable` until `tools/list` actually advertises it.

## Tests

From the repository root:

```powershell
$env:PYTHONPATH = "src;plugins/host/src"
python -m unittest tests.test_framing_parsers_luau tests.test_session tests.test_plugin_host -v
```

Name the modules. A bare `unittest discover` from a parent folder can import unrelated tests on `sys.path`.

## Limits worth knowing first

The longer notes are in `docs/limitations.md` and `docs/agent-playbook.md`. The short version:

- Two path dialects. Script tools want `game.ServerScriptService.Hello`. Tree and inspect want `Workspace.Baseplate` with no `game.` prefix. An instance whose name contains `.` cannot be addressed by a dot path.
- `multi_edit` runs in the Edit datamodel only. `write()` stops a running playtest first. Play-mode copies disappear on stop. Edit, play, stop, then edit again.
- `start_stop_play` is a solo playtest. It does not start Test Here, Team Test, or an 8-client `StudioTestService` session.
- `search_game_tree` truncates (default head 200, depth cap 10). Use `overview()` or `walk()`, not one dump of the whole game.
- `inspect_instance` sometimes returns `properties: []` for a service. Use `read_properties`.
- `generate_material` returns a base material and a variant name. You still set `Material` and `MaterialVariant` on the part. `auto_setup_avatar` takes several minutes; call it through `agent.call(..., timeout=420)`.
- `save_place` never publishes. The layer never calls `submit_feedback` unless you call `agent.feedback`.
- Script Sync and MCP can both write the same script. Pick one writer.
- DataStore and MemoryStore calls made through `execute_luau` hit the live game when those scopes are on.
- This process is single-threaded. One `RobloxStudio` serializes its RPC calls. Do not share it across threads.

## Layout

```
src/roblox_studio_adapter/    client, session, services, workflows
plugins/host/        plugin discovery, config, and the roblox-plugins CLI
examples/            read-only and opt-in mutating samples
docs/                architecture, playbook, catalog, limits, sources, plugins
tests/               framing, parsers, session policy, plugin host
```

## Related

[PROVE](https://github.com/digitizables/PROVE) stores goals, intents, and these evidence records. This package remains the Studio tool layer.

## License

[MIT](LICENSE). This project is not affiliated with, endorsed by, or sponsored by Roblox Corporation. Roblox, Roblox Studio, and Luau are trademarks of their owners.
