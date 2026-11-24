# Architecture

```
RobloxStudio
  Session            one studio id, mode cache, retry policy, argument prep
    StudioClient     initialize, tools/list, tools/call
      StdioTransport newline-delimited JSON to mcp.bat → StudioMCP.exe
  services           scripts, datamodel, luau, playtest, capture, assets,
                     docs, cloud, skills, input
  Loop               explore, change_and_verify
  Context            script cache, console watermark, screenshot files, brief()
  Registry           static overlay merged with the live tools/list
```

## Transport

`default_command()` runs `cmd.exe /c %LOCALAPPDATA%\Roblox\mcp.bat`. The process is created with `CREATE_NO_WINDOW`. On close the client terminates it and then `taskkill /F /T` so the child `StudioMCP.exe` does not stay behind.

Frames are one JSON object per line. The decoder also accepts `Content-Length` headers in case a later build adds them. Protocol versions tried, in order: `2025-06-18`, `2025-03-26`, `2024-11-05`. After `initialize`, the client sends `notifications/initialized`. `tools/list` is followed while `nextCursor` is set. A server-initiated request gets JSON-RPC `-32601`. Transport code `-32000` means the pipe dropped and becomes `StudioConnectionError`.

Grok's connected server prefixes tools as `Roblox_Studio__…`. This process talks to `StudioMCP.exe` directly, so names are unprefixed (`script_read`). If a caller passes the prefixed form, the session strips one leading `Roblox_Studio__`.

## Session

Every tool except `list_roblox_studios` gets `studio_id`. Tools whose overlay lists datamodels also get `datamodel_type`.

`prepare()` and `refresh_state()` run **outside** the session lock. The lock only covers the single in-flight RPC. Holding the lock across a state refresh would deadlock, because refresh itself is a call.

Mode choice:

- Not playing, and Edit is legal → `Edit`.
- Playing, and the tool is Client-only → `Client`.
- Playing, and the tool is Edit-only → `ModeError` (stop the playtest).
- Playing, and the tool allows Edit, Client, and Server → `ModeError` unless the caller passed `datamodel=`.

`get_studio_state` is cached for one second. Calls that do not need a datamodel skip the refresh. `get_studio_state` itself has no datamodel, so refresh does not recurse.

## Registry

`static_tools()` is the overlay: summary, datamodels, timeout, and whether a retry is safe. `Registry.refresh` merges a live `tools/list` on top. A live tool with no overlay stays callable and is treated as a mutation so a surprise tool is not retried. An overlay tool with `documented_only=True` raises `ToolUnavailable` until the server advertises it.

Add a future tool with `Registry.add_overlay` or just `agent.call`.

## Services

Services are thin. They pick the path dialect, the datamodel, and the chunking, then call `session.call`. They do not hide the raw text: parsers keep it on the result object (`raw_text`, `ToolResult.text`).

`Loop.change_and_verify` is the only multi-step workflow. It stops play, writes scripts, applies instances, plays, checks the new console lines, and stops again.

## Context

`Context` is process memory, not Studio memory.

- Script bodies are cached up to about 80,000 characters, oldest dropped first.
- Console output is a full log every time. `console_since_snapshot` diffs against the watermark and then advances it.
- Image payloads are decoded into `.studio-adapter/artifacts` and removed from the result before it returns to the agent.
- The journal line redacts `studio_id`, source, and skill bodies. It records the tool name and a short summary.

`brief()` is what an agent should re-inject. It is not a transcript.

## Threads

One session, one lock, one in-flight request. Do not share a `RobloxStudio` across threads. A second agent is a second `StudioMCP.exe` and is fine.
