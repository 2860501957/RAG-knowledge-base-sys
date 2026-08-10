from __future__ import annotations

from typing import Any

from backend.domain import DocumentChunk, UserContext


DEFAULT_ROLE = "employee"
ADMIN_ROLE = "admin"


def normalize_user_context(user_context: UserContext | dict[str, Any] | None) -> UserContext:
    if user_context is None:
        return UserContext()
    if isinstance(user_context, UserContext):
        return UserContext(
            user_id=(user_context.user_id or "anonymous").strip() or "anonymous",
            roles=_normalize_values(user_context.roles) or (DEFAULT_ROLE,),
        )
    return UserContext(
        user_id=str(user_context.get("user_id") or "anonymous").strip() or "anonymous",
        roles=_normalize_values(user_context.get("roles")) or (DEFAULT_ROLE,),
    )


def can_read_chunk(chunk: DocumentChunk, user_context: UserContext | dict[str, Any] | None) -> bool:
    user = normalize_user_context(user_context)
    metadata = chunk.metadata or {}
    visibility = str(metadata.get("visibility") or "internal").strip().lower()
    roles = set(user.roles)
    allowed_roles = set(_normalize_values(metadata.get("allowed_roles")))
    allowed_users = set(_normalize_values(metadata.get("allowed_users")))

    if visibility == "public":
        return True
    if ADMIN_ROLE in roles:
        return True
    if user.user_id in allowed_users:
        return True
    if roles & allowed_roles:
        return True
    if visibility in {"internal", ""}:
        return bool(user.user_id and user.user_id != "anonymous")
    if visibility in {"restricted", "private"}:
        return False
    return False


def describe_access(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "visibility": str(metadata.get("visibility") or "internal"),
        "allowed_roles": list(_normalize_values(metadata.get("allowed_roles"))),
        "allowed_users": list(_normalize_values(metadata.get("allowed_users"))),
    }


def _normalize_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).replace(";", ",").split(","))
    else:
        raw_items = str(value).replace(";", ",").split(",")
    normalized = []
    for item in raw_items:
        clean = item.strip().strip("[]'\" ")
        if clean:
            normalized.append(clean)
    return tuple(dict.fromkeys(normalized))
