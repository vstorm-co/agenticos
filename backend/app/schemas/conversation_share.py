"""Conversation sharing schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import BaseSchema
from app.schemas.conversation import ConversationAgent
from app.schemas.user import AdminUserList, AdminUserRead  # re-exported for backward compatibility

__all__ = [
    "AdminConversationList",
    "AdminConversationRead",
    "AdminUserList",
    "AdminUserRead",
    "ConversationShareCreate",
    "ConversationShareList",
    "ConversationShareRead",
    "SharedConversationRead",
]


class SharedVisual(BaseSchema):
    """A drawing in a shared thread, as a finished document - never the call that made it."""

    id: str
    title: str
    kind: Literal["svg", "html", "mermaid"]
    content: str = Field(description="The drawing, revisions applied and pictures inlined")


class SharedDraftField(BaseSchema):
    """One part of a shared draft, with the indentation and line breaks it was written with."""

    # BaseSchema strips whitespace; a field's text is shown and copied as typed.
    model_config = ConfigDict(str_strip_whitespace=False)

    name: str | None = None
    text: str
    format: str


class SharedDraftVersion(BaseSchema):
    """One take on a shared draft; its label is the tab when there are several."""

    label: str | None = None
    fields: list[SharedDraftField]


class SharedDraft(BaseSchema):
    """A draft in a shared thread, rebuilt from the call that wrote it - never the call."""

    id: str
    title: str
    kind: str
    versions: list[SharedDraftVersion]


class ConversationShareCreate(BaseSchema):
    """Schema for creating a conversation share."""

    shared_with: UUID | None = Field(
        default=None, description="User ID to share with (omit for link sharing)"
    )
    # What the share dialog actually collects. People know each other by email,
    # not by UUID; the server resolves it, so the client never has to hold a
    # user id it has no other reason to know.
    shared_with_email: EmailStr | None = Field(
        default=None, description="Email of the user to share with, resolved server-side"
    )
    permission: Literal["view", "edit"] = Field(default="view", description="Access level")
    generate_link: bool = Field(default=False, description="Generate a public share link")


class ConversationShareUpdate(BaseSchema):
    """Change what a share with a person lets them do."""

    permission: Literal["view", "edit"] = Field(description="Access level")


class ConversationShareRead(BaseSchema):
    """Schema for reading a conversation share."""

    id: UUID
    conversation_id: UUID
    shared_by: UUID
    shared_with: UUID | None = None
    share_token: str | None = None
    permission: Literal["view", "edit"] = "view"
    shared_with_email: str | None = Field(default=None, description="Email of the user shared with")
    shared_by_email: str | None = Field(default=None, description="Email of the user who shared")
    created_at: datetime


class ConversationShareList(BaseSchema):
    """Paginated list of conversation shares."""

    items: list[ConversationShareRead]
    total: int


class AdminConversationRead(BaseSchema):
    """Admin view of a conversation - includes owner email."""

    id: UUID
    user_id: UUID | None = None
    title: str | None = None
    is_archived: bool = False
    message_count: int = 0
    user_email: str | None = None
    agents: list[ConversationAgent] = Field(
        default_factory=list,
        description="Every agent that answered here, in the order they first did",
    )
    coding_agents: list[Literal["claude_code", "codex"]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


class AdminConversationList(BaseSchema):
    """Paginated list of conversations for admin."""

    items: list[AdminConversationRead]
    total: int


class SharedMessageRead(BaseSchema):
    """One message of a conversation opened by its share link."""

    id: UUID
    role: str
    content: str | None = None
    created_at: datetime | None = None
    visuals: list[SharedVisual] = Field(default_factory=list)
    drafts: list[SharedDraft] = Field(default_factory=list)


class SharedConversationBody(BaseSchema):
    id: UUID
    title: str | None = None
    messages: list[SharedMessageRead]


class SharedConversationShare(BaseSchema):
    """The link itself, without its token: whoever opened it already holds that."""

    id: UUID
    permission: Literal["view", "edit"]


class SharedConversationRead(BaseSchema):
    """A conversation opened by its share link, with no account."""

    show_agenticos_attribution: bool = True
    conversation: SharedConversationBody
    share: SharedConversationShare
