"""Reusable webhook configuration; credentials are write-only."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

JsonObject = dict[str, JsonValue]
Provider = Literal["github", "linear", "hubspot", "zendesk", "webhook"]

SIGNATURE_HEADER = {
    "github": "x-hub-signature-256",
    "hubspot": "x-hubspot-signature-v3",
    "linear": "linear-signature",
    "webhook": "x-signature-256",
    "zendesk": "x-zendesk-webhook-signature",
}
HUBSPOT_V1_SIGNATURE_HEADER = "x-hubspot-signature"


class SourceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["provider", "hmac", "basic", "api_key", "standard_webhooks"] = "hmac"
    header_name: str = Field(
        default="x-signature-256", pattern=r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$"
    )
    signature_prefix: str = Field(default="sha256=", max_length=128)
    encoding: Literal["hex", "base64", "base64url"] = "hex"
    legacy: bool = False

    def reserves_header(self, provider: str, header: str) -> bool:
        """Whether using this header as an event ID could expose authentication material."""
        forbidden = {"authorization", self.header_name, "webhook-signature"}
        if self.method == "provider":
            forbidden.add(SIGNATURE_HEADER[provider])
            if provider == "hubspot":
                forbidden.add(HUBSPOT_V1_SIGNATURE_HEADER)
        return header.lower() in forbidden

    @field_validator("header_name")
    @classmethod
    def lower_header(cls, value: str) -> str:
        return value.lower()

    @field_validator("signature_prefix")
    @classmethod
    def printable_prefix(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError("A header prefix must contain printable ASCII")
        return value


class SourceCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None


class EventSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    provider: Provider = "webhook"
    auth: SourceAuth = Field(default_factory=SourceAuth)
    delivery_id_header: str | None = Field(
        default=None, pattern=r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$"
    )
    visibility: Literal["private", "org"] = "private"
    is_active: bool = True
    credentials: SourceCredentials = Field(default_factory=SourceCredentials)

    @field_validator("delivery_id_header")
    @classmethod
    def valid_delivery_id_header(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        auth = info.data.get("auth")
        provider = info.data.get("provider")
        if (
            isinstance(auth, SourceAuth)
            and provider is not None
            and auth.reserves_header(provider, value)
        ):
            raise ValueError("Delivery IDs must not use a credential or signature header")
        return value.lower()

    @model_validator(mode="after")
    def provider_auth(self) -> Self:
        if (self.provider == "webhook") == (self.auth.method == "provider"):
            raise ValueError(
                "Choose provider verification for a preset, or custom authentication for Custom webhook"
            )
        return self


class EventSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    visibility: Literal["private", "org"] | None = None
    is_active: bool | None = None
    auth: SourceAuth | None = None
    delivery_id_header: str | None = Field(
        default=None, pattern=r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$"
    )
    credentials: SourceCredentials | None = None


class EventSourceRead(BaseModel):
    id: UUID
    name: str
    provider: Provider
    auth: SourceAuth
    delivery_id_header: str | None
    visibility: Literal["private", "org"]
    owner_user_id: UUID | None
    is_active: bool
    webhook_url: str
    can_use: bool
    can_edit: bool


class EventSourceCreated(EventSourceRead):
    reveal_secret: str | None = None


class EventSourceList(BaseModel):
    items: list[EventSourceRead]
    total: int


class SourceUsage(BaseModel):
    id: UUID
    kind: Literal["routine", "workflow"]
    target_id: UUID | None
    name: str
    is_active: bool | None


class SourceUsageList(BaseModel):
    items: list[SourceUsage]
    total: int


class EventSourceTarget(BaseModel):
    """The routine's agent or workflow whose editor is requesting a sample."""

    kind: Literal["agent", "workflow"]
    id: UUID


class SourceListening(BaseModel):
    listener_id: str
    expires_at: datetime


class SourceSample(BaseModel):
    body: JsonObject
    delivery_id: str


class SourceCapture(BaseModel):
    state: Literal["listening", "caught", "expired", "too_large"]
    delivery: SourceSample | None = None
