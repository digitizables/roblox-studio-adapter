"""Load Studio skills before the work they describe."""

from __future__ import annotations

from roblox_studio_adapter.session import Session


class SkillService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cache: dict[str, str] = {}

    def list(self) -> str:
        return self.session.call("list_skills", {}).text

    def load(self, name: str) -> str:
        if name in self.cache:
            return self.cache[name]
        text = self.session.call("skill", {"skill_name": name}).text
        self.cache[name] = text
        return text

    def ensure(self, names: list[str]) -> dict[str, str]:
        return {name: self.load(name) for name in names}
