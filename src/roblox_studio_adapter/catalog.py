"""Static knowledge about Studio MCP tools, merged with a live tools/list.

The docs page and the running server drift. ``generate_animation`` and
``generate_avatar`` are on the docs page dated 2026-11-23 and were not
advertised by the Studio build probed the same day. ``subagent`` docs say
``explore`` and ``playtest``; that build's tool description said ``explore``,
``screen_capture``, and ``unit_test``. Live tools/list wins. A tool with no
overlay is still callable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from roblox_studio_adapter.errors import ToolUnavailable

# retry: "read" may be repeated; "mutation" must not; "job" is a status poll.
SUBAGENT_TYPES_DOCS = ("explore", "playtest")
SUBAGENT_TYPES_OBSERVED = ("explore", "screen_capture", "unit_test")

OBSERVED_SKILLS = (
    "rbx-configs-experimentation",
    "rbx-create-skill",
    "rbx-debug",
    "rbx-device-simulator-lua",
    "rbx-docs-search",
    "rbx-import-asset",
    "rbx-instrument-analytics",
    "rbx-network-simulator",
    "rbx-open-cloud-usage",
    "rbx-perf-profiling",
    "rbx-permissions",
    "rbx-scene-analysis",
    "rbx-unit-test",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    summary: str
    datamodels: tuple[str, ...] = ()
    requires_studio_id: bool = True
    retry: str = "read"
    mutates: bool = False
    timeout: float = 120.0
    notes: str = ""
    documented_only: bool = False
    schema: dict | None = None

    @property
    def available(self) -> bool:
        return not self.documented_only


def _tool(
    name: str,
    group: str,
    summary: str,
    *,
    dm: tuple[str, ...] = (),
    retry: str = "read",
    mutates: bool = False,
    timeout: float = 120.0,
    notes: str = "",
    documented_only: bool = False,
    studio: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        group=group,
        summary=summary,
        datamodels=dm,
        requires_studio_id=studio,
        retry=retry,
        mutates=mutates,
        timeout=timeout,
        notes=notes,
        documented_only=documented_only,
    )


def static_tools() -> dict[str, ToolSpec]:
    tools = [
        _tool("list_roblox_studios", "session", "List connected Studio instances.", studio=False, notes="Call this before any other tool. Every other call needs the id."),
        _tool("get_studio_state", "session", "Play state and which datamodels exist.", notes="Returns a short bullet list, not JSON."),
        _tool("save_place", "session", "Save the open place without publishing.", retry="mutation", mutates=True, notes="Do this when the user asked to save, not after every edit. Status is Saved, NotNeeded, NeedsUserAction, Busy, or Failed."),
        _tool("submit_feedback", "feedback", "Send one Studio-tool issue to Roblox.", retry="mutation", mutates=True, notes="The layer never calls this unless you do. No source, personal data, or credentials."),
        _tool("list_plugin_actions", "session", "List built-in Studio toggle actions."),
        _tool("open_plugin", "session", "Turn a built-in toggle action on or off.", retry="mutation", mutates=True, notes="Pass all four ids from list_plugin_actions. Cloud and local plugins are opened by setting the widget Enabled through execute_luau."),
        _tool("script_read", "scripts", "Read a script, with line numbers, or a line range.", notes="Path looks like game.ServerScriptService.MyScript. Does not create scripts."),
        _tool("multi_edit", "scripts", "Apply exact string replacements, or create a script.", dm=("Edit",), retry="mutation", mutates=True, notes="Edit datamodel only. old_string must match exactly. Creating a script needs className and a first edit whose old_string is empty. The whole batch is atomic."),
        _tool("script_search", "scripts", "Fuzzy search of script names. At most 10 hits.", notes="Not a wildcard. A miss is the sentence 'No matches found'."),
        _tool("script_grep", "scripts", "Search script source. At most 50 hits.", notes="The query is a string or a Luau pattern. The layer escapes it when literal=True."),
        _tool("search_game_tree", "datamodel", "Flat listing of the instance tree.", dm=("Edit", "Client", "Server"), notes="Default depth 3, hard cap 10, default head 200. A truncated page starts with a Note line and then a JSON array. Paths have no game. prefix."),
        _tool("inspect_instance", "datamodel", "Properties, attributes, and children of one path.", notes="Case-insensitive. Up to 20 matches when names collide. Some services return properties as an empty list; read those with execute_luau."),
        _tool("execute_luau", "luau", "Run Luau on the Edit, Client, or Server datamodel.", dm=("Edit", "Client", "Server"), retry="mutation", mutates=True, timeout=180, notes="Main thread until the first yield. Chunk instance work and task.wait() once per chunk. Do not parent a huge subtree in one assignment."),
        _tool("start_stop_play", "playtest", "Start or stop a solo playtest.", retry="mutation", mutates=True, notes="Does not expose Test Here, Team Test, or multi-client. Stop resets runtime instances."),
        _tool("get_console_output", "playtest", "Read the Studio output log.", notes="The whole log comes back. Diff it against the previous snapshot."),
        _tool("screen_capture", "playtest", "Capture the current viewport.", timeout=90, notes="Prefer this over video. Camera arguments are for edit-time framing. During play, leave the camera alone unless you mean to move it."),
        _tool("video_capture", "playtest", "Start or stop a playtest recording.", dm=("Client",), retry="mutation", mutates=True, timeout=90, notes="Client datamodel only. Use it for motion, timing, stutter, or flicker. Status partial means the capture ended early, not that gameplay ended."),
        _tool("character_navigation", "input", "Walk the playtest character to a point or an instance.", dm=("Client",), retry="mutation", mutates=True, notes="Speed multiplier is 0.1 to 10."),
        _tool("user_keyboard_input", "input", "Send an ordered list of keyboard actions.", dm=("Client",), retry="mutation", mutates=True),
        _tool("user_mouse_input", "input", "Send an ordered list of mouse actions.", dm=("Client",), retry="mutation", mutates=True, notes="After the first positioned step, later steps can reuse that position."),
        _tool("subagent", "playtest", "Run a Studio subagent once and take its summary.", retry="mutation", mutates=True, timeout=300, notes="No nesting and no back-and-forth. Prefer the playtest service over a playtest subagent; the type list disagrees between the docs and the tool description."),
        _tool("search_asset", "assets", "Search Creator Store and inventories.", notes="auto waterfalls universe, group, user, then store. Price filters require scope creator_store. Packages need assetType Package."),
        _tool("insert_asset", "assets", "Insert a numeric asset id into the place.", retry="mutation", mutates=True, notes="Pass assetName and assetType from the search hit. Image and Decal both insert as a Decal."),
        _tool("upload_image", "assets", "Upload HTTP image URLs and return rbxassetid values.", retry="mutation", mutates=True, notes="These are URLs, not local files. Local files go through store_image."),
        _tool("store_image", "assets", "Load a local png or jpeg (max 5 MB) and return an IMAGEID uri.", retry="mutation", mutates=True),
        _tool("generate_mesh", "assets", "Generate a textured mesh from a prompt.", retry="mutation", mutates=True, timeout=300, notes="Call with async true and poll wait_job_finished. Explicit parts need partNames, max 8. maxTriangles is 12 to 20000."),
        _tool("generate_material", "assets", "Generate a MaterialVariant.", retry="mutation", mutates=True, timeout=300, notes="The result is a base material and a variant name. Set both on the part. The layer does not apply them unless you ask."),
        _tool("generate_procedural_model", "assets", "Build a parametric part model from a prompt.", retry="mutation", mutates=True, timeout=300, notes="The tool inserts the model. Default to async. Pass the user's words through; do not describe an attached image yourself."),
        _tool("generate_texture", "assets", "Re-texture a MeshPart or Model in place.", retry="mutation", mutates=True, timeout=300),
        _tool("generate_scene", "assets", "Generate a scene of models and parts from a prompt or images.", retry="mutation", mutates=True, timeout=300, notes="No async flag on this build. Give the call a long timeout."),
        _tool("segment_mesh", "assets", "Split a mesh into at most 5 named parts.", retry="mutation", mutates=True, timeout=300, notes="Inserts a sibling model. Does not delete the source."),
        _tool("auto_setup_avatar", "assets", "Rig a Workspace model as an R15 avatar beside the source.", retry="mutation", mutates=True, timeout=420, notes="Usually 3 to 5 minutes. Platform is marketplace-shaped. Development is for in-experience NPCs. Do not set Selection with execute_luau."),
        _tool("generate_animation", "assets", "Generate an R15 animation, or convert an R6 animation.", retry="mutation", mutates=True, timeout=300, documented_only=True, notes="Listed on the MCP docs page. Not advertised by the probed Studio build."),
        _tool("generate_avatar", "assets", "Generate a rigged R15 avatar from a prompt.", retry="mutation", mutates=True, timeout=420, documented_only=True, notes="Listed on the MCP docs page. Not advertised by the probed Studio build."),
        _tool("wait_job_finished", "assets", "Poll a background generation.", retry="job", timeout=70, notes="External clients are capped at about 45 seconds per call. Poll again while status is Running."),
        _tool("http_get", "docs", "Fetch an allowed Roblox docs URL.", timeout=60, notes="URL must end in .md or be llms.txt, under the Creator docs, engine reference, cloud reference, performance docs, or Roblox/libmp. The JSON search API is not on this allowlist; the docs service fetches that directly."),
        _tool("list_skills", "skills", "List Studio skills and when to load them."),
        _tool("skill", "skills", "Load one skill body.", notes="Load a skill before the domain work it describes. User copies of built-in skills replace the original and stop receiving updates."),
        _tool("create_skill", "skills", "Publish a custom skill.", retry="mutation", mutates=True, notes="Name cannot start with rbx-."),
        _tool("edit_skill", "skills", "Edit a user skill.", retry="mutation", mutates=True, notes="Built-in rbx- skills are not editable. Duplicate them in Studio first."),
        _tool("open_cloud_invoke", "cloud", "Call an Open Cloud API with the scopes granted in Studio.", retry="mutation", mutates=True, timeout=90, notes="Endpoint is a path under https://apis.roblox.com, never a full URL. The client never sees the token. 403 means the scope is off. 401 is retried once. Unpublished places cannot use this."),
    ]
    return {tool.name: tool for tool in tools}


class Registry:
    """Overlay plus the tools this Studio actually advertised."""

    def __init__(self, overlay: dict[str, ToolSpec] | None = None) -> None:
        self.overlay = dict(overlay or static_tools())
        self.live: dict[str, ToolSpec] = {}
        self.refreshed = False

    @classmethod
    def with_static(cls) -> Registry:
        registry = cls()
        registry.assume_documented_live()
        return registry

    def assume_documented_live(self) -> None:
        """Treat every non-documented_only overlay tool as advertised. Used by tests."""
        self.live = {name: spec for name, spec in self.overlay.items() if not spec.documented_only}
        self.refreshed = True

    def refresh(self, listed: list[dict]) -> None:
        live: dict[str, ToolSpec] = {}
        for item in listed:
            name = str(item.get("name") or "")
            if not name:
                continue
            if name.startswith("Roblox_Studio__"):
                name = name[len("Roblox_Studio__") :]
            schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else None
            base = self.overlay.get(name) or ToolSpec(
                name=name,
                group="unlisted",
                summary=str(item.get("description") or "Advertised by this Studio build."),
                retry="read",
            )
            live[name] = replace(base, documented_only=False, schema=schema, summary=base.summary or str(item.get("description") or ""))
        self.live = live
        self.refreshed = True

    def get(self, name: str) -> ToolSpec:
        clean = name[len("Roblox_Studio__") :] if name.startswith("Roblox_Studio__") else name
        if clean in self.live:
            return self.live[clean]
        if clean in self.overlay:
            raise ToolUnavailable(
                f"{clean} is in the compatibility catalog, but this Studio MCP server did not advertise it. "
                "Update Studio, or call list_tools() and use a tool that is actually present."
            )
        raise ToolUnavailable(f"Unknown Studio tool {clean!r}. Call list_tools() to see this build.")

    def names(self) -> list[str]:
        return sorted(self.live)

    def missing_from_live(self) -> list[str]:
        return sorted(name for name in self.overlay if name not in self.live)

    def unknown_to_overlay(self) -> list[str]:
        return sorted(name for name in self.live if name not in self.overlay)

    def add_overlay(self, spec: ToolSpec) -> None:
        self.overlay[spec.name] = spec
        if self.refreshed and spec.name in self.live:
            self.live[spec.name] = replace(spec, schema=self.live[spec.name].schema, documented_only=False)
