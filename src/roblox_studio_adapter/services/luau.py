"""execute_luau with the main-thread guard from the tool description."""

from __future__ import annotations

import json
from typing import Any

from roblox_studio_adapter.errors import ToolFailed, UnyieldingLuau
from roblox_studio_adapter.luau_gen import json_query, yield_risk
from roblox_studio_adapter.parsers import extract_json
from roblox_studio_adapter.session import Session


class LuauService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run(
        self,
        code: str,
        *,
        datamodel: str | None = None,
        allow_unyielding: bool = False,
    ) -> str:
        warning = yield_risk(code)
        if warning and not allow_unyielding:
            raise UnyieldingLuau(warning)
        result = self.session.call("execute_luau", {"code": code}, datamodel=datamodel)
        self.session.invalidate_state()
        return result.text

    def query(self, expression: str, *, datamodel: str | None = None) -> Any:
        """Evaluate one Luau expression and JSON-decode the structured result."""
        raw = self.run(json_query(expression), datamodel=datamodel, allow_unyielding=True)
        payload = extract_json(raw)
        if not isinstance(payload, dict):
            raise ToolFailed("execute_luau", raw)
        if payload.get("ok") is False:
            raise ToolFailed("execute_luau", str(payload.get("error") or raw))
        return payload.get("value")

    def run_json(self, code: str, *, datamodel: str | None = None, allow_unyielding: bool = False) -> Any:
        text = self.run(code, datamodel=datamodel, allow_unyielding=allow_unyielding)
        value = extract_json(text)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value if value is not None else text
