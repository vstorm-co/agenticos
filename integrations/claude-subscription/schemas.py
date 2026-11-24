"""Bounded internal protocol between the API and the native Claude runtime."""

import json
from base64 import b64decode
from binascii import Error as Base64Error
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    field_validator,
)

ModelAlias = Literal["sonnet", "opus", "haiku"]
LoginState = Literal[
    "disconnected", "starting", "awaiting_code", "verifying", "connected", "error"
]


class OwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: UUID
    user_id: UUID


class LoginRequest(OwnerRequest):
    login_id: UUID


class CodeRequest(LoginRequest):
    code: str = Field(min_length=1, max_length=2048, repr=False)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str) -> str:
        value = value.strip()
        if not value or any(
            ord(character) < 33 or ord(character) > 126 for character in value
        ):
            raise ValueError("Invalid authorization code")
        return value


class ConnectionStatus(BaseModel):
    available: bool = True
    connected: bool = False
    state: LoginState = "disconnected"
    login_id: UUID | None = None
    authorization_url: str | None = Field(default=None, repr=False)
    expires_at: str | None = None
    error_code: str | None = None


class ImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str = Field(min_length=1, max_length=1024 * 1024, repr=False)

    @field_validator("data")
    @classmethod
    def image_bytes(cls, value: str) -> str:
        try:
            b64decode(value, validate=True)
        except (ValueError, Base64Error):
            raise ValueError("Invalid image bytes") from None
        return value


class InferRequest(OwnerRequest):
    model: ModelAlias
    prompt: str = Field(min_length=1, max_length=800000, repr=False)
    output_schema: dict[str, JsonValue] = Field(repr=False)
    max_output_tokens: int = Field(default=8192, ge=256, le=32000, strict=True)
    images: list[ImageInput] = Field(default_factory=list, repr=False)
    thinking: (
        StrictBool | Literal["minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None

    @field_validator("prompt")
    @classmethod
    def prompt_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 800000:
            raise ValueError("Prompt too large")
        return value

    @field_validator("output_schema")
    @classmethod
    def schema_bytes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if (
            value.get("type") != "object"
            or len(json.dumps(value).encode("utf-8")) > 131072
        ):
            raise ValueError("Invalid output schema")
        return value


class Usage(BaseModel):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    cache_read_input_tokens: int = Field(default=0, ge=0, strict=True)
    cache_creation_input_tokens: int = Field(default=0, ge=0, strict=True)


class InferResult(BaseModel):
    structured_output: dict[str, JsonValue]
    usage: Usage
    model: str
