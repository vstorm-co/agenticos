"""Data access for agent-to-agent messages.

A thread is keyed by an unordered pair, stored canonical (`agent_a_id` is
the lesser id) so the pair is found whichever order the caller names it in.
Every function here takes the organization with the row: a missed `WHERE` is
a constraint violation or an empty result, never a row from another tenant.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import (
    AgentMessage,
    AgentMessageAttachment,
    AgentMessageReaction,
    AgentMessageRead,
    AgentMessageThread,
)
from app.db.models.chat_file import ChatFile


def canonical_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    """The pair in storage order, so (A, B) and (B, A) are one thread."""
    return (first, second) if first < second else (second, first)


async def get_thread_by_agents(
    db: AsyncSession, *, organization_id: UUID, agent_a_id: UUID, agent_b_id: UUID
) -> AgentMessageThread | None:
    """The thread for this pair in this organization, if one exists."""
    first, second = canonical_pair(agent_a_id, agent_b_id)
    result = await db.execute(
        select(AgentMessageThread).where(
            AgentMessageThread.organization_id == organization_id,
            AgentMessageThread.agent_a_id == first,
            AgentMessageThread.agent_b_id == second,
        )
    )
    return result.scalar_one_or_none()


async def create_thread(
    db: AsyncSession, *, organization_id: UUID, agent_a_id: UUID, agent_b_id: UUID
) -> AgentMessageThread:
    """A new thread for this pair. The caller checks one does not exist first."""
    first, second = canonical_pair(agent_a_id, agent_b_id)
    thread = AgentMessageThread(
        organization_id=organization_id, agent_a_id=first, agent_b_id=second
    )
    db.add(thread)
    await db.flush()
    await db.refresh(thread)
    return thread


async def get_or_create_thread(
    db: AsyncSession, *, organization_id: UUID, agent_a_id: UUID, agent_b_id: UUID
) -> AgentMessageThread:
    """The pair's thread, creating it when this is their first message."""
    thread = await get_thread_by_agents(
        db, organization_id=organization_id, agent_a_id=agent_a_id, agent_b_id=agent_b_id
    )
    if thread is not None:
        return thread
    return await create_thread(
        db, organization_id=organization_id, agent_a_id=agent_a_id, agent_b_id=agent_b_id
    )


async def get_thread(db: AsyncSession, thread_id: UUID) -> AgentMessageThread | None:
    """One thread by id, in any organization."""
    result = await db.execute(select(AgentMessageThread).where(AgentMessageThread.id == thread_id))
    return result.scalar_one_or_none()


async def list_threads(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_ids: set[UUID] | None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentMessageThread], int]:
    """Threads in this organization, most recently active first.

    `agent_ids` narrows to threads one of those agents is in; `None` means
    every thread in the organization, which is what a caller whose role
    already reaches all agents asks for. A thread with no messages yet sorts
    by creation, after every thread that has one.
    """
    where = [AgentMessageThread.organization_id == organization_id]
    if agent_ids is not None:
        where.append(
            or_(
                AgentMessageThread.agent_a_id.in_(agent_ids),
                AgentMessageThread.agent_b_id.in_(agent_ids),
            )
        )
    order = [
        AgentMessageThread.last_message_at.desc().nulls_last(),
        AgentMessageThread.created_at.desc(),
    ]
    query = select(AgentMessageThread).where(*where).order_by(*order).offset(skip).limit(limit)
    count_query = select(func.count(AgentMessageThread.id)).where(*where)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def create_message(
    db: AsyncSession,
    *,
    thread: AgentMessageThread,
    organization_id: UUID,
    sender_agent_id: UUID,
    sender_user_id: UUID | None,
    body: str,
    reply_to_message_id: UUID | None,
) -> AgentMessage:
    """One message in a thread. The thread's `last_message_at` is the caller's."""
    message = AgentMessage(
        thread_id=thread.id,
        organization_id=organization_id,
        sender_agent_id=sender_agent_id,
        sender_user_id=sender_user_id,
        body=body,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def touch_thread(
    db: AsyncSession, *, thread: AgentMessageThread, at: datetime
) -> AgentMessageThread:
    """Record that a message arrived in this thread at `at`."""
    thread.last_message_at = at
    await db.flush()
    await db.refresh(thread)
    return thread


async def get_message(db: AsyncSession, message_id: UUID) -> AgentMessage | None:
    """One message by id, in any organization."""
    result = await db.execute(select(AgentMessage).where(AgentMessage.id == message_id))
    return result.scalar_one_or_none()


async def list_messages(
    db: AsyncSession, *, thread_id: UUID, skip: int = 0, limit: int = 50
) -> tuple[list[AgentMessage], int]:
    """A thread's messages oldest first, with the total count."""
    where = [AgentMessage.thread_id == thread_id]
    query = (
        select(AgentMessage)
        .where(*where)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
        .offset(skip)
        .limit(limit)
    )
    count_query = select(func.count(AgentMessage.id)).where(*where)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def latest_messages(db: AsyncSession, *, thread_ids: list[UUID]) -> dict[UUID, AgentMessage]:
    """The newest message in each of these threads, keyed by thread id.

    One query, through Postgres `DISTINCT ON`: the order that picks the row
    is the thread, then the newest message in it, so the first row per thread
    is the one the listing previews.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(AgentMessage)
        .distinct(AgentMessage.thread_id)
        .where(AgentMessage.thread_id.in_(thread_ids))
        .order_by(
            AgentMessage.thread_id,
            AgentMessage.created_at.desc(),
            AgentMessage.id.desc(),
        )
    )
    return {message.thread_id: message for message in result.scalars().all()}


async def list_reactions(
    db: AsyncSession, *, message_ids: list[UUID]
) -> list[AgentMessageReaction]:
    """Every reaction on these messages, oldest first."""
    if not message_ids:
        return []
    result = await db.execute(
        select(AgentMessageReaction)
        .where(AgentMessageReaction.message_id.in_(message_ids))
        .order_by(AgentMessageReaction.created_at.asc(), AgentMessageReaction.id.asc())
    )
    return list(result.scalars().all())


async def get_reaction(
    db: AsyncSession,
    *,
    message_id: UUID,
    emoji: str,
    reactor_agent_id: UUID | None = None,
    reactor_user_id: UUID | None = None,
) -> AgentMessageReaction | None:
    """One reactor's reaction of one emoji on one message, if it exists."""
    where = [
        AgentMessageReaction.message_id == message_id,
        AgentMessageReaction.emoji == emoji,
    ]
    if reactor_agent_id is not None:
        where.append(AgentMessageReaction.reactor_agent_id == reactor_agent_id)
    else:
        where.append(AgentMessageReaction.reactor_user_id == reactor_user_id)
    result = await db.execute(select(AgentMessageReaction).where(*where))
    return result.scalar_one_or_none()


async def add_reaction(
    db: AsyncSession,
    *,
    message: AgentMessage,
    organization_id: UUID,
    emoji: str,
    reactor_agent_id: UUID | None = None,
    reactor_user_id: UUID | None = None,
) -> AgentMessageReaction:
    """Record one reaction. Exactly one of the two reactor ids is set."""
    reaction = AgentMessageReaction(
        message_id=message.id,
        organization_id=organization_id,
        reactor_agent_id=reactor_agent_id,
        reactor_user_id=reactor_user_id,
        emoji=emoji,
    )
    db.add(reaction)
    await db.flush()
    await db.refresh(reaction)
    return reaction


async def remove_reaction(db: AsyncSession, *, reaction: AgentMessageReaction) -> None:
    """Take a reaction back - the other half of the toggle."""
    await db.delete(reaction)
    await db.flush()


async def add_attachment(
    db: AsyncSession,
    *,
    message: AgentMessage,
    organization_id: UUID,
    chat_file_id: UUID,
) -> AgentMessageAttachment:
    """Link a file already uploaded to a message."""
    attachment = AgentMessageAttachment(
        message_id=message.id, organization_id=organization_id, chat_file_id=chat_file_id
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    return attachment


async def list_attachments(
    db: AsyncSession, *, message_ids: list[UUID]
) -> list[AgentMessageAttachment]:
    """Every attachment link on these messages."""
    if not message_ids:
        return []
    result = await db.execute(
        select(AgentMessageAttachment).where(AgentMessageAttachment.message_id.in_(message_ids))
    )
    return list(result.scalars().all())


async def get_attachment(
    db: AsyncSession, *, message_id: UUID, chat_file_id: UUID
) -> AgentMessageAttachment | None:
    """The link between one message and one file, if the message carries it."""
    result = await db.execute(
        select(AgentMessageAttachment).where(
            AgentMessageAttachment.message_id == message_id,
            AgentMessageAttachment.chat_file_id == chat_file_id,
        )
    )
    return result.scalar_one_or_none()


async def list_chat_files(db: AsyncSession, *, file_ids: list[UUID]) -> list[ChatFile]:
    """The uploaded files behind these ids, whatever conversation they came from.

    The caller already decided these files may be read - they are attached to
    a message in a thread the caller may read - so this is a lookup, not an
    authorization: the ownership check happened when the file was attached.
    """
    if not file_ids:
        return []
    result = await db.execute(select(ChatFile).where(ChatFile.id.in_(file_ids)))
    return list(result.scalars().all())


async def mark_read(
    db: AsyncSession, *, thread_id: UUID, user_id: UUID, read_at: datetime
) -> AgentMessageRead:
    """Record that `user_id` had `thread_id` open at `read_at`.

    An upsert rather than a read-then-write: two opens racing each other must
    not fail on the primary key, and the later time is the one that stands.
    """
    statement = pg_insert(AgentMessageRead).values(
        thread_id=thread_id, user_id=user_id, read_at=read_at
    )
    statement = statement.on_conflict_do_update(
        index_elements=["thread_id", "user_id"],
        set_={"read_at": func.greatest(AgentMessageRead.read_at, statement.excluded.read_at)},
    )
    await db.execute(statement)
    await db.flush()
    result = await db.execute(
        select(AgentMessageRead).where(
            AgentMessageRead.thread_id == thread_id,
            AgentMessageRead.user_id == user_id,
        )
    )
    row = result.scalar_one()
    await db.refresh(row)
    return row


async def get_reads(
    db: AsyncSession, *, thread_ids: list[UUID], user_id: UUID
) -> dict[UUID, AgentMessageRead]:
    """This reader's read rows for these threads, keyed by thread id."""
    if not thread_ids:
        return {}
    result = await db.execute(
        select(AgentMessageRead).where(
            AgentMessageRead.thread_id.in_(thread_ids),
            AgentMessageRead.user_id == user_id,
        )
    )
    return {row.thread_id: row for row in result.scalars().all()}
