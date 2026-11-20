"""A native sign-in's public state; no schema can return its credentials."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.schemas.base import BaseSchema


class ClaudeSubscriptionRead(BaseSchema):
    available: bool
    connected: bool = False
    state: Literal[
        "disconnected", "starting", "awaiting_code", "verifying", "connected", "error"
    ] = "disconnected"
    login_id: UUID | None = None
    authorization_url: str | None = Field(default=None, max_length=8192, repr=False)
    expires_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^CLAUDE_[A-Z_]+$")

    @field_validator("authorization_url")
    @classmethod
    def provider_authorization_page(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or (url.hostname, url.path)
            not in {
                ("claude.ai", "/oauth/authorize"),
                ("claude.ai", "/oauth/authorize/"),
                ("claude.com", "/cai/oauth/authorize"),
                ("claude.com", "/cai/oauth/authorize/"),
            }
            or url.port not in {None, 443}
            or url.username is not None
            or url.password is not None
            or url.fragment
        ):
            raise ValueError("The native runtime returned an invalid authorization page")
        return value


class ClaudeSubscriptionLoginControl(BaseSchema):
    login_id: UUID


class ClaudeSubscriptionLoginCode(ClaudeSubscriptionLoginControl):
    code: SecretStr = Field(min_length=1, max_length=2048, repr=False)

    @field_validator("code")
    @classmethod
    def single_line_code(cls, value: SecretStr) -> SecretStr:
        if any(not 33 <= ord(character) <= 126 for character in value.get_secret_value()):
            raise ValueError("Paste the code without spaces or line breaks")
        return value
