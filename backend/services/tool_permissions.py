from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.domain import UserContext
from backend.services.access_control import ADMIN_ROLE, normalize_user_context


TOOL_ROLE_POLICIES: dict[str, set[str]] = {
    "search_knowledge_base": {"employee", "manager", "admin"},
    "ask_knowledge_base": {"employee", "manager", "admin"},
    "list_documents": {"admin"},
}


@dataclass(frozen=True)
class ToolPermissionDecision:
    tool: str
    user_id: str
    roles: tuple[str, ...]
    allowed: bool
    required_roles: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "user_id": self.user_id,
            "roles": list(self.roles),
            "allowed": self.allowed,
            "required_roles": list(self.required_roles),
            "reason": self.reason,
        }


def check_tool_permission(
    tool: str,
    user_context: UserContext | dict[str, Any] | None,
) -> ToolPermissionDecision:
    user = normalize_user_context(user_context)
    required_roles = TOOL_ROLE_POLICIES.get(tool)
    if required_roles is None:
        return ToolPermissionDecision(
            tool=tool,
            user_id=user.user_id,
            roles=user.roles,
            allowed=False,
            required_roles=(),
            reason="unknown_tool",
        )

    role_set = set(user.roles)
    allowed = ADMIN_ROLE in role_set or bool(role_set & required_roles)
    return ToolPermissionDecision(
        tool=tool,
        user_id=user.user_id,
        roles=user.roles,
        allowed=allowed,
        required_roles=tuple(sorted(required_roles)),
        reason="allowed" if allowed else "missing_required_role",
    )
