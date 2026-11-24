"""open_cloud_invoke with the permission rules from the Open Cloud MCP guide.

High-risk calls are refused unless the caller passes allow_high_risk=True.
The person at the keyboard still has to enable the scope in Studio. This
guard only stops the agent from firing one by accident.
"""

from __future__ import annotations

from roblox_studio_adapter.errors import HighRiskRefused, PermissionDenied, ToolFailed
from roblox_studio_adapter.parsers import extract_json
from roblox_studio_adapter.session import Session

_HIGH_RISK_PREFIXES = (
    "universe:write",
    "universe.place:write",
    "universe.place.instance:write",
    "universe-places:write",
    "developer-product:",
    "game-pass:",
    "ad.campaign:",
    "universe.user-restriction:",
    "universe.secret:",
    "universe-datastores.objects:update",
    "universe-datastores.objects:delete",
    "memory-store:",
    "universe-messaging-service:publish",
)

_HIGH_RISK_PATH_BITS = (
    "/publish",
    ":publish",
    "/user-restrictions",
    "/secrets",
    "/developer-products",
    "/game-passes",
)


def assess_cloud_call(method: str, endpoint: str, scopes: list[str] | None, *, allow_high_risk: bool) -> None:
    if not endpoint.startswith("/"):
        raise HighRiskRefused("endpoint must be a path starting with /, not a full URL. Example: /cloud/v2/universes/123")
    if "apis.roblox.com" in endpoint or endpoint.startswith("http"):
        raise HighRiskRefused("Pass the path under https://apis.roblox.com, not the full URL.")
    if allow_high_risk:
        return
    upper = method.upper()
    if upper == "DELETE":
        raise HighRiskRefused("DELETE is refused unless allow_high_risk=True.")
    for scope in scopes or []:
        if any(scope.startswith(prefix) or scope == prefix.rstrip(":") for prefix in _HIGH_RISK_PREFIXES):
            raise HighRiskRefused(
                f"Scope {scope!r} can publish, spend, ban, or write live data. "
                "Enable it in Studio's MCP Permissions, then pass allow_high_risk=True."
            )
    if upper != "GET":
        lowered = endpoint.lower()
        for bit in _HIGH_RISK_PATH_BITS:
            if bit in lowered:
                raise HighRiskRefused(
                    f"{method} {endpoint} looks high-risk ({bit}). Pass allow_high_risk=True after a person confirms it."
                )


class CloudService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def invoke(
        self,
        method: str,
        endpoint: str,
        *,
        body: str | None = None,
        scopes: list[str] | None = None,
        files: list[dict] | None = None,
        allow_high_risk: bool = False,
    ) -> dict:
        assess_cloud_call(method, endpoint, scopes, allow_high_risk=allow_high_risk)
        arguments: dict = {"method": method.upper(), "endpoint": endpoint, "scopes": scopes, "body": body, "files": files}
        policy = "read" if method.upper() == "GET" else "mutation"
        try:
            result = self.session.call("open_cloud_invoke", arguments, retry=policy)
        except ToolFailed as exc:
            self._raise_permission(exc)
            if "401" in exc.detail:
                result = self.session.call("open_cloud_invoke", arguments, retry=policy)
            else:
                raise
        if "401" in result.text:
            result = self.session.call("open_cloud_invoke", arguments, retry=policy)
        self._raise_permission(ToolFailed("open_cloud_invoke", result.text) if _denied(result.text) else None)
        payload = extract_json(result.text)
        return payload if isinstance(payload, dict) else {"text": result.text}

    def _raise_permission(self, exc: ToolFailed | None) -> None:
        if exc is None:
            return
        detail = exc.detail
        if _denied(detail):
            raise PermissionDenied(
                detail + " Enable the scope under Assistant, Settings, MCP Permissions. "
                "The agent cannot turn permissions on. Unpublished places cannot use Open Cloud."
            ) from exc


def _denied(text: str) -> bool:
    lowered = text.lower()
    return (
        "has not been granted" in lowered
        or "403" in lowered
        or "lacking capability" in lowered
        or "not in the assistant http allowlist" in lowered
        or "studio access to apis is not allowed" in lowered
        or "not in an approved upload" in lowered
    )
