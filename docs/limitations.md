# Limitations and best practices

Observed against Studio MCP on 2026-11-23 (`StudioMCP.exe` from `version-8d7a1009c17e4ff8`) and the docs listed in `sources.md`. Re-check with `python -m roblox_studio_adapter doctor` after a Studio update. The live tool list wins.

## Docs versus this build

| Docs say | This build did |
| --- | --- |
| `generate_animation`, `generate_avatar` exist | Not advertised. Calling them raises `ToolUnavailable`. |
| `subagent` types include `playtest` | Description listed `explore`, `screen_capture`, `unit_test`. Use `PlaytestService`. |
| `http_get` can read docs | Only `.md` and `llms.txt` under Creator docs, the engine reference, cloud reference, performance docs, or `github.com/Roblox/libmp`. |
| Search is `GET /docs/api/search?q=` | That URL is not on the `http_get` allowlist. `DocsService.search` uses `urllib` from this process. |

`doctor` prints catalog tools missing from the live server, and live tools the overlay does not know.

## Data model

- Tree paths omit `game.`. Script paths include it. The services convert. Mixing them in a raw `agent.call` will miss.
- Dots inside an instance name break both dialects. Rename, or address the instance from a parent with `FindFirstChild` inside `execute_luau`.
- `search_game_tree` defaults to depth 3 and head 200, and refuses depth above 10. A truncated page starts with a Note line. `walk()` follows unexplored children for at most 8 calls.
- `inspect_instance` on some services returns an empty property list. `read_properties` uses `execute_luau` for the names you pass. Property values that do come back are often strings (`"2048, 16, 2048"`, `"Enum.Material.Plastic"`), not typed objects.
- Up to 20 inspect hits when the match is not unique.
- `multi_edit` is Edit only. Writing a script while a playtest is running stops the playtest.
- Changes made in Play do not persist. Stop resets the runtime DataModel. Edit the Edit DataModel.
- `datamodel.apply` will not set `Source`. It will not destroy `Workspace`, `Lighting`, or `ServerScriptService`. Destroy is still an edit-session delete. Studio undo can bring the instance back. The package does not call undo.
- Client and Server during play are different copies. StreamingEnabled means the client tree is a subset. Pass the datamodel you mean.

## Play and input

- Solo play only. No Test Here, no Team Test, no multi-client. Those remain Studio UI or a plugin.
- `playtest.run` always stops when `stop=True` (the default), including when the screenshot fails. An error from `stop()` can replace the earlier error.
- The playtest camera is left alone. `capture.screenshot(position=..., look_at=...)` is for edit-time framing. Pass both, or neither.
- Video status `partial` means the recording ended early. It does not mean the playtest ended.
- `record()` starts play if needed and leaves it running after the clip. Stop it yourself before the next script edit.

## Generation

- `generate_material` does not apply the result. Set `Material` to the base material and `MaterialVariant` to the variant name.
- `generate_procedural_model` inserts itself. `wait=False` by default. Poll `wait_job` when you need the instance.
- `generate_scene` is not given the async flag. Call it with a long timeout.
- There is no dedicated `auto_setup_avatar` wrapper. Use `agent.call("auto_setup_avatar", {...}, timeout=420)`. Do not set Selection from Luau for that tool.
- `maxTriangles` on mesh generation is 12 to 20000. Explicit part names cap at 8. `segment_mesh` splits into at most 5 parts and does not delete the source.

## Saves, cloud, and safety

- `save_place` statuses: `Saved`, `NotNeeded`, `NeedsUserAction`, `Busy`, `Failed`. The facade retries `Busy` once. It never publishes.
- First save of a place that has never been saved needs the user.
- If `notesSaved` is false, do not call save again only to retry the notes.
- Open Cloud endpoint is a path under `https://apis.roblox.com`, never a full URL, and this client never sees the token. 401 is retried once. 403 becomes `PermissionDenied`.
- High-risk scopes and paths are refused unless `allow_high_risk=True`. That includes DELETE, publish, bans, secrets, developer products, game passes, data-store writes, memory-store scopes (including reads, because the prefix matches), and messaging publish.
- Uploads only succeed from folders the user approved. Do not move files into those folders on the user's behalf.
- DataStoreService and MemoryStoreService inside `execute_luau` are live when the scopes are enabled. They are not a local sandbox.
- `submit_feedback` is wrapped as `agent.feedback` and is never called by the other services.

## Script Sync

The coding-harness guide uses Script Sync for `.luau` files and MCP for everything else. If both write one script, the last writer wins and you will not be able to tell which buffer is current. Use one writer per script.

## Protocol

- Single-threaded. One in-flight request per agent.
- Read retries can reconnect. Mutation retries do not happen. A drop during a mutation is `AmbiguousOutcome`.
- A mutation timeout does not reconnect. The tool may still be running.
- Positive response bodies for `script_read`, `screen_capture`, and `save_place` were not captured live. If a future Studio changes those strings, the raw text is still on the result. Update the parser from that text.
- Play-mode `get_studio_state` wording was inferred from the Edit bullet layout. A parse failure raises `StateParseError` and keeps `raw`.

## Best practices

- Prefer `overview` and a depth-2 tree over a full dump.
- Prefer `scripts.replace` for a small edit so you do not rewrite a whole ModuleScript blindly. `replace` counts matches locally and refuses an ambiguous one.
- Prefer screenshots over video.
- Prefer `playtest.run` over a playtest subagent.
- Read `context.brief()` back into the model instead of the console log.
- After `AmbiguousOutcome` or a timeout, `script_read` or `inspect` before you try the write again.
- Ask the user before save, publish, feedback, high-risk cloud, and avatar setup.
