# Agent playbook

Use this order. It matches `python -m roblox_studio_adapter steps` and the constraints on the MCP tools.

1. List Studio windows. If several are open, ask which place. Do not pick one by being first.
2. Load the Studio skill that matches the task (`agent.skills.list()`, then `agent.skills.load(name)` or `ensure`). The built-in names observed were `rbx-debug`, `rbx-docs-search`, `rbx-scene-analysis`, `rbx-unit-test`, `rbx-permissions`, `rbx-open-cloud-usage`, `rbx-import-asset`, `rbx-perf-profiling`, `rbx-network-simulator`, `rbx-device-simulator-lua`, `rbx-instrument-analytics`, `rbx-configs-experimentation`, `rbx-create-skill`. A custom skill cannot start with `rbx-`. A user copy of a built-in skill stops receiving Roblox's updates.
3. Before you call an API from memory, `agent.docs.latest_features()` and `agent.docs.search(question)`. Then `agent.docs.read(url)` or `agent.docs.engine_class("Part")`. Search goes to `/docs/api/search` over HTTPS because `http_get` rejects that URL. Page reads go through Studio's `http_get` when a session is connected.
4. Explore with `agent.loop.explore()` or `datamodel.overview()`. Do not request the whole DataModel in one `search_game_tree`. The tool truncates, and most of a full dump is services you already know.
5. Edit in Edit mode. `scripts.write` and `scripts.replace` stop a playtest because `multi_edit` cannot run while playing. `datamodel.apply` targets Edit.
6. Play with `playtest.run`. Pass `expect_contains` for the print you expect and `expect_absent` for a line that must not appear. Pass `probes` when the check is a Server or Client value, because stop deletes that copy. Each check is named. `passed` is false when any check fails. `forbid_errors=False` if the place already logs errors you do not own. Persist `evidence_record(report)` or `change_and_verify(...)["evidence"]`. Fields are in `docs/evidence.md`. When `console.reset` is true, the checks saw the whole later log.
7. Screenshot for a still. Record video only when the question is motion, timing, stutter, or flicker. Video is Client-only and is heavier than a screenshot.
8. Stop before the next edit. Instances created during play are gone after stop. StarterPlayer, StarterGui, and StarterPack are copied at runtime. Change the starter, not the copy inside the player.
9. Save only when the person asked. `agent.save()` never publishes. If status is `NeedsUserAction`, stop and tell the person. If notes fail to save, do not save again just to retry the notes.
10. For Open Cloud, call `agent.cloud.invoke` with a path such as `/cloud/v2/universes/123`. A 403 means the scope is off in Assistant → MCP Permissions. Tell the person. The agent cannot enable it. Unpublished places cannot use Open Cloud.

## Path dialects

| Tool family | Path |
| --- | --- |
| `script_read`, `multi_edit` | `game.ServerScriptService.Hello` |
| `search_game_tree`, `inspect_instance` | `Workspace.Baseplate` |

`script_tool_path` adds `game.` when it is missing. `tree_path` strips it. Names that contain a dot cannot be addressed this way. `inspect_instance` is case-insensitive and can return up to 20 matches. Use `unique_id` when names collide.

## Where a new script should live

`class_name="auto"` follows the script-location guide:

| Parent | Class |
| --- | --- |
| ServerScriptService | Script |
| ServerStorage | ModuleScript (scripts there do not run) |
| StarterPlayerScripts, StarterCharacterScripts, StarterGui, StarterPack | LocalScript |
| ReplicatedStorage, ReplicatedFirst | ModuleScript |
| Workspace | Script, with a warning to prefer a ModuleScript required from ServerScriptService |

`RunContext` Legacy runs on the server and only from a server container. A client Script left in a starter container is copied, and both copies can run. Prefer one client Script with `RunContext` Client in ReplicatedStorage when you want a stable Output path.

Do not attach gameplay scripts to parts in Workspace unless the script ships inside a model.

## Luau from the agent

`execute_luau` runs on Studio's main thread until it yields. A `while` loop without `task.wait`, or a `for` loop that calls `Instance.new` without `task.wait`, is refused by `LuauService.run` unless you pass `allow_unyielding=True`.

`datamodel.apply` already chunks 50 instances, sets properties before `Parent`, parents each new instance on its own, and calls `task.wait()` once per chunk. It refuses `Source`. Script source goes through `scripts.write`.

`luau.query("game.Workspace.Baseplate.Name")` JSON-encodes the value. `HttpService:JSONEncode` does not need HttpEnabled.

Luau in this package uses `ipairs` / `pairs`, not generalized `for k, v in tbl`.

## Playtests

`start_stop_play` toggles a solo play. It does not expose Test Here, Team Test, or multi-client. `StudioTestService` can run up to 8 clients and is a plugin API, not an MCP tool.

Default playtest latency is 0. With `StreamingEnabled`, the client receives a subset of Workspace. Read server state with `datamodel="Server"` and client state with `datamodel="Client"`. Do not treat one as the other.

`TeleportService:TeleportAsync` works in a Studio playtest inside the same experience without publishing. `TeleportService:Teleport` does not.

Keyboard, mouse, and `character_navigation` require Client and a running playtest. `InputService` does not start play for you when nothing is playing. Speed is clamped to 0.1–10.

## Assets

Long generations (`generate_mesh`, `generate_material`, `generate_procedural_model`) are sent with `async=true`. Poll with `assets.wait_job`. Each `wait_job_finished` call is capped around 45 seconds for an external client, so the helper loops. `generate_scene` has no async flag on this build. Give that call a long timeout through `agent.call`.

`generate_procedural_model` inserts the model itself. `generate_material` does not assign the variant. Read the base material and the variant name, then set both on the part. `auto_setup_avatar` commonly takes 3–5 minutes. Do not set Selection with `execute_luau` to aim that tool. Call it with `timeout=420`.

`store_image` is a local png or jpeg up to 5 MB and returns an `IMAGEID` uri. `upload_image` is for HTTP URLs. Insert assets with the `assetName` and `assetType` from the search hit. Image and Decal both insert as a Decal.

## What not to do

- Do not call `agent.feedback` as part of a normal loop. It sends text to Roblox. No source, personal data, or credentials. 4000 bytes max.
- Do not publish, and do not call universe write or place write scopes unless the person confirmed and you passed `allow_high_risk=True`.
- Do not copy files into an approved upload folder to sneak an upload through.
- Do not re-run a mutation that returned `AmbiguousOutcome` until you have read the place.
- Do not dump base64 screenshots back into the model. The paths are on the result.
