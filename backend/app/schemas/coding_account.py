"""Only the owner sees coding-account metadata; credentials never leave the vault."""

from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.schemas.base import BaseSchema

CodingHarness = Literal["claude_code", "codex"]


class CodingAccountCreate(BaseSchema):
    harness: CodingHarness
    label: str = Field(min_length=1, max_length=120)
    api_key: SecretStr = Field(min_length=8, max_length=8192)
    enabled: bool = False

    @field_validator("api_key")
    @classmethod
    def complete_key(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() != value.get_secret_value().strip():
            raise ValueError("Remove whitespace around the credential")
        return value


class CodingAccountRead(BaseSchema):
    id: UUID
    harness: CodingHarness
    label: str
    secret_kind: Literal["api_key", "openai_codex"]
    enabled: bool
    generation: UUID


class CodingAccountList(BaseSchema):
    items: list[CodingAccountRead]


class CodingAccountUpdate(BaseSchema):
    generation: UUID
    enabled: bool


class CodingAccountOAuthComplete(BaseSchema):
    label: str = Field(min_length=1, max_length=120)
    callback_url: SecretStr = Field(min_length=1, max_length=8192)
    enabled: bool = False


class CodingAccountOAuthStart(BaseSchema):
    authorization_url: str
