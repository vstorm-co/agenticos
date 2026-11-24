"""Schemas for the permission catalog and a member's effective permissions."""

from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.core.permissions import OrgRoleName
from app.schemas.base import BaseSchema

NAVIGATION_ITEM_IDS = (
    "chat",
    "inbox",
    "agentMessages",
    "allApps",
    "agents",
    "workflows",
    "routines",
    "datasets",
    "allProjects",
    "knowledgeBases",
    "tables",
    "skills",
    "context",
    "documents",
    "activity",
    "failureLearning",
    "backgroundWork",
    "connectors",
    "groups",
)
"""Sidebar entry identifiers. Dashboard and Organizations remain available for recovery."""


class PlatformContextRead(BaseSchema):
    """Connection metadata only; no bearer, session cookie or credential value."""

    server_version: str
    mcp_contract_version: int
    organization_id: UUID
    user_id: UUID | None
    authentication: str
    granted_scopes: list[str] | None
    features: list[str]
    deployment_admin: bool = False


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
    hidden_navigation_items: list[str] = Field(default_factory=list)


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


class RoleNavigationRead(BaseSchema):
    """Sidebar preferences for this organization, separate from authorization.

    The UI intersects these preferences with the permission catalog. Showing an
    entry never grants its permission; hiding it never revokes a resource grant.
    """

    hidden_items: dict[OrgRoleName, list[str]]
    configurable_items: list[str]
    editable_roles: list[OrgRoleName]


class RoleNavigationUpdate(BaseSchema):
    """Replace one role's hidden entries; an empty list restores its default sidebar."""

    model_config = ConfigDict(extra="forbid")

    hidden_items: list[str] = Field(max_length=len(NAVIGATION_ITEM_IDS))

    @field_validator("hidden_items")
    @classmethod
    def known_unique_items(cls, items: list[str]) -> list[str]:
        if any(item not in NAVIGATION_ITEM_IDS for item in items):
            raise ValueError("Choose only configurable sidebar entries")
        if len(set(items)) != len(items):
            raise ValueError("Each sidebar entry must appear only once")
        return [item for item in NAVIGATION_ITEM_IDS if item in items]
