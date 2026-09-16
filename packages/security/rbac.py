"""Role-Based Access Control (RBAC) and permission engine.
Defaults unknown permissions to DENY.
"""

from typing import Dict, Set
from fastapi import Depends, HTTPException, status
from packages.security.auth import get_current_token_payload
from packages.shared.models import UserRole

# Explicit permission matrix mapping (Role -> Set of allowed Resource:Action strings)
ROLE_PERMISSIONS: Dict[UserRole, Set[str]] = {
    UserRole.OWNER: {
        "*:*",  # Owner has full system access
    },
    UserRole.OPERATOR: {
        "agent:read",
        "agent:start",
        "agent:pause",
        "agent:stop",
        "projects:read",
        "projects:write",
        "prospects:read",
        "prospects:write",
        "conversations:read",
        "conversations:write",
        "quotes:read",
        "quotes:write",
        "payments:read",
        "artifacts:read",
        "qa:read",
        "qa:trigger",
        "tools:read",
        "audit:read",
        "settings:read",
    },
    UserRole.AUDITOR: {
        "agent:read",
        "projects:read",
        "prospects:read",
        "conversations:read",
        "quotes:read",
        "payments:read",
        "artifacts:read",
        "qa:read",
        "audit:read",
        "tools:read",
        "metrics:read",
    },
    UserRole.WORKER_SERVICE: {
        "tasks:read",
        "tasks:update",
        "artifacts:write",
        "tools:execute",
        "qa:write",
    },
}


def is_permission_allowed(role: UserRole, permission: str) -> bool:
    """Evaluate whether a role possesses an explicit permission. Unknown permissions default to False (DENY)."""
    allowed_perms = ROLE_PERMISSIONS.get(role, set())
    if "*:*" in allowed_perms:
        return True
    if permission in allowed_perms:
        return True

    # Check prefix wildcard (e.g. "projects:*")
    resource = permission.split(":")[0] if ":" in permission else permission
    if f"{resource}:*" in allowed_perms:
        return True

    return False


def require_permission(permission: str):
    """FastAPI dependency factory enforcing strict RBAC permission on endpoint access."""
    async def permission_checker(payload: dict = Depends(get_current_token_payload)) -> dict:
        user_role_str = payload.get("role")
        try:
            role = UserRole(user_role_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unknown role. Access denied by default policy.",
            )

        if not is_permission_allowed(role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role.value}' does not have required permission '{permission}'",
            )
        return payload

    return permission_checker
