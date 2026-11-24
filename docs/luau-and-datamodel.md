# Luau and the data model

A short map for an agent that is about to call `execute_luau` or `datamodel.apply`. The engine reference is the authority for each class. Fetch it with `agent.docs.engine_class("RemoteEvent")` rather than quoting this file as the API.

## The place is a tree

The root is a `DataModel`. Its children are services. `search_game_tree` shows the place name as that root (`Place1`, class `DataModel` in the 2026-11-23 session). Paths below the root look like `Workspace.Baseplate`. `game.Workspace` is the same instance when you are writing Luau. It is the wrong string for the tree tool.

Services you almost always want before any others are listed as `FOCUS_SERVICES` in `services/datamodel.py`: Workspace, Lighting, ReplicatedFirst, ReplicatedStorage, ServerScriptService, ServerStorage, StarterGui, StarterPack, StarterPlayer, SoundService, MaterialService, TextChatService, Teams.

Display names and class names differ. The tree can show `Run Service` for class `RunService`. Use the class name when you call `GetService`. Use the path the tree gave you when you call `inspect`.

## Who runs the code

| Where it runs | Who it sees | What persists |
| --- | --- | --- |
| Edit datamodel | The place as saved in the editor | Yes, until you undo or revert |
| Server during play | Server copy, full authority | No. Stop deletes it |
| Client during play | The local player's copy. Streaming may omit instances | No |

The server is the authority for game state. A LocalScript must not be the only copy of a purchase, a score, or a door that matters. RemoteEvents and RemoteFunctions cross the boundary. The client can ask. The server decides.

`StreamingEnabled` sends the client a subset of Workspace. An instance missing on the client can still exist on the server.

Playtest latency defaults to 0, so a bug that only shows up with delay will not show up in `playtest.run` unless you set latency in Studio yourself. This package does not change network simulation.

## Script classes

| Class | Runs |
| --- | --- |
| Script with RunContext Legacy | Server, and only if it lives in a server container such as ServerScriptService |
| Script with RunContext Server | Server, from the containers that allow it |
| Script with RunContext Client | Client. One copy in ReplicatedStorage stays put, so Output points at a stable path |
| LocalScript | Client, after it is copied into the player from a starter container |
| ModuleScript | Nowhere until something `require`s it |

StarterGui, StarterPack, StarterPlayerScripts, and StarterCharacterScripts are templates. Play clones them. Edit the template in Edit mode.

ServerStorage is invisible to the client. ReplicatedStorage is visible to both. Do not put secrets in ReplicatedStorage.

## Patterns this package emits

Instance batches (`luau_gen.apply_chunk`):

- Resolve the parent with `FindFirstChild` along the dot path.
- If the name exists and the class matches, update it. If the class differs, error. Do not destroy and recreate.
- Assign properties, then attributes, then `Parent` for a new instance. Parenting last avoids a half-built instance replicating.
- One `task.wait()` after the chunk, not inside the property loop.
- Return `HttpService:JSONEncode({ ok = true, paths = made })`.

Property probes (`property_reader`) return JSON. `datamodel.read_properties("Workspace.Baseplate", ["Size", "Anchored"])` is the supported form.

`luau.query("1 + 1")` wraps the expression. It is for values, not for scripts that need to yield.

## Main thread

Studio runs the snippet on the main thread until the first yield. A tight loop freezes the editor, including the MCP server, so the client will time out while Studio is still busy. That timeout is not a license to send the snippet again.

Safe shape for a large build:

```lua
local batch = 0
for _, spec in ipairs(specs) do
    local part = Instance.new("Part")
    part.Name = spec.name
    part.Parent = workspace
    batch += 1
    if batch % 50 == 0 then
        task.wait()
    end
end
```

`UnyieldingLuau` is a local guess from the source text (a `while` with no `task.wait`, or `Instance.new` inside a `for` with no `task.wait`). It is not Studio's own guard. A snippet can still freeze Studio if the heuristic misses it. Keep probes small.

## Apply spec

```python
{
    "parent": "Workspace",
    "name": "Marker",
    "class_name": "Part",
    "properties": {
        "Anchored": True,
        "Size": {"x": 4, "y": 1, "z": 4},
        "Color": {"r": 1, "g": 0, "b": 0},
        "CFrame": {"position": {"x": 0, "y": 5, "z": 0}},
    },
    "attributes": {"Role": "marker"},
}
```

Numbers that are whole become Luau integers (`Vector3.new(4, 1, 4)`). Enums are `{"enum": "Material", "name": "Neon"}` when you need one. See `luau_literal` in `luau_gen.py` for Vector2, UDim2, Color3, and CFrame.

## Replication checklist

- Create the server script in ServerScriptService.
- Put shared modules in ReplicatedStorage.
- Put client scripts in StarterPlayerScripts or one client Script in ReplicatedStorage.
- Create RemoteEvents in ReplicatedStorage from the server script or from `datamodel.apply`, not from a LocalScript that might lose the race.
- Read the server result with `datamodel="Server"` during play if you need to know what the server actually did.
