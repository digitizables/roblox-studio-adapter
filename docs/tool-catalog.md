# Tool catalog

The overlay in `src/roblox_studio_adapter/catalog.py` is the source of truth for retry policy and datamodels. `python -m roblox_studio_adapter catalog` prints it without connecting. Live `tools/list` can add tools. Those stay callable through `agent.call`.

`studio_id` is injected for every tool except `list_roblox_studios`. Datamodel is injected only when the overlay lists one and the play state makes the choice unambiguous.

## Session

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `list_roblox_studios` | `agent.studios()` | read, no studio id |
| `get_studio_state` | `agent.playtest.state()` | read |
| `save_place` | `agent.save()` | mutation. Busy retried once inside `save`. Never publishes |
| `submit_feedback` | `agent.feedback()` | mutation. Never called automatically |
| `list_plugin_actions` | `agent.call` | read |
| `open_plugin` | `agent.call` | mutation. Pass all four ids from the list |

## Scripts

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `script_read` | `agent.scripts.read` | read. Edit or play, the file is the saved script |
| `multi_edit` | `write`, `replace` | mutation, Edit only. Whole batch is atomic |
| `script_search` | `agent.scripts.find` | read. At most 10 fuzzy name hits. Not a wildcard |
| `script_grep` | `agent.scripts.grep` | read. At most 50 hits. `literal=True` escapes Luau pattern characters |

## Data model and Luau

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `search_game_tree` | `datamodel.tree`, `children`, `overview`, `walk` | read. Edit, Client, or Server |
| `inspect_instance` | `datamodel.inspect` | read |
| `execute_luau` | `luau.run`, `luau.query`, `datamodel.apply`, `destroy`, `read_properties` | mutation, because it can change the place. Edit, Client, or Server. Timeout 180s |

## Play and capture

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `start_stop_play` | `playtest.start`, `stop`, `run` | mutation. Solo play only |
| `get_console_output` | `playtest.console`, `console_since_snapshot` | read. Full log. Diff it |
| `screen_capture` | `capture.screenshot` | read. Timeout 90s. Base64 stored as a file |
| `video_capture` | `playtest.record` | mutation, Client only |
| `subagent` | `agent.call` only | mutation. No nesting. Do not use it as the playtest loop |

## Input (Client, playtest running)

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `character_navigation` | `agent.input.walk_to` | mutation. Speed 0.1–10 |
| `user_keyboard_input` | `agent.input.press`, `type_text` | mutation |
| `user_mouse_input` | `agent.input.click` | mutation |

## Assets

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `search_asset` | `assets.search` | read. Price filters need the `creator_store` scope |
| `insert_asset` | `assets.insert` | mutation. Pass name and type from the hit |
| `upload_image` | `agent.call` | mutation. HTTP URLs, not local files |
| `store_image` | `assets.store_image` | mutation. Local png or jpeg, 5 MB, returns an IMAGEID uri |
| `generate_mesh` | `assets.generate_mesh` | mutation. `async=true`, then `wait_job` |
| `generate_material` | `assets.generate_material` | mutation. Does not assign the variant onto a part |
| `generate_procedural_model` | `assets.generate_procedural_model` | mutation. Inserts the model. `wait` defaults to false |
| `generate_texture` | `agent.call` | mutation. Re-textures a MeshPart or Model in place |
| `generate_scene` | `agent.call` | mutation. No async flag on this build |
| `segment_mesh` | `agent.call` | mutation. At most 5 parts. Keeps the source |
| `auto_setup_avatar` | `agent.call` with timeout 420 | mutation. Often 3–5 minutes |
| `wait_job_finished` | `assets.wait_job` | job poll. About 45s per call, so the helper loops |
| `generate_animation` | none | documented only, until `tools/list` shows it |
| `generate_avatar` | none | documented only, until `tools/list` shows it |

## Docs, skills, cloud

| Tool | Wrapper | Policy |
| --- | --- | --- |
| `http_get` | `docs.read`, `docs.engine_class` | read. Allowlisted `.md` and `llms.txt` only |
| `list_skills` | `skills.list` | read |
| `skill` | `skills.load`, `skills.ensure` | read |
| `create_skill` | `agent.call` | mutation. Name cannot start with `rbx-` |
| `edit_skill` | `agent.call` | mutation. Built-in `rbx-` skills are not editable |
| `open_cloud_invoke` | `cloud.invoke` | mutation. Path only. High-risk calls need `allow_high_risk=True` |

`docs.search` and `docs.latest_features` do not use `http_get`. The search API and `latest-features.json` are fetched with `urllib` because Studio would reject those URLs.

## Adding a tool

```python
from roblox_studio_adapter.catalog import ToolSpec

agent.session.registry.add_overlay(ToolSpec(
    name="example_tool",
    group="session",
    summary="One line.",
    datamodels=("Edit", "Client", "Server"),
    retry="read",  # or "mutation" or "job"
    mutates=False,
    timeout=120,
))
agent.call("example_tool", {})
```

Set `documented_only=True` on a tool you have only seen in the docs. The session then raises `ToolUnavailable` instead of sending a call the server will reject. Clear that flag, or omit it, once `doctor` shows the tool as advertised.
