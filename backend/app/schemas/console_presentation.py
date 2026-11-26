"""Console presentation narrows navigation; it never grants resource access."""

from typing import Literal, get_args

from pydantic import ConfigDict, Field, JsonValue, StrictBool, TypeAdapter, field_validator

from app.core.permissions import OrgRoleName
from app.schemas.base import BaseSchema

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
SIMPLE_NAVIGATION: tuple[NavigationEntry, ...] = ("chat", "inbox", "allProjects", "documents")
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ConsoleNotices(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    desktop_install_prompt: StrictBool | None = None
    product_notices: StrictBool | None = None

    def changes(self) -> dict[str, JsonValue]:
        return _JSON_OBJECT.validate_python(self.model_dump(mode="json", exclude_unset=True))


class ConsolePreferences(ConsoleNotices):
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
    model_config = ConfigDict(extra="ignore")
    navigation: list[str] | None = None


class RoleConsoleUpdate(BaseSchema):
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

    navigation: list[str] | None = None


class ConsolePresentationRead(BaseSchema):
    simple_navigation: list[NavigationEntry] = Field(
        default_factory=lambda: list(SIMPLE_NAVIGATION)
    )
    navigation_available: list[NavigationEntry] = Field(
        default_factory=lambda: list(NAVIGATION_ENTRIES)
    )
    organization_navigation: list[NavigationEntry] = Field(
        default_factory=lambda: list(NAVIGATION_ENTRIES)
    )
    navigation: list[NavigationEntry] = Field(default_factory=lambda: list(NAVIGATION_ENTRIES))
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
    effective = [
        entry
        for entry in organization
        if personal.navigation is None or entry in personal.navigation
    ]
    return ConsolePresentationRead(
        navigation_available=ceiling,
        organization_navigation=organization,
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
