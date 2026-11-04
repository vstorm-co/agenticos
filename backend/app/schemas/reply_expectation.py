"""A body-free, source-bound expectation carried by one durable workflow step."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

ThreadId = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=r"^[^\x00-\x1f\x7f]+$")
]
ReplyAnchor = Annotated[str, StringConstraints(max_length=998, pattern=r"^<[^<>\s]+>$")]


class ReplyExpectationInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    thread_id: ThreadId
    expected_sender: EmailStr
    not_before: AwareDatetime
    deadline: AwareDatetime
    anchor_message_id: ReplyAnchor | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.deadline <= self.not_before:
            raise ValueError("The reply deadline must follow the start of the expectation")
        return self


class ReplyDraftSelection(BaseModel):
    """Explicit model and per-draft budget; the draft has no sending tools."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model_profile_id: UUID
    max_cost_usd: float = Field(default=0.10, gt=0, le=5)


class ReplyMailboxSelection(BaseModel):
    """The existing organization mailbox a reply workflow may read."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: Literal["google", "outlook"]
    connection_id: UUID
    mailbox: EmailStr | None = None


class ReplyExpectation(ReplyExpectationInput):
    kind: Literal["mail_reply"] = "mail_reply"
    provider: Literal["google", "outlook"]
    connection_id: UUID
    authorization_generation: UUID
    mailbox: EmailStr | None = None
    paused: bool = False


class ReplyExpectationEdit(ReplyExpectationInput):
    """Replace the match criteria while the step is parked; its mailbox stays fixed."""

    paused: bool = False
    review_mailbox: bool = False


class ReplyExpectationOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: Literal["reply", "deadline"]
    checked_at: AwareDatetime
    deadline: AwareDatetime
    message_id: str | None = None
    received_at: AwareDatetime | None = None
    ignored_unverified: int = Field(default=0, ge=0, le=500)
