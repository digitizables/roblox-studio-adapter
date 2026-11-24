"""Explore and update the instance tree without a pile of one-off tool calls."""

from __future__ import annotations

from typing import Any

from roblox_studio_adapter.errors import EditError, ToolFailed
from roblox_studio_adapter.luau_gen import apply_chunk, chunked, property_reader
from roblox_studio_adapter.parsers import parse_inspect, parse_tree
from roblox_studio_adapter.paths import tree_path
from roblox_studio_adapter.results import InspectResult, TreeNode, TreePage
from roblox_studio_adapter.services.luau import LuauService
from roblox_studio_adapter.session import Session

# Containers an agent almost always wants before it dumps every service.
FOCUS_SERVICES = (
    "Workspace",
    "Lighting",
    "ReplicatedFirst",
    "ReplicatedStorage",
    "ServerScriptService",
    "ServerStorage",
    "StarterGui",
    "StarterPack",
    "StarterPlayer",
    "SoundService",
    "MaterialService",
    "TextChatService",
    "Teams",
)


class DataModelService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def tree(
        self,
        path: str | None = None,
        *,
        instance_type: str | None = None,
        keywords: str | None = None,
        max_depth: int = 3,
        head_limit: int = 200,
        datamodel: str | None = None,
    ) -> TreePage:
        chosen = datamodel or self._default_datamodel()
        if max_depth < 1 or max_depth > 10:
            raise EditError("max_depth must be from 1 to 10.")
        result = self.session.call(
            "search_game_tree",
            {
                "path": tree_path(path),
                "instance_type": instance_type,
                "keywords": keywords,
                "max_depth": max_depth,
                "head_limit": head_limit,
            },
            datamodel=chosen,
        )
        page = parse_tree(result.text)
        page.note = (page.note + f" datamodel={chosen}").strip()
        return page

    def children(self, path: str, **kwargs: Any) -> TreePage:
        return self.tree(path, max_depth=1, **kwargs)

    def overview(self, *, datamodel: str | None = None) -> dict[str, TreePage]:
        """One shallow page per container an agent usually edits.

        A full-tree call is truncated at the head limit and is mostly services.
        Asking for each focus service keeps the useful instances.
        """
        pages: dict[str, TreePage] = {}
        for service in FOCUS_SERVICES:
            try:
                pages[service] = self.tree(service, max_depth=2, head_limit=80, datamodel=datamodel)
            except ToolFailed:
                continue
        return pages

    def walk(
        self,
        path: str | None = None,
        *,
        instance_type: str | None = None,
        keywords: str | None = None,
        datamodel: str | None = None,
        head_limit: int = 200,
        max_calls: int = 8,
    ) -> list[TreeNode]:
        """Follow truncation and unexplored-child summaries, with a hard call budget."""
        seen: dict[str, TreeNode] = {}
        queue = [path]
        calls = 0
        while queue and calls < max_calls:
            current = queue.pop(0)
            page = self.tree(
                current,
                instance_type=instance_type,
                keywords=keywords,
                max_depth=4,
                head_limit=head_limit,
                datamodel=datamodel,
            )
            calls += 1
            for node in page.nodes:
                if node.full_path:
                    seen[node.full_path] = node
                if node.unexplored_child_count and node.full_path and node.full_path not in queue:
                    queue.append(node.full_path)
            if page.truncated and current is not None:
                # Narrow by class only when the page itself was cut off.
                break
        return list(seen.values())

    def inspect(self, path: str) -> InspectResult:
        result = self.session.call("inspect_instance", {"path": tree_path(path)})
        parsed = parse_inspect(result.text)
        return parsed

    def read_properties(self, path: str, names: list[str], *, datamodel: str | None = None) -> dict[str, Any]:
        """Read specific properties when inspect_instance returns none.

        ``path`` is a tree path such as ``Workspace.Baseplate``.
        """
        code = property_reader(tree_path(path) or "", names)
        payload = LuauService(self.session).run_json(code, datamodel=datamodel, allow_unyielding=True)
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise ToolFailed("execute_luau", str(payload))
        properties = payload.get("properties")
        return properties if isinstance(properties, dict) else {}

    def apply(self, specs: list[dict[str, Any]], *, chunk_size: int = 50, datamodel: str | None = None) -> list[str]:
        """Create or update instances. New instances are parented one at a time, then the chunk waits.

        Each spec needs ``parent``, ``name``, and ``class_name``. ``properties`` and
        ``attributes`` are optional. Refuses ``Source``; use the scripts service.
        """
        if chunk_size < 1 or chunk_size > 200:
            raise EditError("chunk_size must be from 1 to 200. Smaller chunks keep Studio responsive.")
        made: list[str] = []
        for batch in chunked(specs, chunk_size):
            normalized = []
            for spec in batch:
                item = dict(spec)
                if item.get("parent"):
                    item["parent"] = tree_path(str(item["parent"]))
                normalized.append(item)
            payload = LuauService(self.session).run_json(
                apply_chunk(normalized),
                datamodel=datamodel or "Edit",
                allow_unyielding=True,
            )
            if isinstance(payload, dict) and isinstance(payload.get("paths"), list):
                made.extend(str(path) for path in payload["paths"])
        return made

    def destroy(self, path: str, *, datamodel: str | None = None) -> str:
        """Destroy one instance. This is permanent for the open edit session until undo."""
        target = tree_path(path)
        if not target or target in {"Workspace", "Lighting", "ServerScriptService"}:
            raise EditError(f"Refusing to destroy {path!r}. Pass a child instance, not a service.")
        from roblox_studio_adapter.luau_gen import luau_string

        code = f"""
local HttpService = game:GetService("HttpService")
local function resolve(path)
    local current = game
    for _, segment in ipairs(string.split(path, ".")) do
        if segment ~= "game" and segment ~= "" then
            current = current:FindFirstChild(segment)
            if current == nil then
                return nil
            end
        end
    end
    return current
end
local inst = resolve({luau_string(target)})
if inst == nil then
    return HttpService:JSONEncode({{ ok = false, error = "missing" }})
end
local full = inst:GetFullName()
inst:Destroy()
return HttpService:JSONEncode({{ ok = true, path = full }})
""".strip()
        payload = LuauService(self.session).run_json(code, datamodel=datamodel or "Edit", allow_unyielding=True)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ToolFailed("execute_luau", str(payload))
        return str(payload.get("path"))

    def _default_datamodel(self) -> str:
        state = self.session.refresh_state()
        if state.playing:
            return "Server"
        return "Edit"
