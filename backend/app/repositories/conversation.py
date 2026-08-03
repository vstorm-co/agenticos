"""Conversation repository."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent import Agent, AgentVersion
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.user import User


async def agents_in_conversations(
    db: AsyncSession, conversation_ids: list[UUID]
) -> dict[UUID, list[Agent]]:
    """Which agents answered in each of these conversations, oldest turn first.

    One query for the whole page rather than one per row: a conversation list is
    fifty rows, and the alternative is fifty round trips to render a chip.

    An agent appears once however many times it answered - the list says who
    took part, not how often. Ordering by the first message it sent makes that
    order stable across refreshes, which a set could not promise.
    """
    if not conversation_ids:
        return {}

    first_turn = func.min(Message.created_at).label("first_turn")
    result = await db.execute(
        select(Message.conversation_id, Agent, first_turn)
        .join(Agent, Agent.id == Message.agent_id)
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id, Agent.id)
        .order_by(Message.conversation_id, first_turn)
    )

    by_conversation: dict[UUID, list[Agent]] = {}
    for conversation_id, agent, _first_turn in result.all():
        by_conversation.setdefault(conversation_id, []).append(agent)
    return by_conversation


async def titles_for(
    db: AsyncSession, conversation_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, str]:
    """The title of each of these conversations, inside one organization.

    One query for a whole page, and scoped: an id from somewhere else answers
    with nothing rather than with a title, which is what stops a listing from
    confirming that a conversation exists in an organization the caller is not in.
    """
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(Conversation.id, Conversation.title).where(
            Conversation.id.in_(conversation_ids),
            Conversation.organization_id == organization_id,
        )
    )
    return {row.id: row.title for row in result.all()}


async def count_by_agent(
    db: AsyncSession, agent_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, int]:
    """How many conversations each of these agents has answered in.

    Counted through `messages` and not off the conversation, because a
    conversation is not had with one agent - the picker can be changed mid-thread,
    which is why `agent_id` sits on the message. `distinct` is what keeps a long
    thread from counting as fifty.

    For the workspaces a whole agent shares: "how many chats reach these files" is
    a number a table can show, and asking it per row would be one query per
    workspace.
    """
    if not agent_ids:
        return {}
    result = await db.execute(
        select(Message.agent_id, func.count(distinct(Message.conversation_id)))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.agent_id.in_(agent_ids),
            Conversation.organization_id == organization_id,
        )
        .group_by(Message.agent_id)
    )
    return {agent_id: count for agent_id, count in result.all() if agent_id is not None}


async def version_numbers(db: AsyncSession, version_ids: list[UUID]) -> dict[UUID, int]:
    """The human-readable number behind each version id.

    A transcript says "v3"; the message stores a UUID, which names nothing to a
    reader. Resolved in one query for the whole page rather than joined onto the
    message query, because most messages have no version at all and a join would
    pay for the column on every row that does not use it.
    """
    if not version_ids:
        return {}
    result = await db.execute(
        select(AgentVersion.id, AgentVersion.version).where(AgentVersion.id.in_(version_ids))
    )
    return {row[0]: row[1] for row in result.all()}


async def get_conversation_by_id(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    include_messages: bool = False,
) -> Conversation | None:
    """Get a conversation by ID without a tenant filter.

    Deliberately unscoped, like :func:`app.repositories.channel_bot.get_for_inbound`:
    callers that serve a member must go through
    :meth:`app.services.conversation.ConversationService.get_conversation`, which
    takes the active organization and enforces it. Grep for this function when
    auditing cross-tenant reads.
    """
    if include_messages:
        query = (
            select(Conversation)
            .options(
                selectinload(Conversation.messages).selectinload(Message.tool_calls),
                selectinload(Conversation.messages).selectinload(Message.files),
            )
            .where(Conversation.id == conversation_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()
    return await db.get(Conversation, conversation_id)


async def get_conversations_by_user(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
    include_archived: bool = False,
) -> list[Conversation]:
    """Get one organization's conversations, optionally narrowed to one user.

    `organization_id` is a required keyword with no default: a call that omits
    the tenant would return every tenant's rows, and that mistake must not look
    like an ordinary call.
    """
    query = select(Conversation).where(Conversation.organization_id == organization_id)
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    if not include_archived:
        query = query.where(Conversation.is_archived == False)  # noqa: E712
    query = (
        query.order_by(func.coalesce(Conversation.updated_at, Conversation.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def admin_list_with_users(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> tuple[list[tuple[Conversation, int, str | None]], int]:
    """Admin: list conversations across all users with message counts and owner email.

    Returns list of (conversation, message_count, user_email) tuples and total count.

    `agent_id` narrows to threads *an agent answered in*, which is an EXISTS on
    messages rather than a column on the conversation: an agent is not a
    property of a thread - the picker can be changed mid-conversation, so one
    thread can have several. A join would multiply the rows and quietly inflate
    every message count on the page.
    """
    msg_count_col = func.count(Message.id).label("message_count")
    query = (
        select(Conversation, msg_count_col, User.email.label("user_email"))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .outerjoin(User, User.id == Conversation.user_id)
        .group_by(Conversation.id, User.email)
    )
    count_query = select(func.count()).select_from(Conversation)

    if search:
        query = query.where(Conversation.title.ilike(f"%{search}%"))
        count_query = count_query.where(Conversation.title.ilike(f"%{search}%"))
    if user_id is not None:
        query = query.where(Conversation.user_id == user_id)
        count_query = count_query.where(Conversation.user_id == user_id)
    if agent_id is not None:
        # `select_from` and `correlate` are both load-bearing. Left to itself
        # SQLAlchemy correlates *every* table it recognises from the enclosing
        # query - including `messages` - and the subquery ends up with no FROM
        # clause at all, which raises rather than returning wrong rows. Only
        # `conversations` may be correlated; `messages` is what this selects.
        answered_here = (
            select(Message.id)
            .select_from(Message)
            .where(Message.conversation_id == Conversation.id, Message.agent_id == agent_id)
            .correlate(Conversation)
            .exists()
        )
        query = query.where(answered_here)
        count_query = count_query.where(answered_here)
    if archived_only:
        query = query.where(Conversation.is_archived.is_(True))
        count_query = count_query.where(Conversation.is_archived.is_(True))
    elif not include_archived:
        query = query.where(Conversation.is_archived.is_(False))
        count_query = count_query.where(Conversation.is_archived.is_(False))

    sort_columns: dict[str, Any] = {
        "title": Conversation.title,
        "created_at": Conversation.created_at,
        "updated_at": Conversation.updated_at,
        "owner": User.email,
        "messages": msg_count_col,
    }
    sort_col = sort_columns.get(sort_by, Conversation.updated_at)
    sort_col = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    query = query.order_by(sort_col).offset(skip).limit(limit)

    total = await db.scalar(count_query) or 0
    rows = (await db.execute(query)).all()
    return [(conv, msg_count, email) for conv, msg_count, email in rows], total


async def count_conversations(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    include_archived: bool = False,
) -> int:
    """Count one organization's conversations, optionally narrowed to one user."""
    query = select(func.count(Conversation.id)).where(
        Conversation.organization_id == organization_id
    )
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    if not include_archived:
        query = query.where(Conversation.is_archived == False)  # noqa: E712
    result = await db.execute(query)
    return result.scalar() or 0


async def create_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None = None,
    title: str | None = None,
) -> Conversation:
    """Create a new conversation owned by an organization.

    `organization_id` has no default on purpose: every conversation belongs to
    a tenant, and a caller that cannot name one has a bug rather than a default.
    `user_id` stays optional - channel conversations have no user.
    """
    conversation = Conversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def update_conversation(
    db: AsyncSession,
    *,
    db_conversation: Conversation,
    update_data: dict[str, Any],
) -> Conversation:
    """Update a conversation."""
    for field, value in update_data.items():
        setattr(db_conversation, field, value)

    db.add(db_conversation)
    await db.flush()
    await db.refresh(db_conversation)
    return db_conversation


async def archive_conversation(
    db: AsyncSession,
    *,
    db_conversation: Conversation,
) -> Conversation:
    """Archive a conversation."""
    db_conversation.is_archived = True
    db.add(db_conversation)
    await db.flush()
    await db.refresh(db_conversation)
    return db_conversation


async def delete_conversation(db: AsyncSession, *, db_conversation: Conversation) -> None:
    """Delete a conversation and all related messages/tool_calls (cascades)."""
    await db.delete(db_conversation)
    await db.flush()


async def get_message_by_id(db: AsyncSession, message_id: UUID) -> Message | None:
    """Get message by ID."""
    return await db.get(Message, message_id)


async def get_messages_by_conversation(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    skip: int = 0,
    limit: int = 100,
    include_tool_calls: bool = False,
) -> list[Message]:
    """Get messages for a conversation with pagination."""
    query = select(Message).where(Message.conversation_id == conversation_id)
    if include_tool_calls:
        query = query.options(selectinload(Message.tool_calls))
    query = query.options(selectinload(Message.files))
    query = query.order_by(Message.created_at.asc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_messages(db: AsyncSession, conversation_id: UUID) -> int:
    """Count messages in a conversation."""
    query = select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    result = await db.execute(query)
    return result.scalar() or 0


async def create_message(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    role: str,
    content: str,
    thinking: str | None = None,
    model_name: str | None = None,
    tokens_used: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: Decimal | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
) -> Message:
    """Create a new message."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        thinking=thinking,
        model_name=model_name,
        tokens_used=tokens_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    await db.execute(
        sql_update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=message.created_at)
    )

    return message


async def delete_message(db: AsyncSession, message_id: UUID) -> bool:
    """Delete a message."""
    message = await get_message_by_id(db, message_id)
    if message:
        await db.delete(message)
        await db.flush()
        return True
    return False


async def get_tool_call_by_id(db: AsyncSession, tool_call_id: UUID) -> ToolCall | None:
    """Get tool call by ID."""
    return await db.get(ToolCall, tool_call_id)


async def get_tool_calls_by_message(
    db: AsyncSession,
    message_id: UUID,
) -> list[ToolCall]:
    """Get tool calls for a message."""
    query = (
        select(ToolCall)
        .where(ToolCall.message_id == message_id)
        .order_by(ToolCall.started_at.asc())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_tool_call(
    db: AsyncSession,
    *,
    message_id: UUID,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any],
    started_at: datetime,
) -> ToolCall:
    """Create a new tool call record."""
    tool_call = ToolCall(
        message_id=message_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args=args,
        started_at=started_at,
        status="running",
    )
    db.add(tool_call)
    await db.flush()
    await db.refresh(tool_call)
    return tool_call


async def complete_tool_call(
    db: AsyncSession,
    *,
    db_tool_call: ToolCall,
    result: str,
    completed_at: datetime,
    success: bool = True,
) -> ToolCall:
    """Mark a tool call as completed."""
    db_tool_call.result = result
    db_tool_call.completed_at = completed_at
    db_tool_call.status = "completed" if success else "failed"

    if db_tool_call.started_at:
        delta = completed_at - db_tool_call.started_at
        db_tool_call.duration_ms = int(delta.total_seconds() * 1000)

    db.add(db_tool_call)
    await db.flush()
    await db.refresh(db_tool_call)
    return db_tool_call
