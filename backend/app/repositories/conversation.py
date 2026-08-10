"""Conversation repository."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, distinct, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.user import User
from app.repositories._search import contains_ci


async def agents_in_conversations(
    db: AsyncSession, conversation_ids: list[UUID]
) -> dict[UUID, list[Agent]]:
    """Which agents answered in each of these conversations, oldest turn first.

    One query per source for the whole page rather than one per row: a conversation
    list is fifty rows, and the alternative is fifty round trips to render a chip.

    An agent appears once however many times it answered - the list says who took
    part, not how often. Ordering by the first evidence of it answering makes that
    order stable across refreshes, which a set could not promise.

    **Two sources, and the second is why history works at all.** The message is the
    accurate one: `messages.agent_id` says which agent produced *that answer*, which
    is what a transcript needs. But it was written by a call that silently dropped
    the field for as long as web chat has existed, so every row before that fix has
    it null - and for those rows the attribution is not recoverable. `run_id` links a
    turn to its run from here on; nothing links the ones written before it.

    A *run* is recoverable: `agent_runs` has carried `conversation_id` and `agent_id`
    since it existed. It cannot say which answer came from which agent, and it does
    not have to - the question here is only "who took part in this conversation", and
    a completed run in it is exactly that evidence. So the two are merged, and a
    conversation from before the fix shows its agents.

    Only `completed` runs. A cancelled or failed one did not answer, and this list is
    read as "who answered here".

    And only *top-level* runs. A delegation gets an `agent_runs` row carrying the
    parent's `conversation_id` and a terminal status, so without the null test on
    `parent_run_id` every delegate the orchestrator called would appear as a
    participant the user never picked. A delegate answered the parent, not the
    conversation. The message-sourced half needs no such filter: `messages.agent_id`
    is the agent that produced the visible answer, and a delegation produces none.
    """
    if not conversation_ids:
        return {}

    first_turn = func.min(Message.created_at).label("first_turn")
    from_messages = await db.execute(
        select(Message.conversation_id, Agent, first_turn)
        .join(Agent, Agent.id == Message.agent_id)
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id, Agent.id)
        .order_by(Message.conversation_id, first_turn)
    )

    first_run = func.min(AgentRun.created_at).label("first_run")
    from_runs = await db.execute(
        select(AgentRun.conversation_id, Agent, first_run)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(
            AgentRun.conversation_id.in_(conversation_ids),
            AgentRun.status == "completed",
            AgentRun.parent_run_id.is_(None),
        )
        .group_by(AgentRun.conversation_id, Agent.id)
        .order_by(AgentRun.conversation_id, first_run)
    )

    # Merged on the earliest evidence from either source, so the order is the order
    # the agents appeared however the row was recorded.
    seen: dict[UUID, dict[UUID, tuple[datetime, Agent]]] = {}
    for rows in (from_messages.all(), from_runs.all()):
        for conversation_id, agent, at in rows:
            if conversation_id is None:
                continue
            found = seen.setdefault(conversation_id, {})
            existing = found.get(agent.id)
            if existing is None or at < existing[0]:
                found[agent.id] = (at, agent)

    return {
        conversation_id: [agent for _at, agent in sorted(agents.values(), key=lambda p: p[0])]
        for conversation_id, agents in seen.items()
    }


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


def _list_filters(
    *,
    search: str | None = None,
    agent_id: UUID | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[ColumnElement[bool]]:
    """The predicates both conversation listings narrow by.

    Written once because the two listings have to agree: the member sidebar and
    `/admin/conversations` ask the same three questions of a thread, and a
    difference between them would read as data missing from one screen rather
    than as two queries.

    `agent_id` narrows to threads *an agent answered in*, which is an EXISTS on
    messages rather than a column on the conversation: an agent is not a
    property of a thread - the picker can be changed mid-conversation, so one
    thread can have several. A join would multiply the rows and quietly inflate
    every message count on the admin page.

    Tenancy is **not** here. Each caller owns its own scope - the member listing
    filters on `organization_id` before any of this, the admin listing
    deliberately does not - and a predicate that sometimes carries a tenant
    filter is one nobody can read a guarantee out of. An `agent_id` belonging to
    another organization needs no special case: the EXISTS runs against messages
    of conversations the caller's own scope already narrowed, so it matches
    nothing rather than confirming the agent exists.
    """
    filters: list[ColumnElement[bool]] = []
    if search:
        filters.append(contains_ci(Conversation.title, search))
    if agent_id is not None:
        # `select_from` and `correlate` are both load-bearing. Left to itself
        # SQLAlchemy correlates *every* table it recognises from the enclosing
        # query - including `messages` - and the subquery ends up with no FROM
        # clause at all, which raises rather than returning wrong rows. Only
        # `conversations` may be correlated; `messages` is what this selects.
        filters.append(
            select(Message.id)
            .select_from(Message)
            .where(Message.conversation_id == Conversation.id, Message.agent_id == agent_id)
            .correlate(Conversation)
            .exists()
        )
    if archived_only:
        filters.append(Conversation.is_archived.is_(True))
    elif not include_archived:
        filters.append(Conversation.is_archived.is_(False))
    return filters


def _sort_columns() -> dict[str, Any]:
    """The columns a conversation listing can be ordered by, before the extras.

    Three of the sortable columns are nullable, and Postgres sorts NULL *first*
    on a descending order - so the default page opened on every thread that had
    never been written to, above the one updated a second ago, and they held the
    top of page one permanently. `updated_at` is null until the first edit,
    which is why it is coalesced here; `title` is null until one is generated.
    """
    return {
        "title": Conversation.title,
        "created_at": Conversation.created_at,
        "updated_at": func.coalesce(Conversation.updated_at, Conversation.created_at),
    }


def _ordering(columns: dict[str, Any], sort_by: str, sort_dir: str) -> Any:
    """One `ORDER BY`, defaulting to recency when the key is not one we sort on.

    A row with nothing in the sorted column sorts last whichever way the column
    is pointing: "no title" is not the largest title.
    """
    column = columns.get(sort_by, columns["updated_at"])
    column = column.desc() if sort_dir == "desc" else column.asc()
    return column.nulls_last()


async def get_conversations_by_user(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    agent_id: UUID | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> list[Conversation]:
    """Get one organization's conversations, optionally narrowed to one user.

    `organization_id` is a required keyword with no default: a call that omits
    the tenant would return every tenant's rows, and that mistake must not look
    like an ordinary call. The narrowing arguments after it are shared with the
    admin listing - see :func:`_list_filters` for what each one means.
    """
    query = select(Conversation).where(Conversation.organization_id == organization_id)
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    for condition in _list_filters(
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
    ):
        query = query.where(condition)
    query = query.order_by(_ordering(_sort_columns(), sort_by, sort_dir)).offset(skip).limit(limit)
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

    Narrows by the same predicates as the member listing - :func:`_list_filters`
    says what each one means, and `agent_id` in particular - and sorts by the
    same columns plus the two only this listing has.
    """
    msg_count_col = func.count(Message.id).label("message_count")
    query = (
        select(Conversation, msg_count_col, User.email.label("user_email"))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .outerjoin(User, User.id == Conversation.user_id)
        .group_by(Conversation.id, User.email)
    )
    count_query = select(func.count()).select_from(Conversation)

    if user_id is not None:
        query = query.where(Conversation.user_id == user_id)
        count_query = count_query.where(Conversation.user_id == user_id)
    for condition in _list_filters(
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
    ):
        query = query.where(condition)
        count_query = count_query.where(condition)

    # `owner` is null for every conversation that arrived through a channel
    # rather than a user, which is why this listing sorts nulls last too.
    sort_columns: dict[str, Any] = {
        **_sort_columns(),
        "owner": User.email,
        "messages": msg_count_col,
    }
    query = query.order_by(_ordering(sort_columns, sort_by, sort_dir)).offset(skip).limit(limit)

    total = await db.scalar(count_query) or 0
    rows = (await db.execute(query)).all()
    return [(conv, msg_count, email) for conv, msg_count, email in rows], total


async def count_conversations(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    search: str | None = None,
    agent_id: UUID | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
) -> int:
    """Count one organization's conversations, optionally narrowed to one user.

    Takes the same narrowing as :func:`get_conversations_by_user` because it
    answers a question about that page: a total counted without the filters the
    page was fetched with is a number that contradicts the rows under it.
    """
    query = select(func.count(Conversation.id)).where(
        Conversation.organization_id == organization_id
    )
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    for condition in _list_filters(
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
    ):
        query = query.where(condition)
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


async def get_messages_by_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    skip: int = 0,
    limit: int = 100,
    include_tool_calls: bool = False,
) -> list[Message]:
    """The turns one run produced, oldest first.

    Narrowed by `messages.run_id` rather than by a time window over the
    conversation: two runs started in one thread interleave, so windowing by the
    run's `started_at`/`ended_at` returns the wrong rows for the first and none
    for a run that never ended.
    """
    query = select(Message).where(Message.run_id == run_id)
    if include_tool_calls:
        query = query.options(selectinload(Message.tool_calls))
    query = query.options(selectinload(Message.files))
    query = query.order_by(Message.created_at.asc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_messages_by_run(db: AsyncSession, run_id: UUID) -> int:
    """Count the turns one run produced."""
    query = select(func.count(Message.id)).where(Message.run_id == run_id)
    result = await db.execute(query)
    return result.scalar() or 0


async def create_message(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    role: str,
    content: str,
    thinking: str | None = None,
    parts: list[dict[str, object]] | None = None,
    model_name: str | None = None,
    tokens_used: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: Decimal | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    run_id: UUID | None = None,
) -> Message:
    """Create a new message."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        thinking=thinking,
        parts=parts,
        model_name=model_name,
        tokens_used=tokens_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        run_id=run_id,
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


async def link_message_to_run(
    db: AsyncSession, *, message_id: UUID, run_id: UUID, conversation_id: UUID
) -> None:
    """Stamp `run_id` on a message that was already written.

    The prompt is persisted before the run row exists, on purpose: a build that
    refuses - a deleted secret, a removed model profile - must not lose what
    somebody typed. So the link is made once there is a run to link to.

    `conversation_id` narrows the statement rather than being taken on trust. A
    message id belonging to another thread then updates nothing, instead of
    moving that thread's turn into this run's transcript.
    """
    await db.execute(
        sql_update(Message)
        .where(Message.id == message_id, Message.conversation_id == conversation_id)
        .values(run_id=run_id)
    )


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


async def get_open_tool_call_in_run(
    db: AsyncSession, *, run_id: UUID, tool_call_id: str
) -> ToolCall | None:
    """A call this run made that has not returned yet, by the provider's own id.

    The row a gated call leaves behind. It is written when the run parks - with no
    result, because it has not run - and the thing that finally runs it is a
    *resume*, whose messages carry the return without the call it belongs to. So
    the only way back to the row is this lookup.

    Scoped by run rather than by conversation: a provider's `tool_call_id` is
    unique within a run and a conversation holds many runs, so the run is the
    boundary that is true rather than the one that happens to work.
    """
    query = (
        select(ToolCall)
        .join(Message, Message.id == ToolCall.message_id)
        .where(
            Message.run_id == run_id,
            ToolCall.tool_call_id == tool_call_id,
            ToolCall.completed_at.is_(None),
        )
        .order_by(ToolCall.started_at.asc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


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
