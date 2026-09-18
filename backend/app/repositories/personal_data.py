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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.memory import AgentMemoryFile
from app.db.models.message_rating import MessageRating
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization, OrganizationMember
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


async def tool_calls_in(db: AsyncSession, message_ids: list[UUID]) -> list[ToolCall]:
    """What the agent did on their behalf, with the arguments and the answer.

    A tool call holds what was sent out to answer them and what came back - an
    address looked up, a document retrieved, a row read - which is theirs as
    much as the turn that caused it. The transcript without it says an agent did
    something and not what.
    """
    if not message_ids:
        return []
    result = await db.execute(
        select(ToolCall)
        .where(ToolCall.message_id.in_(message_ids))
        .order_by(ToolCall.message_id, ToolCall.started_at)
    )
    return list(result.scalars().all())


async def memberships_of(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Which organizations they belong to, and as what.

    A row referencing the person directly, and one they cannot see anywhere else
    in an export: `admin_detail` already shows it to an administrator, so
    leaving it out made "everything about you" untrue in the one place a reader
    could check.
    """
    result = await db.execute(
        select(
            OrganizationMember.id,
            Organization.name,
            OrganizationMember.role,
            OrganizationMember.joined_at,
        )
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.name)
    )
    return [
        {"id": str(row_id), "organization": name, "role": role, "joined_at": joined_at}
        for row_id, name, role, joined_at in result.all()
    ]


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


async def notifications_of(db: AsyncSession, user_id: UUID) -> list[Notification]:
    """Every notification addressed to them, whether the inbox still shows it.

    A row hidden by a channel opt-out (`in_app_visible=false`) is still a row
    this deployment holds about them, and an art. 15 answer that returned only
    what the bell happens to render would be a partial answer that does not
    say so.
    """
    result = await db.execute(
        select(Notification)
        .where(Notification.recipient_user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def notification_preferences_of(
    db: AsyncSession, user_id: UUID
) -> list[NotificationChannelPreference]:
    result = await db.execute(
        select(NotificationChannelPreference).where(
            NotificationChannelPreference.user_id == user_id
        )
    )
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


async def export_size(db: AsyncSession, conversation_ids: list[UUID]) -> int:
    """How many characters of message content one export would carry.

    The export is assembled in memory and serialized in one response, and
    `MessageCreate.content` has no ceiling - so without a preflight the caller
    decides how much memory the worker spends, and five concurrent exports of a
    conversation somebody has been filling take the process with them. Counted
    in the database, where the rows already are.
    """
    if not conversation_ids:
        return 0
    total = await db.scalar(
        select(func.coalesce(func.sum(func.length(Message.content)), 0)).where(
            Message.conversation_id.in_(conversation_ids)
        )
    )
    return int(total or 0)


async def attachment_paths_of(db: AsyncSession, user_id: UUID) -> list[str]:
    """Where every file this person attached to any of their threads is stored.

    The account-deletion counterpart of `attachment_paths_in`. `chat_files`
    cascades from `users`, so the rows go with the account and the bytes stay:
    an erasure that leaves the uploads on disk has not erased them.
    """
    result = await db.execute(
        select(ChatFile.storage_path).where(
            ChatFile.user_id == user_id, ChatFile.storage_path.is_not(None)
        )
    )
    return [path for path in result.scalars().all() if path]


async def workspaces_of(db: AsyncSession, owner_ref: str) -> list[AgentWorkspace]:
    """The workspaces that are this person's own, by the string that names them."""
    result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.scope == "user", AgentWorkspace.owner_ref == owner_ref
        )
    )
    return list(result.scalars().all())


async def purge_workspaces_of(db: AsyncSession, owner_ref: str) -> int:
    """Delete their user-scoped workspaces, which no cascade reaches.

    `agent_workspaces.owner_ref` is a string, like `agent_memory_files.owner_key`
    and for the same reason - a workspace can belong to a conversation, an agent
    or a person - so there is no foreign key to follow when the person goes. The
    row survives holding a dangling owner reference, and a state-backed
    workspace holds the files themselves (#1421).

    Returns:
        How many workspaces were removed, for the audit entry.
    """
    result = await db.execute(
        sa_delete(AgentWorkspace).where(
            AgentWorkspace.scope == "user", AgentWorkspace.owner_ref == owner_ref
        )
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


def as_rows(items: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """The named fields of each row, as JSON-ready values.

    Named rather than "everything on the model", because an export is a document
    handed to a person and a model carries columns that are neither theirs nor
    meaningful to them - a hashed credential, an internal flag, a foreign key to
    a row they cannot see. Adding a column to a table must not silently add it to
    what every person can download.

    `getattr` without a default on purpose: a field named here that the model
    does not have is a mistake in this file, and answering it with `null` made
    every exported conversation say `archived: null` and every dashboard layout
    `widgets: null` - a value that reads as "we hold nothing" for data that is
    right there on the row.
    """
    return [{field: getattr(item, field) for field in fields} for item in items]
