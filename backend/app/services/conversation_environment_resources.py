"""Private vault payloads for owned environments, never response models."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter
from pydantic_ai.workspaces import WorkspaceRef

from app.agents.capabilities.browser_use._page import BrowserTarget
from app.agents.capabilities.browser_use._route import BrowserRoute


class StoredBrowserRoute(BaseModel):
    """Resolved credentials live only inside the environment's sealed envelope."""

    model_config = ConfigDict(extra="forbid")

    proxy_server: str | None = Field(default=None, repr=False)
    proxy_username: str | None = Field(default=None, repr=False)
    proxy_password: str | None = Field(default=None, repr=False)
    remote_url: str | None = Field(default=None, repr=False)
    remote_address: str | None = Field(default=None, repr=False)
    timezone: str | None = None
    locale: str | None = None

    @classmethod
    def capture(cls, route: BrowserRoute | None) -> StoredBrowserRoute | None:
        if route is None:
            return None
        return cls(
            proxy_server=route.proxy_server,
            proxy_username=route.proxy_username,
            proxy_password=route.proxy_password.get_secret_value()
            if route.proxy_password
            else None,
            remote_url=route.remote_url.get_secret_value() if route.remote_url else None,
            remote_address=route.remote_address,
            timezone=route.timezone,
            locale=route.locale,
        )

    def restore(self) -> BrowserRoute:
        return BrowserRoute(
            proxy_server=self.proxy_server,
            proxy_username=self.proxy_username,
            proxy_password=SecretStr(self.proxy_password)
            if self.proxy_password is not None
            else None,
            remote_url=SecretStr(self.remote_url) if self.remote_url is not None else None,
            remote_address=self.remote_address,
            timezone=self.timezone,
            locale=self.locale,
        )


class BrowserEnvironmentResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["browser"] = "browser"
    environment_id: UUID
    organization_id: UUID
    cdp_url: str = Field(repr=False)
    route: StoredBrowserRoute | None = Field(default=None, repr=False)
    tabs: dict[str, BrowserTarget] = Field(default_factory=dict, max_length=8)
    active: str = "main"


class DesktopEnvironmentResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["desktop"] = "desktop"
    environment_id: UUID
    organization_id: UUID
    backend: Literal["sandbox", "daemon", "e2b"]
    workspace_id: UUID | None = None
    workspace_ref: WorkspaceRef | None = None
    connection_id: UUID | None = None
    connection_fingerprint: str | None = None
    workspace_root: str | None = None
    project_lease_id: UUID | None = Field(default=None, exclude_if=lambda lease: lease is None)
    credential: str = Field(default="", repr=False)
    daemon_url: str = Field(default="", repr=False)
    width: int = Field(ge=640, le=1920)
    height: int = Field(ge=480, le=1200)


type EnvironmentResource = Annotated[
    BrowserEnvironmentResource | DesktopEnvironmentResource, Field(discriminator="kind")
]
ENVIRONMENT_RESOURCE = TypeAdapter(EnvironmentResource)
