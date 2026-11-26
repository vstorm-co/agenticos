"""Console presentation narrows navigation; it never grants resource access."""

from typing import Literal, get_args

from pydantic import ConfigDict, Field, JsonValue, StrictBool, TypeAdapter, field_validator

from app.core.permissions import OrgRoleName
from app.schemas.base import BaseSchema
from app.schemas.console_catalogs import CatalogPolicy
from app.schemas.console_dashboard import OrganizationDashboardUpdate, StoredOrganizationDashboard

NavigationEntry = Literal[
    "dashboard",
    "chat",
    "inbox",
    "allProjects",
    "agents",
    "workflows",
    "routines",
    "eventSources",
    "datasets",
    "artifacts",
    "knowledgeBases",
    "tables",
    "skills",
    "context",
    "documents",
    "activity",
    "backgroundWork",
    "mcpServers",
    "channels",
    "remoteAgents",
    "vault",
    "sandboxes",
]
NAVIGATION_ENTRIES: tuple[NavigationEntry, ...] = get_args(NavigationEntry)
DEFAULT_NAVIGATION: tuple[NavigationEntry, ...] = tuple(
    entry for entry in NAVIGATION_ENTRIES if entry != "eventSources"
)
SIMPLE_NAVIGATION: tuple[NavigationEntry, ...] = ("chat", "inbox", "allProjects", "documents")
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ConsoleNotices(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    desktop_install_prompt: StrictBool | None = None
    product_notices: StrictBool | None = None

    def changes(self) -> dict[str, JsonValue]:
        return _JSON_OBJECT.validate_python(self.model_dump(mode="json", exclude_unset=True))


class ConsolePreferences(ConsoleNotices):
    mcp_gallery: CatalogPolicy | None = None
    skill_gallery: CatalogPolicy | None = None
    navigation: list[NavigationEntry] | None = Field(
        default=None, max_length=len(NAVIGATION_ENTRIES)
    )

    @field_validator("navigation")
    @classmethod
    def unique_navigation(cls, value: list[NavigationEntry] | None) -> list[NavigationEntry] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Navigation entries must be unique")
        return value


class StoredConsolePreferences(ConsoleNotices):
    mcp_gallery: CatalogPolicy | None = None
    skill_gallery: CatalogPolicy | None = None
    model_config = ConfigDict(extra="ignore")
    navigation: list[str] | None = None


class RoleConsoleUpdate(BaseSchema):
    dashboard: OrganizationDashboardUpdate | None = None
    mcp_gallery: CatalogPolicy | None = None
    skill_gallery: CatalogPolicy | None = None
    model_config = ConfigDict(extra="forbid")
    navigation: list[NavigationEntry] | None = Field(
        default=None, max_length=len(NAVIGATION_ENTRIES)
    )

    @field_validator("navigation")
    @classmethod
    def unique_navigation(cls, value: list[NavigationEntry] | None) -> list[NavigationEntry] | None:
        return ConsolePreferences.unique_navigation(value)

    def changes(self) -> dict[str, JsonValue]:
        return _JSON_OBJECT.validate_python(self.model_dump(mode="json", exclude_unset=True))


class StoredRoleConsole(BaseSchema):
    """Unknown retired destinations are retained for settings, dropped on resolution."""

    dashboard: StoredOrganizationDashboard | None = None

    mcp_gallery: CatalogPolicy | None = None
    skill_gallery: CatalogPolicy | None = None
    navigation: list[str] | None = None


class ConsolePresentationRead(BaseSchema):
    available_mcp_gallery: CatalogPolicy = Field(default_factory=CatalogPolicy)
    available_skill_gallery: CatalogPolicy = Field(default_factory=CatalogPolicy)
    dashboard_default: StoredOrganizationDashboard | None = None
    organization_mcp_gallery: CatalogPolicy = Field(default_factory=CatalogPolicy)
    organization_skill_gallery: CatalogPolicy = Field(default_factory=CatalogPolicy)
    simple_navigation: list[NavigationEntry] = Field(
        default_factory=lambda: list(SIMPLE_NAVIGATION)
    )
    navigation_available: list[NavigationEntry] = Field(
        default_factory=lambda: list(NAVIGATION_ENTRIES)
    )
    organization_navigation: list[NavigationEntry] = Field(
        default_factory=lambda: list(NAVIGATION_ENTRIES)
    )
    navigation_base_default: list[NavigationEntry] = Field(
        default_factory=lambda: list(DEFAULT_NAVIGATION)
    )
    navigation_default: list[NavigationEntry] = Field(
        default_factory=lambda: list(DEFAULT_NAVIGATION)
    )
    navigation: list[NavigationEntry] = Field(default_factory=lambda: list(DEFAULT_NAVIGATION))
    preferences: StoredConsolePreferences = Field(default_factory=StoredConsolePreferences)
    notices_available: ConsoleNotices = Field(default_factory=ConsoleNotices)
    organization_notices: ConsoleNotices = Field(default_factory=ConsoleNotices)
    desktop_install_prompt: bool = True
    product_notices: bool = True


def resolve_console_presentation(
    available: StoredConsolePreferences,
    role: StoredRoleConsole,
    notices: ConsoleNotices,
    personal: StoredConsolePreferences,
) -> ConsolePresentationRead:
    """Organization/deployment ceilings are intersections; empty lists stay empty."""
    ceiling = [
        entry
        for entry in NAVIGATION_ENTRIES
        if available.navigation is None or entry in available.navigation
    ]
    organization = [
        entry for entry in ceiling if role.navigation is None or entry in role.navigation
    ]
    inherited = [
        entry
        for entry in organization
        if role.navigation is not None or entry in DEFAULT_NAVIGATION
    ]
    selected = inherited if personal.navigation is None else personal.navigation
    effective = [entry for entry in organization if entry in selected]
    return ConsolePresentationRead(
        available_mcp_gallery=available.mcp_gallery or CatalogPolicy(),
        available_skill_gallery=available.skill_gallery or CatalogPolicy(),
        dashboard_default=role.dashboard,
        organization_mcp_gallery=role.mcp_gallery or CatalogPolicy(),
        organization_skill_gallery=role.skill_gallery or CatalogPolicy(),
        navigation_available=ceiling,
        organization_navigation=organization,
        navigation_base_default=[entry for entry in ceiling if entry in DEFAULT_NAVIGATION],
        navigation_default=inherited,
        navigation=effective,
        preferences=personal,
        notices_available=ConsoleNotices(
            desktop_install_prompt=available.desktop_install_prompt,
            product_notices=available.product_notices,
        ),
        organization_notices=notices,
        desktop_install_prompt=available.desktop_install_prompt is not False
        and notices.desktop_install_prompt is not False
        and personal.desktop_install_prompt is not False,
        product_notices=available.product_notices is not False
        and notices.product_notices is not False
        and personal.product_notices is not False,
    )


RoleConsoleChanges = dict[OrgRoleName, RoleConsoleUpdate | None]


_ROLE_DEFAULTS = TypeAdapter(dict[str, StoredRoleConsole])


def stored_role_defaults(value: dict[str, JsonValue] | None) -> dict[str, StoredRoleConsole]:
    return _ROLE_DEFAULTS.validate_python({} if value is None else value)
