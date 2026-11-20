"""Agent messages: the shapes the console and the capability tool both speak.

A thread is addressed by its two agents; a message names the agent that sent
it and, where the console sent it, the person who sent it as that agent. The
recipient on a send is a slug or an id - the console offers a picker of slugs,
and an agent names the colleague it knows by slug - resolved server-side so a
typo is a refusal naming the slug, not a row in the wrong thread.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema

MAX_BODY_CHARS = 16_000
"""The longest message the console sends. The capability's own ceiling is its
config, bounded by the same number; the service holds a higher hard ceiling
behind both so a client that skips validation cannot store a novel."""

MAX_ATTACHMENTS = 10
"""Files on one message. A message is a note with evidence, not a folder."""

MAX_EMOJI_CHARS = 16
"""An emoji, with room for a compound one (a flag, a skin tone, a ZWJ pair)."""


class AgentRef(BaseSchema):
    """One agent, as a thread names it."""

    id: UUID
    slug: str
    name: str


class AgentMessageSend(BaseSchema):
    """Send a message as one agent to another.

    `recipient` is the other agent's slug or id. `sender_agent_id` is the
    agent the message is sent as - the console names it, the capability tool
    fills it from the agent that is running.
    """

    sender_agent_id: UUID = Field(description="The agent sending this message")
    recipient: str = Field(
        min_length=1,
        max_length=64,
        description="The other agent's slug, or its id",
    )
    body: str = Field(
        min_length=1,
        max_length=MAX_BODY_CHARS,
        description="What the agent says to the other agent",
    )
    reply_to_message_id: UUID | None = Field(
        default=None, description="The message in their thread this answers, if any"
    )
    attachment_file_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_ATTACHMENTS,
        description="Files already uploaded, by their upload ids",
    )


class AgentMessageReactionCreate(BaseSchema):
    """React to a message, or take the reaction back by sending it again."""

    emoji: str = Field(
        min_length=1,
        max_length=MAX_EMOJI_CHARS,
        description="One emoji, such as 👍",
    )
    as_agent_id: UUID | None = Field(
        default=None,
        description="React as this agent in the thread; omitted reacts as the reader",
    )


class AgentMessageReactionRead(BaseSchema):
    """One emoji on a message, and who put it there."""

    emoji: str
    reactor_agent_id: UUID | None = None
    reactor_agent_slug: str | None = None
    reactor_user_id: UUID | None = None
    created_at: datetime


class AgentMessageAttachmentRead(BaseSchema):
    """A file a message carries, by its upload."""

    chat_file_id: UUID
    filename: str
    mime_type: str
    size: int
    file_type: str


class AgentMessageRead(BaseSchema, TimestampSchema):
    """One message, with its reactions and its files."""

    id: UUID
    thread_id: UUID
    sender_agent_id: UUID
    sender_agent_slug: str
    sender_user_id: UUID | None = None
    body: str
    reply_to_message_id: UUID | None = None
    reactions: list[AgentMessageReactionRead] = Field(default_factory=list)
    attachments: list[AgentMessageAttachmentRead] = Field(default_factory=list)


class AgentMessageReactionsRead(BaseSchema):
    """What a react toggle returns: whether it stuck, and the message's reactions now."""

    reacted: bool = Field(description="True when the reaction was added, false when taken back")
    reactions: list[AgentMessageReactionRead] = Field(default_factory=list)


class AgentMessagePreview(BaseSchema):
    """The last message in a thread, as the listing shows it."""

    sender_agent_slug: str
    body: str = Field(description="The first 200 characters of the message")
    created_at: datetime


class AgentMessageThreadRead(BaseSchema, TimestampSchema):
    """One thread: its two agents, its last message, and whether it waits on the reader."""

    id: UUID
    agent_a: AgentRef
    agent_b: AgentRef
    last_message_at: datetime | None = None
    last_message: AgentMessagePreview | None = None
    unread: bool = False


class AgentMessageThreadList(BaseSchema):
    """A page of threads, most recently active first."""

    items: list[AgentMessageThreadRead]
    total: int


class AgentMessageList(BaseSchema):
    """A page of one thread's messages, oldest first."""

    items: list[AgentMessageRead]
    total: int


class AgentMessageRecipientList(BaseSchema):
    """The agents this caller may message, most recently created first."""

    items: list[AgentRef]
    total: int
