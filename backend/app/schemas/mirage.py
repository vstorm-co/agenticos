"""What the Builder's terminal form reads about each backend it can mount (#2191)."""

from typing import Any, Literal

from app.agents.capabilities.mirage import BackendInfo
from app.schemas.base import BaseSchema


class MirageBackendRead(BaseSchema):
    """One backend: whether it can be mounted here, and the form for it."""

    name: str
    title: str
    group: Literal["files", "mail", "chat", "work", "data", "servers", "scratch"]
    credential: Literal["fields", "google", "microsoft", "none"]
    available: bool
    reason: str | None
    options_schema: dict[str, Any]
    """JSON Schema of the options an author fills; secrets and endpoint overrides left out."""
    secret_fields: list[str]
    required_secrets: list[str]
    address_fields: list[str]
    """Options naming a host, which must be on the operator's allowlist."""

    @classmethod
    def from_info(cls, info: BackendInfo) -> MirageBackendRead:
        return cls(
            name=info.name,
            title=info.title,
            group=info.group,
            credential=info.credential,
            available=info.available,
            reason=info.reason,
            options_schema=info.options_schema,
            secret_fields=list(info.secret_fields),
            required_secrets=list(info.required_secrets),
            address_fields=list(info.address_fields),
        )


class MirageBackendList(BaseSchema):
    items: list[MirageBackendRead]
    installed: bool
    """Whether this deployment has the terminal at all (the `mirage` extra)."""
