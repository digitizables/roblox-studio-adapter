"""Build small, yielding Luau programs for execute_luau.

execute_luau runs on Studio's main thread. A loop that creates instances and
never calls task.wait can freeze Studio and drop the MCP connection. Parenting
one huge subtree is itself one unyielding write, so each new instance is
parented on its own and the program waits once per chunk.
"""

from __future__ import annotations

import math
import re
from typing import Any

from roblox_studio_adapter.errors import EditError

_ENUM = re.compile(r"^Enum\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_HELPERS = """
local HttpService = game:GetService("HttpService")

local function resolve(path)
    local current = game
    if path == nil or path == "" or path == "game" then
        return game
    end
    for _, segment in ipairs(string.split(path, ".")) do
        if segment ~= "game" and segment ~= "" then
            local child = current:FindFirstChild(segment)
            if child == nil and current == game then
                local ok, service = pcall(function()
                    return game:GetService(segment)
                end)
                if ok then
                    child = service
                end
            end
            if child == nil then
                return nil
            end
            current = child
        end
    end
    return current
end

local function encode(value, depth)
    depth = depth or 0
    if depth > 6 then
        return "<max-depth>"
    end
    local kind = typeof(value)
    if kind == "nil" or kind == "number" or kind == "boolean" or kind == "string" then
        return value
    elseif kind == "Vector3" then
        return { type = "Vector3", x = value.X, y = value.Y, z = value.Z }
    elseif kind == "Vector2" then
        return { type = "Vector2", x = value.X, y = value.Y }
    elseif kind == "Color3" then
        return { type = "Color3", r = value.R, g = value.G, b = value.B }
    elseif kind == "CFrame" then
        local p = value.Position
        return { type = "CFrame", x = p.X, y = p.Y, z = p.Z }
    elseif kind == "EnumItem" then
        return tostring(value)
    elseif kind == "Instance" then
        return { type = "Instance", path = value:GetFullName(), className = value.ClassName }
    elseif kind == "table" then
        local out = {}
        for key, item in pairs(value) do
            out[tostring(key)] = encode(item, depth + 1)
        end
        return out
    end
    return tostring(value)
end
""".strip()


def luau_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\0", "\\0")
    )
    return f'"{escaped}"'


def luau_literal(value: Any) -> str:
    """Encode a Python value as a Luau literal. Strings are always quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EditError("Luau literals cannot be NaN or infinity")
        return repr(value)
    if isinstance(value, str):
        if _ENUM.match(value):
            return value
        return luau_string(value)
    if isinstance(value, dict):
        kind = value.get("type")
        if kind == "Vector3":
            return "Vector3.new({x}, {y}, {z})".format(**_xyz(value))
        if kind == "Vector2":
            return "Vector2.new({x}, {y})".format(x=_num_literal(value, "x"), y=_num_literal(value, "y"))
        if kind == "Color3":
            scale = value.get("scale", "rgb")
            if scale == "unit":
                return "Color3.new({r}, {g}, {b})".format(
                    r=_num_literal(value, "r"), g=_num_literal(value, "g"), b=_num_literal(value, "b")
                )
            return "Color3.fromRGB({r}, {g}, {b})".format(
                r=_num_literal(value, "r"), g=_num_literal(value, "g"), b=_num_literal(value, "b")
            )
        if kind == "CFrame":
            if "components" in value:
                components = value["components"]
                if not isinstance(components, (list, tuple)) or len(components) != 12:
                    raise EditError("CFrame components must be 12 numbers")
                inner = ", ".join(_format_number(item) for item in components)
                return f"CFrame.new({inner})"
            return "CFrame.new({x}, {y}, {z})".format(**_xyz(value))
        if kind == "UDim2":
            return "UDim2.new({xs}, {xo}, {ys}, {yo})".format(
                xs=_num_literal(value, "x_scale"),
                xo=_num_literal(value, "x_offset"),
                ys=_num_literal(value, "y_scale"),
                yo=_num_literal(value, "y_offset"),
            )
        if kind == "BrickColor":
            return f"BrickColor.new({luau_string(str(value.get('name', '')))})"
        if kind == "Enum":
            enum_value = str(value.get("value", ""))
            if not _ENUM.match(enum_value):
                raise EditError(f"Enum value must look like Enum.Material.Plastic, got {enum_value!r}")
            return enum_value
        raise EditError(f"Unsupported Luau value type {kind!r}. Use a primitive or Vector3, Color3, CFrame, UDim2, BrickColor, or Enum.")
    raise EditError(f"Cannot encode {type(value).__name__} as a Luau literal")


def yield_risk(code: str) -> str | None:
    """Return a warning when the snippet matches the freeze pattern from the tool docs."""
    has_wait = "task.wait" in code
    has_while = re.search(r"\bwhile\b", code) is not None
    has_for = re.search(r"\bfor\b", code) is not None
    creates = "Instance.new" in code
    if has_while and not has_wait:
        return (
            "This while-loop never calls task.wait(). execute_luau runs on Studio's main thread "
            "until it yields, and a spin loop freezes Studio and can drop the MCP connection."
        )
    if has_for and creates and not has_wait:
        return (
            "This loop creates instances without task.wait(). Split the work into chunks, "
            "parent each chunk's instances one at a time, and call task.wait() once per chunk."
        )
    return None


def property_reader(path: str, names: list[str]) -> str:
    if not names:
        raise EditError("read_properties needs at least one property name")
    for name in names:
        if not _IDENT.match(name):
            raise EditError(f"Property name {name!r} is not an identifier")
    listed = ", ".join(luau_string(name) for name in names)
    return f"""
{_HELPERS}
local inst = resolve({luau_string(path)})
if inst == nil then
    return HttpService:JSONEncode({{ ok = false, error = "missing instance" }})
end
local names = {{ {listed} }}
local properties = {{}}
for _, name in ipairs(names) do
    local ok, value = pcall(function()
        return inst[name]
    end)
    if ok then
        properties[name] = encode(value, 0)
    else
        properties[name] = {{ type = "error", message = tostring(value) }}
    end
end
return HttpService:JSONEncode({{ ok = true, path = inst:GetFullName(), properties = properties }})
""".strip()


def ensure_folders(path_segments: list[str]) -> str:
    """Create missing Folder instances under an existing service. Does not create services."""
    if not path_segments:
        raise EditError("Cannot create folders for an empty path")
    listed = ", ".join(luau_string(segment) for segment in path_segments)
    return f"""
{_HELPERS}
local segments = {{ {listed} }}
local current = game
for _, name in ipairs(segments) do
    local child = current:FindFirstChild(name)
    if child == nil and current == game then
        local ok, service = pcall(function()
            return game:GetService(name)
        end)
        if ok and service ~= nil then
            child = service
        end
    end
    if child == nil then
        if current == game then
            error("No service named " .. name)
        end
        child = Instance.new("Folder")
        child.Name = name
        child.Parent = current
    end
    current = child
end
return current:GetFullName()
""".strip()


def apply_chunk(specs: list[dict[str, Any]]) -> str:
    """One yielding program that creates or updates a small batch of instances.

    Each spec is ``{"parent", "name", "class_name", "properties", "attributes"}``.
    ``parent`` is a tree path without the ``game.`` prefix, or ``"Workspace"``.
    """
    if not specs:
        raise EditError("apply_chunk needs at least one instance")
    rendered = ",\n".join(_spec_table(spec) for spec in specs)
    return f"""
{_HELPERS}
local function apply(spec)
    local parent = resolve(spec.parent)
    if parent == nil then
        error("missing parent " .. tostring(spec.parent))
    end
    local inst = parent:FindFirstChild(spec.name)
    local created = false
    if inst == nil then
        inst = Instance.new(spec.className)
        inst.Name = spec.name
        created = true
    elseif inst.ClassName ~= spec.className then
        error(inst:GetFullName() .. " is a " .. inst.ClassName .. ", not a " .. spec.className)
    end
    for key, value in pairs(spec.properties) do
        inst[key] = value
    end
    for key, value in pairs(spec.attributes) do
        inst:SetAttribute(key, value)
    end
    if created then
        inst.Parent = parent
    end
    return inst:GetFullName()
end
local specs = {{
{rendered}
}}
local made = {{}}
for _, spec in ipairs(specs) do
    table.insert(made, apply(spec))
end
task.wait()
return HttpService:JSONEncode({{ ok = true, paths = made }})
""".strip()


def json_query(expression: str) -> str:
    """Wrap a Luau expression so the tool result is JSON text."""
    if "\n" in expression:
        raise EditError("json_query takes a single expression. Use run() for statements.")
    return f"""
{_HELPERS}
local function __run()
    return ({expression})
end
local ok, value = xpcall(__run, debug.traceback)
if not ok then
    return HttpService:JSONEncode({{ ok = false, error = tostring(value) }})
end
return HttpService:JSONEncode({{ ok = true, value = encode(value, 0) }})
""".strip()


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    if size < 1:
        raise EditError("chunk size must be at least 1")
    return [items[index : index + size] for index in range(0, len(items), size)]


def _spec_table(spec: dict[str, Any]) -> str:
    parent = str(spec.get("parent") or "")
    name = str(spec.get("name") or "")
    class_name = str(spec.get("class_name") or spec.get("className") or "")
    if not parent or not name or not class_name:
        raise EditError("Each instance spec needs parent, name, and class_name")
    if not _IDENT.match(class_name):
        raise EditError(f"class_name {class_name!r} is not a Luau identifier")
    properties = spec.get("properties") or {}
    attributes = spec.get("attributes") or {}
    if not isinstance(properties, dict) or not isinstance(attributes, dict):
        raise EditError("properties and attributes must be dictionaries")
    if "Source" in properties or "source" in properties:
        raise EditError("Set script source with the scripts service (multi_edit), not as an instance property.")
    prop_lines = ", ".join(f"[{luau_string(str(key))}] = {luau_literal(value)}" for key, value in properties.items())
    attr_lines = ", ".join(f"[{luau_string(str(key))}] = {luau_literal(value)}" for key, value in attributes.items())
    return (
        "    {\n"
        f"        parent = {luau_string(parent)},\n"
        f"        name = {luau_string(name)},\n"
        f"        className = {luau_string(class_name)},\n"
        f"        properties = {{ {prop_lines} }},\n"
        f"        attributes = {{ {attr_lines} }},\n"
        "    }"
    )


def _xyz(value: dict) -> dict[str, str]:
    return {"x": _num_literal(value, "x"), "y": _num_literal(value, "y"), "z": _num_literal(value, "z")}


def _format_number(value: Any) -> str:
    number = _finite(value)
    if number.is_integer():
        return str(int(number))
    return repr(number)


def _num(value: dict, key: str) -> float:
    if key not in value:
        raise EditError(f"{value.get('type', 'value')} is missing {key}")
    return _finite(value[key])


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditError(f"{value!r} is not a number") from exc
    if not math.isfinite(number):
        raise EditError("Luau literals cannot be NaN or infinity")
    return number


def _num_literal(value: dict, key: str) -> str:
    number = _num(value, key)
    if number.is_integer():
        return str(int(number))
    return repr(number)
