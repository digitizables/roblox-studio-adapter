"""Read and edit scripts through script_read and multi_edit."""

from __future__ import annotations

from roblox_studio_adapter.errors import EditError
from roblox_studio_adapter.luau_gen import ensure_folders
from roblox_studio_adapter.parsers import parse_script_read
from roblox_studio_adapter.paths import (
    SCRIPT_CLASSES,
    parent_script_path,
    recommend_script_class,
    script_tool_path,
    segments,
)
from roblox_studio_adapter.results import ScriptDocument, ScriptWriteResult
from roblox_studio_adapter.session import Session


class ScriptService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def read(self, path: str, *, start: int | None = None, end: int | None = None) -> ScriptDocument:
        target = script_tool_path(path)
        arguments: dict = {"target_file": target}
        if start is not None or end is not None:
            if start is None or end is None:
                raise EditError("Pass both start and end line numbers, or neither to read the whole script.")
            arguments.update(
                {
                    "should_read_entire_file": False,
                    "start_line_one_indexed": start,
                    "end_line_one_indexed_inclusive": end,
                }
            )
        result = self.session.call("script_read", arguments)
        document = parse_script_read(target, result.text)
        if start is None:
            self.session.context.remember_script(target, document.source)
        return document

    def grep(self, query: str, *, literal: bool = True) -> str:
        pattern = escape_luau_pattern(query) if literal else query
        result = self.session.call("script_grep", {"query": pattern})
        self.session.context.note("script_grep", "capped at 50 matches")
        return result.text

    def find(self, keywords: str) -> str:
        """Fuzzy name search. ``keywords`` is comma-separated, not a wildcard."""
        result = self.session.call("script_search", {"keywords": keywords})
        return result.text

    def write(self, path: str, source: str, *, class_name: str | None = None) -> ScriptWriteResult:
        """Create a script or replace its whole source.

        ``class_name`` is required when the script does not exist, unless you
        pass ``"auto"`` and want the location rule from the scripting guide.
        """
        target = script_tool_path(path)
        source = source.replace("\r\n", "\n").replace("\r", "\n")
        self._ensure_edit_mode()
        self._ensure_parent_folders(target)
        existing = self._existing_source(target)
        if existing is None:
            chosen, note = _resolve_class(target, class_name)
            self.session.call(
                "multi_edit",
                {
                    "file_path": target,
                    "className": chosen,
                    "edits": [{"old_string": "", "new_string": source}],
                },
            )
            self.session.context.remember_script(target, source)
            return ScriptWriteResult(path=target, created=True, unchanged=False, class_name=chosen, note=note)
        if existing == source:
            return ScriptWriteResult(path=target, created=False, unchanged=True, class_name=class_name, note="source already matches")
        self._replace_all(target, existing, source)
        self.session.context.remember_script(target, source)
        return ScriptWriteResult(path=target, created=False, unchanged=False, class_name=class_name)

    def replace(
        self,
        path: str,
        old: str,
        new: str,
        *,
        replace_all: bool = False,
    ) -> ScriptWriteResult:
        """Replace an exact snippet. Refuses an ambiguous match before calling Studio."""
        if old == "":
            raise EditError("old text is empty. Use write() to create a script or replace the whole source.")
        if old == new:
            raise EditError("old and new text are the same, so multi_edit would reject the edit.")
        target = script_tool_path(path)
        self._ensure_edit_mode()
        document = self.read(target)
        count = document.source.count(old)
        if count == 0:
            crlf = document.source.replace("\n", "\r\n")
            if old in crlf:
                old = old.replace("\n", "\r\n")
                count = crlf.count(old)
        if count == 0:
            raise EditError(f"{old!r} was not found in {target}. Read the script and copy the snippet exactly, including whitespace.")
        if count > 1 and not replace_all:
            raise EditError(
                f"{old!r} appears {count} times in {target}. Pass replace_all=True or include more surrounding lines."
            )
        self.session.call(
            "multi_edit",
            {"file_path": target, "edits": [{"old_string": old, "new_string": new, "replace_all": replace_all}]},
        )
        self.session.context.forget_script(target)
        return ScriptWriteResult(path=target, created=False, unchanged=False, class_name=None)

    def _replace_all(self, target: str, existing: str, source: str) -> None:
        try:
            self.session.call(
                "multi_edit",
                {"file_path": target, "edits": [{"old_string": existing, "new_string": source}]},
            )
        except EditError:
            raise
        except Exception as exc:
            # A line-ending mismatch is the usual reason a full-file old_string misses.
            if "old_string" not in str(exc).lower() and "not found" not in str(exc).lower():
                raise
            crlf = existing.replace("\n", "\r\n")
            self.session.call(
                "multi_edit",
                {"file_path": target, "edits": [{"old_string": crlf, "new_string": source}]},
            )

    def _existing_source(self, target: str) -> str | None:
        try:
            return self.read(target).source
        except Exception as exc:
            text = str(exc).lower()
            missing = (
                "not found",
                "does not exist",
                "doesn't exist",
                "cannot find",
                "could not find",
                "couldn't find",
                "no script",
            )
            if any(phrase in text for phrase in missing):
                return None
            raise

    def _ensure_edit_mode(self) -> None:
        state = self.session.refresh_state(force=True)
        if state.playing or not state.can_edit_scripts:
            from roblox_studio_adapter.services.playtest import PlaytestService

            PlaytestService(self.session).stop()

    def _ensure_parent_folders(self, target: str) -> None:
        parent = parent_script_path(target)
        parts = segments(parent)
        if len(parts) <= 1:
            return
        # The service itself must already exist. Create only the folders under it.
        code = ensure_folders(parts)
        from roblox_studio_adapter.services.luau import LuauService

        LuauService(self.session).run(code, datamodel="Edit", allow_unyielding=True)


def escape_luau_pattern(text: str) -> str:
    """Escape a literal so script_grep does not treat it as a Luau pattern."""
    magic = set("().%+-*?[]^$")
    return "".join(f"%{char}" if char in magic else char for char in text)


def _resolve_class(path: str, class_name: str | None) -> tuple[str, str]:
    if class_name == "auto":
        chosen, reason = recommend_script_class(path)
        return chosen, reason
    if class_name is None:
        try:
            suggested, reason = recommend_script_class(path)
        except EditError:
            suggested, reason = "", "no location rule matched"
        hint = f" Suggested class_name={suggested!r} ({reason})." if suggested else ""
        raise EditError(f"Creating {path} requires class_name (Script, LocalScript, or ModuleScript).{hint} Pass class_name='auto' to accept the suggestion.")
    if class_name not in SCRIPT_CLASSES:
        raise EditError(f"class_name must be Script, LocalScript, or ModuleScript, not {class_name!r}.")
    return class_name, ""


