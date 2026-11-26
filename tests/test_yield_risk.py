"""The execute_luau freeze heuristic: flag real stalls, not snippets that merely mention a loop."""

from __future__ import annotations

import unittest

from roblox_studio_adapter.luau_gen import yield_risk


class YieldRiskTests(unittest.TestCase):
    def test_instance_new_inside_a_for_loop_is_flagged(self) -> None:
        code = "for i = 1, 500 do local p = Instance.new('Part') p.Parent = workspace end"
        self.assertIsNotNone(yield_risk(code))

    def test_instance_new_outside_a_property_loop_passes(self) -> None:
        # Two one-off parts and a loop that only sets properties: the case that tripped in a real session.
        code = """
local plate = workspace.Baseplate
for _, t in plate:GetChildren() do
    if t:IsA("Texture") then t.StudsPerTileU = 16 end
end
local probe = Instance.new("Part")
probe.Parent = workspace
"""
        self.assertIsNone(yield_risk(code))

    def test_while_and_repeat_bodies_count(self) -> None:
        self.assertIsNotNone(yield_risk("local i = 0 repeat Instance.new('Part') i += 1 until i > 9"))
        self.assertIsNotNone(yield_risk("while true do end"))

    def test_nested_function_inside_a_loop_counts(self) -> None:
        code = "for i = 1, 9 do local function make() return Instance.new('Part') end make() end"
        self.assertIsNotNone(yield_risk(code))

    def test_loop_closed_before_the_instance(self) -> None:
        code = "for i = 1, 3 do if i > 1 then print(i) end end local p = Instance.new('Part')"
        self.assertIsNone(yield_risk(code))

    def test_keywords_in_strings_and_comments_are_ignored(self) -> None:
        code = """
-- for each part we would do Instance.new, but not here
local s = "while for do end"
local t = [[ for i = 1, 3 do ]]
--[[ while true do end ]]
local p = Instance.new("Part")
"""
        self.assertIsNone(yield_risk(code))

    def test_task_wait_clears_it(self) -> None:
        code = "for i = 1, 500 do Instance.new('Part').Parent = workspace if i % 50 == 0 then task.wait() end end"
        self.assertIsNone(yield_risk(code))


if __name__ == "__main__":
    unittest.main()
