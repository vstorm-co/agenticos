"""Only connection metadata leaves the personal model vault."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.core.secret_kinds import MIN_CREDENTIAL_LENGTH
from app.schemas.base import BaseSchema


class PersonalModelDestination(BaseSchema):
    """The model destination displayed when the person supplied their key."""

    profile_id: UUID
    provider: str = Field(min_length=1, max_length=32)
    endpoint: str | None = Field(max_length=512)
    model: str = Field(min_length=1, max_length=255)


class PersonalModelKeyCreate(BaseSchema):
    expected_destination: PersonalModelDestination
    api_key: SecretStr = Field(min_length=MIN_CREDENTIAL_LENGTH, max_length=8192)


class PersonalModelKeyRead(BaseSchema):
    id: UUID
    provider: str
    endpoint: str


class PersonalModelKeyList(BaseSchema):
    items: list[PersonalModelKeyRead]


class AgentModelConnectionRead(BaseSchema):
    personal: bool
    connected: bool
    profile_id: UUID | None = None
    provider: str | None = None
    endpoint: str | None = None
    model: str | None = None


class CopilotSignInStart(BaseSchema):
    expected_destination: PersonalModelDestination


class CopilotSignInChallenge(BaseSchema):
    handle: str
    user_code: str
    verification_uri: Literal["https://github.com/login/device"]
    expires_at: datetime
    poll_after_seconds: int


class CopilotSignInPoll(BaseSchema):
    handle: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class CopilotSignInResult(BaseSchema):
    status: Literal["pending", "connected"]
    poll_after_seconds: int = 0


class PersonalModelGenerationRead(BaseSchema):
    organization_id: UUID
    provider: str
    endpoint: str
    created_at: datetime
    updated_at: datetime | None
