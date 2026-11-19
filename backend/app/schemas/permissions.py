"""Schemas for the permission catalog and a member's effective permissions."""

from uuid import UUID

from app.schemas.base import BaseSchema


class PlatformContextRead(BaseSchema):
    """Connection metadata only; no bearer, session cookie or credential value."""

    server_version: str
    mcp_contract_version: int
    organization_id: UUID
    user_id: UUID | None
    authentication: str
    granted_scopes: list[str] | None
    features: list[str]


class PermissionEntry(BaseSchema):
    """One permission the caller holds, and how far it reaches."""

    permission: str
    scope: str


class MyPermissions(BaseSchema):
    """What the caller may do in one organization.

    The frontend uses this to hide actions that would be refused anyway. It is
    a convenience, never the enforcement point - every endpoint re-checks.
    """

    organization_id: str
    user_id: str
    role: str
    is_app_admin: bool
    permissions: list[PermissionEntry]


class RoleDefinition(BaseSchema):
    """A built-in role and the permissions it bundles."""

    name: str
    permissions: list[PermissionEntry]


class RoleCatalog(BaseSchema):
    """Every permission the platform defines, and how roles compose them.

    Drives the Users & Roles matrix. Roles can only ever recombine
    `all_permissions`; clients cannot invent new ones.
    """

    all_permissions: list[str]
    resource_permissions: list[str]
    roles: list[RoleDefinition]
