"""Dot paths used by Studio tools.

Two dialects show up in the same session:

* Script tools want ``game.ServerScriptService.MyScript``.
* ``search_game_tree`` and ``inspect_instance`` want ``Workspace.Baseplate``
  (no ``game.`` prefix). The tree root is the place name, class ``DataModel``.

Names that themselves contain a dot cannot be addressed this way. Names may
contain spaces (``Run Service``); splitting on ``.`` keeps that segment intact.
"""

from __future__ import annotations

from roblox_studio_adapter.errors import EditError

SCRIPT_CLASSES = frozenset({"Script", "LocalScript", "ModuleScript"})

_CLIENT_CONTAINERS = frozenset(
    {
        "StarterPlayerScripts",
        "StarterCharacterScripts",
        "StarterGui",
        "StarterPack",
    }
)


def strip_game(path: str) -> str:
    text = path.strip().strip(".")
    if text == "game":
        return ""
    if text.startswith("game."):
        return text[5:]
    return text


def script_tool_path(path: str) -> str:
    """Path form for ``script_read`` and ``multi_edit``."""
    rest = strip_game(path)
    if not rest:
        raise EditError("Script path is empty")
    _reject_empty_segments(rest)
    return "game." + rest


def tree_path(path: str | None) -> str | None:
    """Path form for ``search_game_tree`` and ``inspect_instance``."""
    if path is None:
        return None
    rest = strip_game(path)
    if not rest:
        return None
    _reject_empty_segments(rest)
    return rest


def parent_script_path(path: str) -> str:
    rest = strip_game(path)
    if "." not in rest:
        return "game"
    return "game." + rest.rsplit(".", 1)[0]


def leaf_name(path: str) -> str:
    rest = strip_game(path)
    return rest.rsplit(".", 1)[-1]


def segments(path: str) -> list[str]:
    rest = strip_game(path)
    if not rest:
        return []
    _reject_empty_segments(rest)
    return rest.split(".")


def recommend_script_class(path: str) -> tuple[str, str]:
    """Suggest a script class from where the instance will live.

    The suggestion follows the script-location guide. ``ReplicatedStorage``
    defaults to ``ModuleScript`` because a ``Script`` there only runs when
    its ``RunContext`` is set, and the original plus the copied starter
    script both run if you leave a client ``Script`` in a starter container.
    """
    parts = segments(path)
    if "ServerScriptService" in parts:
        return "Script", "ServerScriptService is the server entry container. Use ModuleScripts next to it for the actual logic."
    if "ServerStorage" in parts:
        return (
            "ModuleScript",
            "Scripts do not run from ServerStorage. Store ModuleScripts there and require them from ServerScriptService.",
        )
    if any(part in _CLIENT_CONTAINERS for part in parts):
        return (
            "LocalScript",
            "Starter containers are copied onto the player. LocalScripts are the usual citizen. Prefer one client Script with RunContext Client in ReplicatedStorage when you want a stable Output path.",
        )
    if "ReplicatedStorage" in parts or "ReplicatedFirst" in parts:
        return (
            "ModuleScript",
            "Shared code belongs in a ModuleScript. Pass class_name='Script' yourself when you are creating the single client or server entry and will set RunContext.",
        )
    if parts and parts[0] == "Workspace":
        return (
            "Script",
            "A Legacy Script in Workspace can run on the server. Prefer a tagged instance plus a ModuleScript required from ServerScriptService, unless this script ships inside a Creator Store model.",
        )
    raise EditError(
        "Pass class_name as Script, LocalScript, or ModuleScript. "
        f"No location rule matched {path!r}."
    )


def _reject_empty_segments(path: str) -> None:
    parts = path.split(".")
    if any(part == "" for part in parts):
        raise EditError(f"Path {path!r} has an empty segment. Instance names that contain '.' cannot be used in dot paths.")
