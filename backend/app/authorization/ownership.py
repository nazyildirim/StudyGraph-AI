"""Reusable authorization policies (role access and non-disclosing ownership).

Implements Revision 3 §10:
- Deny-by-default role and ownership checks.
- Authoritative role is always read from the DB-loaded `User` object, never
  from a JWT claim.
- Both non-existent resources and unauthorized resource access raise the exact
  same `ResourceNotFoundError` so callers cannot enumerate resource IDs.
- No concrete module resolvers (#7/#8) are implemented here; future modules
  will supply their own `ResourceOwnerResolver` implementations.
"""

from __future__ import annotations

from typing import Protocol

from app.authorization.roles import Role
from app.models.user import User

RESOURCE_NOT_FOUND_MESSAGE = "Resource not found."
INSUFFICIENT_PERMISSIONS_MESSAGE = "Insufficient permissions."
DEFAULT_BYPASS_ROLES: frozenset[Role] = frozenset({Role.ADMIN})


class RoleAuthorizationError(Exception):
    """Raised when a user's database role is not permitted for an endpoint."""


class ResourceNotFoundError(Exception):
    """Raised when a resource does not exist or the user may not access it."""


class ResourceOwnerResolver(Protocol):
    """Contract for resolving the owner user ID of a domain resource."""

    def get_owner_id(self, resource_id: int) -> int | None:
        """Return the owning user's ID, or None if the resource does not exist."""
        ...


def parse_user_role(user: User) -> Role | None:
    """Safely convert a DB-loaded user's role string into a Role enum."""
    try:
        return Role(user.role)
    except ValueError:
        return None


def check_role_access(user: User, allowed_roles: frozenset[Role]) -> None:
    """Enforce deny-by-default role membership against the DB-loaded user."""
    if not allowed_roles:
        raise RoleAuthorizationError(INSUFFICIENT_PERMISSIONS_MESSAGE)

    user_role = parse_user_role(user)
    if user_role is None or user_role not in allowed_roles:
        raise RoleAuthorizationError(INSUFFICIENT_PERMISSIONS_MESSAGE)


class OwnershipPolicy:
    """Non-disclosing resource ownership check (deny by default)."""

    def check(
        self,
        user: User,
        owner_id: int | None,
        *,
        bypass_roles: frozenset[Role] = DEFAULT_BYPASS_ROLES,
    ) -> None:
        """Verify ownership or bypass role; raise ResourceNotFoundError otherwise."""
        if owner_id is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        user_role = parse_user_role(user)
        if user_role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        if user_role in bypass_roles:
            return

        if user.id == owner_id:
            return

        raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
