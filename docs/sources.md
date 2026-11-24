# Sources

Read on 2026-11-23 while this layer was written. Page bodies change. `agent.docs.search` and `agent.docs.read` are how an agent checks a claim later.

## Read closely

| Page | Why it matters here |
| --- | --- |
| https://create.roblox.com/docs/studio/mcp | Tool list, stdio setup, path shapes, playtest and generation tools |
| https://create.roblox.com/docs/studio/mcp-open-cloud | Scopes, 401/403, upload folders, live data stores via `execute_luau` |
| https://create.roblox.com/docs/en-us/ai/coding-harness | Script Sync plus MCP, and the warning that the two writers can fight |
| https://create.roblox.com/docs/en-us/ai/accelerated-workflows | Where the MCP toggle lives, and what Assistant is for |
| https://create.roblox.com/docs/en-us/assistant/mcp | Assistant's own MCP page and bring-your-own-key. Dated 2026-11-14 in the hub |
| https://create.roblox.com/docs/projects/data-model | Services, the place tree, replication at a high level |
| https://create.roblox.com/docs/projects/client-server | Server authority, StreamingEnabled, playtest latency defaulting to none |
| https://create.roblox.com/docs/scripting/locations | Which container gets a Script, LocalScript, or ModuleScript, and RunContext |
| https://create.roblox.com/docs/studio/testing-modes | Solo Test versus Test Here, Team Test, and StudioTestService (up to 8 clients, plugin-side) |
| https://create.roblox.com/docs/projects/teleport | `TeleportAsync` works in Studio Test, Team Test, and MCP playtest inside one experience. `Teleport` does not |
| https://create.roblox.com/docs/llms.txt | Hub index and the agent instructions (search, append `.md`, read `latest-features.json`, do not pull `llms-full.txt`) |

`llms.txt` was read from the top, including those agent instructions and the start of the index. It was not inlined. The hub is about 2,400 pages. Treating the index as "read" would be false.

## Checked through search snippets, not a full page pass

Assistant guide, build-with-assistant, StudioTestService, and the DevForum posts that announced MCP tool batches. Snippets were used to confirm names (multi-client testing is plugin-only, subagent types, skill names). Before relying on one of those details in a live place, open the page with `agent.docs.read`.

## Live evidence that overrides the docs page

On 2026-11-23 the open Studio advertised 39 tools. The MCP docs page also lists `generate_animation` and `generate_avatar`. They were not in `tools/list`, so the catalog marks them `documented_only`.

The same page's `subagent` description offers `explore` and `playtest`. The live tool description offered `explore`, `screen_capture`, and `unit_test`. The schema is a free string. This package does not send a playtest subagent. `PlaytestService` is the supported loop.

Payload shapes used by the parsers were observed that day, not copied from a schema:

- `list_roblox_studios` and `get_studio_state` come back as bullet text, not JSON.
- `search_game_tree` may start with `Note: Output limited to N nodes` and then a JSON array. Paths have no `game.` prefix. The root is the place name, class `DataModel`. Service display names can contain spaces (`Run Service`).
- `inspect_instance` on Workspace returned `properties: []`. On `Workspace.Baseplate` it returned stringified property values (`Size` as `"2048, 16, 2048"`, colors as `"r, g, b"`).
- `script_search` and `script_grep` misses are the sentence `No matches found for the given query.`
- `execute_luau` returned `HttpService:JSONEncode` output as text that `json.loads` accepts.
- A positive `script_read`, `screen_capture`, and `save_place` body was not captured. Those parsers accept the documented line-numbered script form and fall back to raw text.

The launcher observed was `%LOCALAPPDATA%\Roblox\mcp.bat`, which started `StudioMCP.exe` from `Versions\version-8d7a1009c17e4ff8`. The binary speaks newline-delimited JSON. `Content-Length` framing was not present. The decoder still accepts it.

Play-mode wording (`Current Studio Mode: Play`, `Available DataModels: Client, Server`) is inferred from the Edit-mode bullet layout. If `doctor` prints a state line this parser does not understand, it raises `StateParseError` and keeps the raw text. Update `parse_studio_state` from that text.
