"""Role definitions aligned with docs/DATABASE_DESIGN.md (users.role)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Supported application user roles."""

    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"
