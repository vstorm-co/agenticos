"""Every row this deployment holds *about one person*, for export and for erasure.

GDPR art. 15 asks what you hold about somebody and art. 17 asks you to remove it,
and both questions are answered from one place on purpose: an inventory that
lists a table for the export and forgets it for the deletion is worse than no
inventory, because it reads as complete (#1421).

What belongs here is the rows whose *subject* is the person. A row they merely
created - an agent, a knowledge base, a secret - belongs to the organization and
is handled by `UserService._release_owned_rows`, which hands it on rather than
removing it: deleting a colleague's account must not delete the agent the team
runs on. `docs/security.md` has the table, with the reason for each.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.memory import AgentMemoryFile
from app.db.models.message_rating import MessageRating
from app.db.models.session import Session
from app.db.models.user_slash_command import UserSlashCommand


async def conversations_of(db: AsyncSession, user_id: UUID) -> list[Conversation]:
    """The threads this person started, newest first."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def messages_in(db: AsyncSession, conversation_ids: list[UUID]) -> list[Message]:
    """Every turn of those threads, in the order they happened.

    Not filtered by author: a thread's answers are part of what the person is
    asking to see, and a transcript with every second turn removed answers
    nothing. A thread they did *not* start is not here at all.
    """
    if not conversation_ids:
        return []
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .order_by(Message.conversation_id, Message.ordinal)
    )
    return list(result.scalars().all())


async def ratings_of(db: AsyncSession, user_id: UUID) -> list[MessageRating]:
    """What they marked as good or bad, which is an opinion they expressed."""
    result = await db.execute(
        select(MessageRating)
        .where(MessageRating.user_id == user_id)
        .order_by(MessageRating.created_at.desc())
    )
    return list(result.scalars().all())


async def sessions_of(db: AsyncSession, user_id: UUID) -> list[Session]:
    """Where and when they signed in. Never the credential - the row holds a hash."""
    result = await db.execute(
        select(Session).where(Session.user_id == user_id).order_by(Session.created_at.desc())
    )
    return list(result.scalars().all())


async def runs_started_by(db: AsyncSession, user_id: UUID) -> list[AgentRun]:
    """Runs they started, for what each cost and which agent answered."""
    result = await db.execute(
        select(AgentRun).where(AgentRun.user_id == user_id).order_by(AgentRun.created_at.desc())
    )
    return list(result.scalars().all())


async def memory_about(db: AsyncSession, owner_key: str) -> list[AgentMemoryFile]:
    """What every agent in every organization has written down about them."""
    result = await db.execute(
        select(AgentMemoryFile)
        .where(AgentMemoryFile.owner_key == owner_key)
        .order_by(AgentMemoryFile.updated_at.desc())
    )
    return list(result.scalars().all())


async def identities_of(db: AsyncSession, user_id: UUID) -> list[ChannelIdentity]:
    """Their Slack, Telegram and Mattermost accounts, as this deployment knows them."""
    result = await db.execute(select(ChannelIdentity).where(ChannelIdentity.user_id == user_id))
    return list(result.scalars().all())


async def slash_commands_of(db: AsyncSession, user_id: UUID) -> list[UserSlashCommand]:
    result = await db.execute(select(UserSlashCommand).where(UserSlashCommand.user_id == user_id))
    return list(result.scalars().all())


async def dashboard_layouts_of(db: AsyncSession, user_id: UUID) -> list[DashboardLayout]:
    result = await db.execute(select(DashboardLayout).where(DashboardLayout.user_id == user_id))
    return list(result.scalars().all())


async def purge_memory_about(db: AsyncSession, owner_key: str) -> int:
    """Delete what every agent remembers about them, in every organization.

    **Not reached by any cascade, and that is the gap this closes.**
    `agent_memory_files.owner_key` is a string - `person:<user_id>` - with no
    foreign key to `users`, so deleting the row the key names left every note
    behind: personal data about somebody who has asked to be forgotten, keyed
    by an id that no longer resolves to anybody.

    Organization-wide rather than per organization, because the account is
    going: `MemoryService.forget_person` is the scoped version, for a person who
    is still a member somewhere else.

    Returns:
        How many notes were removed, for the audit entry.
    """
    result = await db.execute(
        sa_delete(AgentMemoryFile).where(AgentMemoryFile.owner_key == owner_key)
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def purge_identities_of(db: AsyncSession, user_id: UUID) -> int:
    """Delete their platform identities rather than unlinking them.

    The foreign key is `SET NULL`, which leaves the row: a Slack user id, a
    username and a display name, about a person whose account is gone, linked to
    nobody and reachable by nothing. That is personal data retained for no
    purpose, which is the one thing art. 17 is unambiguous about.

    Returns:
        How many identities were removed, for the audit entry.
    """
    result = await db.execute(sa_delete(ChannelIdentity).where(ChannelIdentity.user_id == user_id))
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def attachment_paths_in(db: AsyncSession, conversation_id: UUID) -> list[str]:
    """Where the files attached to one thread's turns are stored.

    Read *before* the conversation goes, because the rows cascade away with it
    and the bytes do not: `chat_files.message_id` is `ON DELETE CASCADE` from
    `messages`, which cascades from `conversations`, so deleting a thread removed
    every row that named a file and left the file itself on disk - personal data
    kept after somebody asked for it to be deleted, and reachable by nothing
    (#1421, FA-015).
    """
    result = await db.execute(
        select(ChatFile.storage_path)
        .join(Message, ChatFile.message_id == Message.id)
        .where(Message.conversation_id == conversation_id, ChatFile.storage_path.is_not(None))
    )
    return [path for path in result.scalars().all() if path]


def as_rows(items: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """The named fields of each row, as JSON-ready values.

    Named rather than "everything on the model", because an export is a document
    handed to a person and a model carries columns that are neither theirs nor
    meaningful to them - a hashed credential, an internal flag, a foreign key to
    a row they cannot see. Adding a column to a table must not silently add it to
    what every person can download.
    """
    return [{field: getattr(item, field, None) for field in fields} for item in items]
