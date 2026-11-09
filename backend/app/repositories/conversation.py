"""Conversation repository."""

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NamedTuple
from uuid import UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    Numeric,
    Text,
    and_,
    case,
    cast,
    distinct,
    exists,
    func,
    literal,
    or_,
    select,
    type_coerce,
    union_all,
)
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer, load_only, raiseload, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.conversation_favourite import ConversationFavourite
from app.db.models.conversation_last_read import ConversationLastRead
from app.db.models.user import User
from app.repositories._search import contains_ci

# What `MessageFileRead` serializes, plus the key selectin groups rows by. A
# transcript never needs `parsed_content`, the upload's whole extracted text. It is
# narrowed per query rather than deferred on the model because `services/attachments.py`
# and `routes/v1/files.py` read it, and under asyncio a deferred load is a `MissingGreenlet`.
_MESSAGE_FILE_COLUMNS = (
    ChatFile.message_id,
    ChatFile.filename,
    ChatFile.mime_type,
    ChatFile.file_type,
)


type CodingHarness = Literal["claude_code", "codex"]


async def coding_agents_in_conversations(
    db: AsyncSession, conversation_ids: list[UUID]
) -> dict[UUID, list[CodingHarness]]:
    """Coding harnesses actually invoked here, newest first, once each.

    Read saved tool reports for the authorized page in one query. Refusals are
    plain text, and older reports may omit kind; neither current preferences nor
    an agent's edited spec can identify who worked in a historical conversation.
    """
    if not conversation_ids:
        return {}
    # PostgreSQL 16's soft validation lets plain refusals coexist with JSON
    # reports. Aggregate in SQL so only two labels per conversation cross the DB
    # boundary, rather than loading every coding task's answer into a list view.
    report = cast(
        case((func.pg_input_is_valid(ToolCall.result, "jsonb"), ToolCall.result), else_="{}"),
        JSONB,
    )
    harness = report["harness"].astext.label("harness")
    result = await db.execute(
        select(Message.conversation_id, harness)
        .join(ToolCall, ToolCall.message_id == Message.id)
        .where(
            Message.conversation_id.in_(conversation_ids),
            _tool_named(("run_coding_agent",)),
            harness.in_(("claude_code", "codex")),
            report["outcome"].astext.in_(("completed", "failed", "timed_out")),
        )
        .group_by(Message.conversation_id, harness)
        .order_by(Message.conversation_id, func.max(ToolCall.started_at).desc(), harness)
    )
    found: dict[UUID, list[CodingHarness]] = {}
    for conversation_id, harness_name in result.all():
        named: CodingHarness = "codex" if harness_name == "codex" else "claude_code"
        found.setdefault(conversation_id, []).append(named)
    return found


async def agents_in_conversations(
    db: AsyncSession, conversation_ids: list[UUID]
) -> dict[UUID, list[Agent]]:
    """Which agents each conversation was with, most recently used first.

    One query for the whole page rather than one per row: a conversation list is
    fifty rows, and the alternative is fifty round trips to render a chip.

    An agent appears once however many times it answered - the list says who took
    part, not how often. Ordering by its latest message or top-level run moves a
    reused agent back to the front; agent ids break ties across refreshes.

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

    Every run, whatever it ended as. The list is read as "who is this thread with",
    and a run that failed, was stopped or is still going is a message addressed to
    that agent: counting only completed ones left a thread whose agent broke on its
    first turn without a face in the sidebar, as if nobody had been asked.

    And only *top-level* runs. A delegation gets an `agent_runs` row carrying the
    parent's `conversation_id` and a terminal status, so without the null test on
    `parent_run_id` every delegate the orchestrator called would appear as a
    participant the user never picked. A delegate answered the parent, not the
    conversation. The message-sourced half needs no such filter: `messages.agent_id`
    is the agent that produced the visible answer, and a delegation produces none.
    """
    if not conversation_ids:
        return {}

    # Both sources in one statement, aggregated on ids before the agents are
    # joined: the chip needs five columns, and grouping whole rows carried each
    # agent's draft spec through the aggregate, once per conversation (#2248).
    evidence = union_all(
        select(
            Message.conversation_id.label("conversation_id"),
            Message.agent_id.label("agent_id"),
            Message.created_at.label("at"),
        ).where(Message.conversation_id.in_(conversation_ids), Message.agent_id.is_not(None)),
        select(AgentRun.conversation_id, AgentRun.agent_id, AgentRun.created_at).where(
            AgentRun.conversation_id.in_(conversation_ids),
            AgentRun.parent_run_id.is_(None),
        ),
    ).subquery()
    latest = func.max(evidence.c.at).label("latest")
    latest_use = (
        select(evidence.c.conversation_id, evidence.c.agent_id, latest)
        .where(evidence.c.conversation_id.is_not(None))
        .group_by(evidence.c.conversation_id, evidence.c.agent_id)
        .subquery()
    )
    result = await db.execute(
        select(latest_use.c.conversation_id, Agent)
        .join(Agent, Agent.id == latest_use.c.agent_id)
        .options(
            load_only(Agent.id, Agent.slug, Agent.name, Agent.avatar_url, Agent.avatar_color),
            raiseload("*"),
        )
        .order_by(latest_use.c.conversation_id, latest_use.c.latest.desc(), Agent.id)
    )
    found: dict[UUID, list[Agent]] = {}
    for conversation_id, agent in result.all():
        found.setdefault(conversation_id, []).append(agent)
    return found


class ConversationHead(NamedTuple):
    """What a listing needs of a conversation it references: its name, and whose it is."""

    title: str
    user_id: UUID | None


async def titles_for(
    db: AsyncSession, conversation_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, ConversationHead]:
    """The title and owner of each of these conversations, inside one organization.

    One query for a whole page, and scoped: an id from somewhere else answers
    with nothing rather than with a title, which is what stops a listing from
    confirming that a conversation exists in an organization the caller is not in.

    The owner travels with the title because the chat page lists its owner's
    threads: a link offered to anybody else lands on an empty sidebar dressed
    as the conversation, so a listing has to know whose thread it is naming.
    """
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(Conversation.id, Conversation.title, Conversation.user_id).where(
            Conversation.id.in_(conversation_ids),
            Conversation.organization_id == organization_id,
        )
    )
    return {row.id: ConversationHead(row.title, row.user_id) for row in result.all()}


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
    include_summary: bool = False,
    fresh: bool = False,
) -> Conversation | None:
    """Get a conversation by ID without a tenant filter.

    Deliberately unscoped, like :func:`app.repositories.channel_bot.get_for_inbound`:
    callers that serve a member must go through
    :meth:`app.services.conversation.ConversationService.get_conversation`, which
    takes the active organization and enforces it. Grep for this function when
    auditing cross-tenant reads.

    The large model summary is excluded and refuses implicit loading unless
    `include_summary` is requested. Only model-history reconstruction needs it.
    """
    summary_options = (
        () if include_summary else (defer(Conversation.summary_messages, raiseload=True),)
    )
    if include_messages or include_summary:
        query = (
            select(Conversation).options(*summary_options).where(Conversation.id == conversation_id)
        )
        if include_messages:
            query = query.options(
                selectinload(Conversation.messages).selectinload(Message.tool_calls),
                selectinload(Conversation.messages)
                .selectinload(Message.files)
                .load_only(*_MESSAGE_FILE_COLUMNS, raiseload=True),
            )
        result = await db.execute(query.execution_options(populate_existing=fresh))
        return result.scalar_one_or_none()
    if fresh:
        return await db.get(
            Conversation, conversation_id, options=summary_options, populate_existing=True
        )
    return await db.get(Conversation, conversation_id, options=summary_options)


async def get_guardrail_revision(db: AsyncSession, conversation_id: UUID) -> int | None:
    """The current refusal revision, independent of the session's identity map."""
    return await db.scalar(
        select(Conversation.guardrail_revision).where(Conversation.id == conversation_id)
    )


def _list_filters(
    *,
    search: str | None = None,
    agent_id: UUID | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
    hide_api: bool = False,
    hide_channels: bool = False,
    project_id: UUID | None = None,
    for_model: bool = False,
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
    filters: list[ColumnElement[bool]] = [Conversation.origin.is_distinct_from("workflow")]
    if for_model:
        filters.append(
            ~select(Message.id)
            .where(Message.conversation_id == Conversation.id, Message.guardrail_refused.is_(True))
            .correlate(Conversation)
            .exists()
        )
    if project_id is not None:
        filters.append(Conversation.project_id == project_id)
    if hide_api:
        # Null for every conversation opened in the console or a channel.
        filters.append(or_(Conversation.origin.is_(None), Conversation.origin != "api"))
    if hide_channels:
        # A thread a bot answers in belongs to its channel, not to the console's
        # list. An EXISTS on the session rather than a join, for the reason the
        # agent filter below gives: a join would multiply the rows.
        filters.append(
            ~select(ChannelSession.id)
            .where(ChannelSession.conversation_id == Conversation.id)
            .correlate(Conversation)
            .exists()
        )
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


async def authors_of(db: AsyncSession, identity_ids: list[UUID]) -> dict[UUID, ChannelIdentity]:
    """The chat accounts behind a page of messages, keyed by id.

    One query for the whole transcript rather than one per turn, for the reason
    :func:`agents_in_conversations` gives: a thread is a hundred messages and the
    alternative is a hundred round trips to render a hundred names.

    An empty list asks nothing - a dashboard thread has no chat accounts in it at
    all, which is the common case.
    """
    if not identity_ids:
        return {}
    result = await db.execute(
        select(ChannelIdentity).where(ChannelIdentity.id.in_(set(identity_ids)))
    )
    return {identity.id: identity for identity in result.scalars().all()}


def _reachable_by(
    user_id: UUID, participant_ids: Collection[UUID], project_ids: Collection[UUID]
) -> ColumnElement[bool]:
    """Whose conversation list a thread appears in.

    Theirs if they own it, and theirs if they are a *confirmed* participant of
    the room it came from. Participation used to be a correlated `EXISTS` over
    `messages.channel_identity_id` - who spoke - and speaking once kept the
    thread readable after the platform removed them from the channel (#641). So
    the ids arrive vetted instead: the caller runs :func:`participation_claims`
    through `app.services.channels.membership`, which asks the platform, and
    hands over only the threads whose membership held up.

    The default is therefore the narrow one. A caller that passes nothing gets
    owner-only, which fails safe - forgetting the participation step hides a
    thread rather than showing it to somebody who was removed.

    Owning reaches only a chat outside any project. One in a project is
    reached through the project, its starter's included: a person who lost the
    project would otherwise still list a chat that answers 404 when opened.
    `project_ids` are the projects this person may see, decided by the caller
    on the projects as they stand - a predicate over them rather than a list of
    their chats, which grows with every chat a busy project holds.
    """
    ways_in = [and_(Conversation.user_id == user_id, Conversation.project_id.is_(None))]
    if participant_ids:
        ways_in.append(Conversation.id.in_(participant_ids))
    if project_ids:
        ways_in.append(Conversation.project_id.in_(project_ids))
    return or_(*ways_in)


class ParticipationClaim(NamedTuple):
    """One "I spoke there" fact, addressed well enough to check it.

    The conversation a chat account of the user's wrote in, and the bot and
    platform chat the thread belongs to - which is what
    `app.services.channels.membership` needs to ask the platform whether the
    account is *still* in that channel. A claim is who spoke, never who may
    read (#641); nothing may treat one as access without that check.
    """

    conversation_id: UUID
    platform_user_id: str
    bot_id: UUID
    platform_chat_id: str


async def participation_claims(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> list[ParticipationClaim]:
    """Every channel this user's chat accounts have spoken in, by conversation.

    One query for the whole listing: messages joined to the identity that wrote
    them, to the session that names the room, distinct over the four scalars -
    scalars because `channel_bots` carries `json` columns, which have no
    equality operator, so a `DISTINCT` over the row itself is a 500 on a real
    database (see :func:`app.repositories.channel_session.bots_by_identity`).

    The join to `channel_sessions` is inner on purpose. A thread the session no
    longer points at - `/new` re-points `conversation_id` at a fresh row - has
    no channel anybody can ask about, and a claim that cannot be checked is
    refused rather than trusted (#641). The owner and an explicit share still
    reach such a thread; participation alone does not.
    """
    query = (
        select(
            Message.conversation_id,
            ChannelIdentity.platform_user_id,
            ChannelSession.bot_id,
            ChannelSession.platform_chat_id,
        )
        .join(ChannelIdentity, ChannelIdentity.id == Message.channel_identity_id)
        .join(ChannelSession, ChannelSession.conversation_id == Message.conversation_id)
        .where(ChannelIdentity.user_id == user_id)
        .distinct()
    )
    if organization_id is not None:
        query = query.join(Conversation, Conversation.id == Message.conversation_id).where(
            Conversation.organization_id == organization_id
        )
    if conversation_id is not None:
        query = query.where(Message.conversation_id == conversation_id)
    result = await db.execute(query)
    return [ParticipationClaim(*row) for row in result.all()]


# What a listing reads of each row - what `ConversationRead` draws, and no more.
# The rest is a run's working state: `summary_messages` is the summarised history
# itself, 3.7 KB on average in production and over 500 KB on a long thread, and a
# sidebar fetched and decoded it for thirty rows on every refresh. `raiseload`, so a
# caller that starts reading one of them from a listed row fails in a test rather
# than lazily loading per row.
LISTED_COLUMNS = (
    Conversation.id,
    Conversation.user_id,
    Conversation.organization_id,
    Conversation.title,
    Conversation.is_archived,
    Conversation.project_id,
    Conversation.origin,
    Conversation.created_at,
    Conversation.updated_at,
    Conversation.forked_from_conversation_id,
    Conversation.forked_from_message_id,
)


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


def favourited_by(user_id: UUID) -> ColumnElement[bool]:
    """Whether this reader has starred the conversation the query is over.

    An `EXISTS` rather than a join, for the reason `agent_id` is one in
    :func:`_list_filters`: a join against a table keyed on `(user_id,
    conversation_id)` cannot multiply a row today, and would the moment anything
    else is keyed differently. Correlated on `Conversation` alone, or SQLAlchemy
    correlates every table it recognises and the subquery loses its FROM.
    """
    return (
        select(ConversationFavourite.conversation_id)
        .select_from(ConversationFavourite)
        .where(
            ConversationFavourite.conversation_id == Conversation.id,
            ConversationFavourite.user_id == user_id,
        )
        .correlate(Conversation)
        .exists()
    )


# A run left "running" by a worker that died is not a run anybody is waiting on;
# past this the conversation stops showing as at work rather than spinning forever.
RUNNING_HORIZON = timedelta(hours=2)


class RunningActivity(NamedTuple):
    since: datetime
    run_ids: list[UUID]


async def running_activity(
    db: AsyncSession, conversation_ids: Collection[UUID]
) -> dict[UUID, RunningActivity]:
    """Active top-level run identities and their earliest start, in one page query."""
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(AgentRun.conversation_id, func.min(AgentRun.started_at), func.array_agg(AgentRun.id))
        .where(
            AgentRun.conversation_id.in_(list(conversation_ids)),
            AgentRun.parent_run_id.is_(None),
            AgentRun.status == RunStatus.RUNNING,
            AgentRun.surface != RunSurface.FOLLOW_UPS.value,
            AgentRun.ended_at.is_(None),
            AgentRun.started_at >= datetime.now(UTC) - RUNNING_HORIZON,
        )
        .group_by(AgentRun.conversation_id)
    )
    return {
        identifier: RunningActivity(since, list(run_ids))
        for identifier, since, run_ids in result.all()
        if identifier is not None and since is not None
    }


async def running_since(
    db: AsyncSession, conversation_ids: Collection[UUID]
) -> dict[UUID, datetime]:
    """Earliest start of active runs; callers needing identities use running_activity."""
    return {
        identifier: activity.since
        for identifier, activity in (await running_activity(db, conversation_ids)).items()
    }


async def running_users(db: AsyncSession, conversation_ids: Collection[UUID]) -> dict[UUID, UUID]:
    """Who started the run still at work in each of these conversations.

    The same runs `running_since` counts, so a list saying a thread is busy and
    one saying who is busy in it agree. The earliest, where two are running.
    """
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(AgentRun.conversation_id, AgentRun.user_id)
        .where(
            AgentRun.conversation_id.in_(list(conversation_ids)),
            AgentRun.parent_run_id.is_(None),
            AgentRun.status == RunStatus.RUNNING,
            AgentRun.surface != RunSurface.FOLLOW_UPS.value,
            AgentRun.ended_at.is_(None),
            AgentRun.started_at >= datetime.now(UTC) - RUNNING_HORIZON,
            AgentRun.user_id.is_not(None),
        )
        .order_by(AgentRun.started_at.desc())
    )
    # Newest first, so the earliest run's person is the one left standing.
    return dict(result.all())


async def readers_of(
    db: AsyncSession, conversation_ids: Collection[UUID]
) -> dict[UUID, list[tuple[User, datetime]]]:
    """Who has had each of these conversations open, and when last - newest first.

    One query for a page. Read from the rows `mark_read` keeps for the unread
    mark, which is exactly the record of somebody having had the thread open.
    """
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(ConversationLastRead.conversation_id, User, ConversationLastRead.read_at)
        .join(User, User.id == ConversationLastRead.user_id)
        .where(ConversationLastRead.conversation_id.in_(list(conversation_ids)))
        .order_by(ConversationLastRead.read_at.desc())
    )
    readers: dict[UUID, list[tuple[User, datetime]]] = {}
    for conversation_id, user, read_at in result.all():
        readers.setdefault(conversation_id, []).append((user, read_at))
    return readers


async def messages_by_id(db: AsyncSession, message_ids: Collection[UUID]) -> dict[UUID, Message]:
    """These messages, keyed by id; one query, and none for an empty set."""
    if not message_ids:
        return {}
    result = await db.execute(select(Message).where(Message.id.in_(set(message_ids))))
    return {message.id: message for message in result.scalars().all()}


async def release_project_chats(db: AsyncSession, *, user_id: UUID) -> None:
    """Take this person off the project chats they started, so the chats outlive them.

    Called as their account goes: the `users` cascade deletes the rows that
    still name them, and a project's chat is its members' to keep.
    """
    await db.execute(
        sql_update(Conversation)
        .where(Conversation.user_id == user_id, Conversation.project_id.is_not(None))
        .values(user_id=None)
    )
    await db.flush()


async def users_by_id(db: AsyncSession, user_ids: Collection[UUID]) -> dict[UUID, User]:
    """These people, keyed by id; one query, and none for an empty set."""
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(set(user_ids))))
    return {user.id: user for user in result.scalars().all()}


async def favourite_ids(
    db: AsyncSession, *, user_id: UUID, conversation_ids: Collection[UUID]
) -> set[UUID]:
    """Which of these conversations this reader has starred.

    One query for a whole page rather than a column on each row: the flag is the
    caller's, so it cannot be selected with the conversation without putting the
    reader into every query that reads one.
    """
    if not conversation_ids:
        return set()
    result = await db.execute(
        select(ConversationFavourite.conversation_id).where(
            ConversationFavourite.user_id == user_id,
            ConversationFavourite.conversation_id.in_(conversation_ids),
        )
    )
    return set(result.scalars().all())


async def mark_read(db: AsyncSession, *, user_id: UUID, conversation_id: UUID) -> None:
    """Record that this reader has the conversation open now.

    An upsert that only ever moves forward, so a retried or late request cannot
    make an answer the reader has seen look new again; the database's clock, the
    one an answer's `created_at` was stamped by, so the two compare.
    """
    stmt = pg_insert(ConversationLastRead).values(user_id=user_id, conversation_id=conversation_id)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "conversation_id"],
            set_={"read_at": func.greatest(ConversationLastRead.read_at, stmt.excluded.read_at)},
        )
    )


async def unread_ids(
    db: AsyncSession, *, user_id: UUID, conversation_ids: Collection[UUID]
) -> set[UUID]:
    """Which of these conversations have an answer this reader has not seen.

    One query for a page. Unread while the newest assistant message is newer than
    the reader's last read of it, or when they have never opened it and it has an
    answer - a routine's run-log, a thread somebody shared.
    """
    if not conversation_ids:
        return set()
    last_answer = (
        select(Message.conversation_id, func.max(Message.created_at).label("at"))
        .where(Message.conversation_id.in_(list(conversation_ids)), Message.role == "assistant")
        .group_by(Message.conversation_id)
        .subquery()
    )
    result = await db.execute(
        select(last_answer.c.conversation_id)
        .outerjoin(
            ConversationLastRead,
            (ConversationLastRead.conversation_id == last_answer.c.conversation_id)
            & (ConversationLastRead.user_id == user_id),
        )
        .where(
            or_(
                ConversationLastRead.read_at.is_(None),
                last_answer.c.at > ConversationLastRead.read_at,
            )
        )
    )
    return set(result.scalars().all())


async def set_favourite(
    db: AsyncSession, *, user_id: UUID, conversation_id: UUID, favourite: bool
) -> None:
    """Star or unstar one conversation for one reader.

    Idempotent in both directions, and under contention as well as on a retry.
    A star is a preference rather than a transaction, and a toast saying
    "already a favourite" would be the interface apologising for agreeing.

    **A read-then-insert is not enough.** Two overlapping POSTs for the same
    pair both saw `existing is None` and the second `flush()` raised on the
    primary key - an integrity error out of an endpoint that promises success,
    which a double-click or a retried request reaches (#1254). `ON CONFLICT DO
    NOTHING` is the shape `channel_identity_repo.get_or_create` already uses for
    this: `DO NOTHING` waits on a concurrent *uncommitted* insert of the same
    key, because it cannot decide until that transaction ends, and then writes
    nothing.

    The delete is a statement rather than a fetch-then-delete for the same
    reason: `DELETE ... WHERE` on a row another transaction is removing affects
    zero rows instead of raising, and "it was already gone" is the outcome the
    caller asked for.
    """
    if favourite:
        await db.execute(
            pg_insert(ConversationFavourite)
            .values(user_id=user_id, conversation_id=conversation_id)
            .on_conflict_do_nothing(index_elements=["user_id", "conversation_id"])
        )
    else:
        await db.execute(
            sql_delete(ConversationFavourite).where(
                ConversationFavourite.user_id == user_id,
                ConversationFavourite.conversation_id == conversation_id,
            )
        )
    await db.flush()


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
    favourites_first_for: UUID | None = None,
    participant_conversation_ids: Collection[UUID] = frozenset(),
    visible_project_ids: Collection[UUID] = frozenset(),
    hide_api: bool = False,
    hide_channels: bool = False,
    project_id: UUID | None = None,
    for_model: bool = False,
) -> list[Conversation]:
    """Get one organization's conversations, optionally narrowed to one user.

    `organization_id` is a required keyword with no default: a call that omits
    the tenant would return every tenant's rows, and that mistake must not look
    like an ordinary call. The narrowing arguments after it are shared with the
    admin listing - see :func:`_list_filters` for what each one means.

    `favourites_first_for` puts this reader's starred threads at the top, and it
    has to happen **here** rather than by grouping the page after it arrives: the
    list is paged, so a favourite sorted into page two by recency would sit under
    fifty threads that are not favourites (#929). Within each band the chosen
    sort still applies, because "the order you starred them in" is a second
    ordering nobody asked for.

    `participant_conversation_ids` widens a user's list to channel threads whose
    membership the caller has already confirmed against the platform - see
    :func:`_reachable_by` for why they arrive vetted rather than derived here.
    `visible_project_ids` widens it to every chat in the projects the caller
    decided this person may see.
    """
    query = (
        select(Conversation)
        .options(load_only(*LISTED_COLUMNS, raiseload=True))
        .where(Conversation.organization_id == organization_id)
    )
    if user_id:
        query = query.where(
            _reachable_by(user_id, participant_conversation_ids, visible_project_ids)
        )
    for condition in _list_filters(
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
        hide_api=hide_api,
        hide_channels=hide_channels,
        project_id=project_id,
        for_model=for_model,
    ):
        query = query.where(condition)
    orders = [] if favourites_first_for is None else [favourited_by(favourites_first_for).desc()]
    orders.append(_ordering(_sort_columns(), sort_by, sort_dir))
    query = query.order_by(*orders).offset(skip).limit(limit)
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
    participant_conversation_ids: Collection[UUID] = frozenset(),
    visible_project_ids: Collection[UUID] = frozenset(),
    hide_api: bool = False,
    hide_channels: bool = False,
    project_id: UUID | None = None,
    for_model: bool = False,
) -> int:
    """Count one organization's conversations, optionally narrowed to one user.

    Takes the same narrowing as :func:`get_conversations_by_user` because it
    answers a question about that page: a total counted without the filters the
    page was fetched with is a number that contradicts the rows under it -
    which includes the vetted participation set.
    """
    query = select(func.count(Conversation.id)).where(
        Conversation.organization_id == organization_id
    )
    if user_id:
        query = query.where(
            _reachable_by(user_id, participant_conversation_ids, visible_project_ids)
        )
    for condition in _list_filters(
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
        hide_api=hide_api,
        hide_channels=hide_channels,
        project_id=project_id,
        for_model=for_model,
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
    origin: str | None = None,
    project_id: UUID | None = None,
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
        origin=origin,
        project_id=project_id,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


class ForkRowCounts(NamedTuple):
    """Counts in a bounded prefix, saturated at each requested limit plus one."""

    messages: int
    tool_calls: int


async def lock_fork_history(
    db: AsyncSession,
    *,
    source: Conversation,
    through: Message,
    message_limit: int,
    tool_call_limit: int,
) -> ForkRowCounts | None:
    """Lock the source and its bounded prefix without loading any transcript payload.

    Parent and message locks also fence new messages and calls through their foreign
    keys. Existing call rows are locked separately, so a draft edit cannot grow the
    payload between measurement and copying. Missing source/answer means it was
    deleted since authorization; oversized prefixes return counts above a limit.
    The caller holds these locks through its transaction, including the copy.
    """
    parent = await db.scalar(
        select(Conversation)
        .options(defer(Conversation.summary_messages, raiseload=True), raiseload("*"))
        .execution_options(populate_existing=True)
        .where(
            Conversation.id == source.id,
            Conversation.user_id == source.user_id,
            Conversation.organization_id == source.organization_id,
        )
        .with_for_update()
    )
    if parent is None:
        return None
    answer = await db.scalar(
        select(Message)
        .options(
            load_only(
                Message.id, Message.conversation_id, Message.role, Message.ordinal, raiseload=True
            ),
            raiseload("*"),
        )
        .execution_options(populate_existing=True)
        .where(
            Message.id == through.id,
            Message.conversation_id == source.id,
            Message.role == "assistant",
        )
        .with_for_update()
    )
    if answer is None:
        return None
    message_ids = list(
        (
            await db.scalars(
                select(Message.id)
                .where(Message.conversation_id == source.id, Message.ordinal <= through.ordinal)
                .order_by(Message.ordinal)
                .limit(message_limit + 1)
                .with_for_update()
            )
        ).all()
    )
    tool_ids = (
        await db.scalars(
            select(ToolCall.id)
            .where(ToolCall.message_id.in_(message_ids))
            .order_by(ToolCall.id)
            .limit(tool_call_limit + 1)
            .with_for_update()
        )
    ).all()
    return ForkRowCounts(len(message_ids), len(tool_ids))


async def has_message_after(db: AsyncSession, *, source_id: UUID, ordinal: int) -> bool:
    """Whether the current checklist could include work after this fork point."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    Message.conversation_id == source_id,
                    Message.ordinal > ordinal,
                )
            )
        )
    )


async def fork_payload_bytes(db: AsyncSession, *, source_id: UUID, ordinal: int) -> int:
    """Measure the locked prefix's UTF-8 payload in SQL, before loading or inserting it.

    Called only after `lock_fork_history` has bounded and locked every row. Include
    tool arguments/results, attachment text and the summary when it will be copied.
    """
    message_ids = select(Message.id).where(
        Message.conversation_id == source_id, Message.ordinal <= ordinal
    )
    message_bytes = (
        select(
            func.coalesce(
                func.sum(
                    func.octet_length(func.coalesce(Message.content, ""))
                    + func.octet_length(func.coalesce(Message.thinking, ""))
                    + func.octet_length(func.coalesce(Message.attachment_context, ""))
                    + func.octet_length(func.coalesce(cast(Message.parts, Text), ""))
                ),
                0,
            )
        )
        .where(Message.id.in_(message_ids))
        .scalar_subquery()
    )
    tool_bytes = (
        select(
            func.coalesce(
                func.sum(
                    func.octet_length(func.coalesce(cast(ToolCall.args, Text), ""))
                    + func.octet_length(func.coalesce(ToolCall.result, ""))
                    + func.octet_length(ToolCall.tool_name)
                    + func.octet_length(ToolCall.tool_call_id)
                    + func.octet_length(func.coalesce(ToolCall.tool_id, ""))
                ),
                0,
            )
        )
        .where(ToolCall.message_id.in_(message_ids))
        .scalar_subquery()
    )
    summary_bytes = (
        select(
            func.octet_length(func.coalesce(Conversation.title, ""))
            + func.octet_length(func.coalesce(cast(Conversation.plan_items, Text), ""))
            + case(
                (
                    Conversation.summary_ordinal <= ordinal,
                    func.octet_length(func.coalesce(cast(Conversation.summary_messages, Text), "")),
                ),
                else_=0,
            )
        )
        .where(Conversation.id == source_id)
        .scalar_subquery()
    )
    return (
        await db.execute(select(cast(message_bytes + tool_bytes + summary_bytes, BigInteger)))
    ).scalar_one()


class ForkSummary(NamedTuple):
    messages: object
    stored_bytes: int


async def fork_summary(db: AsyncSession, *, source_id: UUID, ordinal: int) -> ForkSummary | None:
    """Read only an eligible summary, after the prefix has passed its SQL byte quota."""
    row = (
        await db.execute(
            select(
                Conversation.summary_messages,
                func.octet_length(cast(Conversation.summary_messages, Text)),
            ).where(
                Conversation.id == source_id,
                Conversation.summary_ordinal <= ordinal,
                Conversation.summary_messages.is_not(None),
            )
        )
    ).one_or_none()
    return ForkSummary(row[0], row[1]) if row is not None else None


async def has_fork_visual_images(db: AsyncSession, *, source_id: UUID, ordinal: int) -> bool:
    """Whether copying this prefix would retain references to source-only visual blobs."""
    images = ToolCall.args["images"]
    return bool(
        await db.scalar(
            select(
                exists().where(
                    ToolCall.message_id.in_(
                        select(Message.id).where(
                            Message.conversation_id == source_id, Message.ordinal <= ordinal
                        )
                    ),
                    _tool_named(("draw", "revise_visual")),
                    case(
                        (func.jsonb_typeof(images) == "array", func.jsonb_array_length(images)),
                        else_=0,
                    )
                    > 0,
                )
            )
        )
    )


async def read_candidates(
    db: AsyncSession, *, organization_id: UUID, ids: Collection[UUID]
) -> list[Conversation]:
    """Tenant-scoped metadata for one bounded access-gate batch."""
    return list(
        (
            await db.scalars(
                select(Conversation)
                .options(load_only(*LISTED_COLUMNS, raiseload=True))
                .where(Conversation.organization_id == organization_id, Conversation.id.in_(ids))
            )
        ).all()
    )


async def channel_thread_ids(db: AsyncSession, ids: Collection[UUID]) -> set[UUID]:
    """Which candidate threads still have a channel whose membership can be checked."""
    return set(
        (
            await db.scalars(
                select(Conversation.id)
                .join(ChannelSession, ChannelSession.conversation_id == Conversation.id)
                .where(Conversation.id.in_(ids))
                .distinct()
            )
        ).all()
    )


async def trigger_log_ids(db: AsyncSession, ids: Collection[UUID]) -> set[UUID]:
    """Narrow ownerless candidates to actual trigger logs before per-agent access checks."""
    return set(
        (
            await db.scalars(
                select(Conversation.id)
                .join(AgentTrigger, AgentTrigger.conversation_id == Conversation.id)
                .where(Conversation.id.in_(ids))
                .distinct()
            )
        ).all()
    )


class ForkVolume(NamedTuple):
    member_bytes: int
    organization_bytes: int


async def retained_fork_volume(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> ForkVolume:
    """Serialize admission and count retained copies, including source-less forks.

    The transaction lock remains held through insertion and commit. Deletion
    removes a charge with its row; rollback cannot leave a reservation behind.
    """
    await hold_subject(db, LockScope.CONVERSATION_FORK_STORAGE_PER_ORG, organization_id)
    row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(Conversation.fork_copy_bytes).filter(Conversation.user_id == user_id),
                    0,
                ),
                func.coalesce(func.sum(Conversation.fork_copy_bytes), 0),
            ).where(
                Conversation.organization_id == organization_id, Conversation.fork_copy_bytes > 0
            )
        )
    ).one()
    return ForkVolume(int(row[0]), int(row[1]))


async def fork_summary_bytes(db: AsyncSession, summary: list[dict[str, JsonValue]]) -> int:
    """Measure exactly what PostgreSQL will store, including expanded JSONB numbers."""
    return (
        await db.execute(select(func.octet_length(cast(literal(summary, type_=JSONB), Text))))
    ).scalar_one()


async def _fork_agent_attribution(
    db: AsyncSession, *, source_id: UUID, through: Message, messages: Sequence[Message]
) -> dict[UUID, tuple[UUID | None, UUID | None]]:
    """Recover missing assistant attribution without inventing an ambiguous author.

    Linked runs identify an exact version. Older unlinked rows can recover only
    the sole agent known in the prefix; delegates and later runs are not evidence.
    """
    missing = [
        message for message in messages if message.role == "assistant" and message.agent_id is None
    ]
    if not missing:
        return {}
    run_ids = {message.run_id for message in missing if message.run_id is not None}
    linked = {
        run_id: (agent_id, version_id)
        for run_id, agent_id, version_id in (
            await db.execute(
                select(AgentRun.id, AgentRun.agent_id, AgentRun.agent_version_id).where(
                    AgentRun.id.in_(run_ids),
                    AgentRun.conversation_id == source_id,
                    AgentRun.parent_run_id.is_(None),
                )
            )
        ).all()
    }
    evidence = union_all(
        select(Message.agent_id).where(
            Message.conversation_id == source_id,
            Message.ordinal <= through.ordinal,
            Message.agent_id.is_not(None),
        ),
        select(AgentRun.agent_id).where(
            AgentRun.conversation_id == source_id,
            AgentRun.created_at <= through.created_at,
            AgentRun.parent_run_id.is_(None),
        ),
    ).subquery()
    agents = (await db.scalars(select(evidence.c.agent_id).distinct().limit(2))).all()
    fallback = (agents[0], None) if len(agents) == 1 else (None, None)
    return {message.id: linked.get(message.run_id, fallback) for message in missing}


async def fork_conversation(
    db: AsyncSession,
    *,
    source: Conversation,
    through: Message,
    copy_bytes: int,
    restored_summary: list[dict[str, JsonValue]] | None = None,
) -> Conversation:
    """A new conversation holding `source`'s messages up to and including `through`.

    Owned by the source's owner, in its organization and project, with the same
    title. Each message is copied with its tool calls, in the order it was
    written, and flushed one at a time: the ordinal comes from an identity, and
    one multi-row insert does not promise to hand it out in the order of the
    rows.

    What a copy leaves behind is what belongs to the source's runs, readers or
    storage rather than to its history: the run and its cost, attachments, the
    server a tool call reached, and a part's pointer at the source's workspace -
    which would name the source to anybody the fork is shared with, and lead
    them to files they cannot open. A reply to a message that was not copied
    loses its target.

    The source's summary comes too when it ends at or before the fork point:
    a long conversation replays its summary and the turns after it, and
    without it the fork's model would read only the recent window of turns
    and lose everything older. It is re-anchored on the copy of the last turn
    it covers, since ordinals are new. The service restores externalized media
    before supplying `restored_summary`, so its bytes survive source deletion.
    A summary that reaches past the fork point
    covers turns the fork does not have, and is left behind.
    """
    fork = Conversation(
        user_id=source.user_id,
        organization_id=source.organization_id,
        title=source.title,
        project_id=source.project_id,
        forked_from_conversation_id=source.id,
        forked_from_message_id=through.id,
        fork_copy_bytes=copy_bytes,
        plan_items=deepcopy(source.plan_items),
    )
    db.add(fork)
    await db.flush()
    originals = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == source.id, Message.ordinal <= through.ordinal)
                .options(selectinload(Message.tool_calls))
                .execution_options(populate_existing=True)
                .order_by(Message.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )
    attribution = await _fork_agent_attribution(
        db, source_id=source.id, through=through, messages=originals
    )
    copied: dict[UUID, UUID] = {}
    for original in originals:
        agent_id, version_id = attribution.get(
            original.id, (original.agent_id, original.agent_version_id)
        )
        copy = Message(
            conversation_id=fork.id,
            role=original.role,
            content=original.content,
            thinking=original.thinking,
            model_name=original.model_name,
            parts=_without_source_workspace(original.parts, source.id),
            attachment_context=original.attachment_context,
            context_used_tokens=original.context_used_tokens,
            agent_id=agent_id,
            agent_version_id=version_id,
            channel_identity_id=original.channel_identity_id,
            author_user_id=original.author_user_id,
            reply_to_message_id=copied.get(original.reply_to_message_id)
            if original.reply_to_message_id is not None
            else None,
            interrupted=original.interrupted,
            guardrail_refused=original.guardrail_refused,
            created_at=original.created_at,
            tool_calls=[
                ToolCall(
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    tool_id=call.tool_id,
                    presentation_kind=call.presentation_kind,
                    args=call.args,
                    result=call.result,
                    status=call.status,
                    started_at=call.started_at,
                    completed_at=call.completed_at,
                    duration_ms=call.duration_ms,
                )
                for call in original.tool_calls
            ],
        )
        db.add(copy)
        await db.flush()
        copied[original.id] = copy.id
    summary, summary_ordinal = (
        await db.execute(
            select(Conversation.summary_messages, Conversation.summary_ordinal).where(
                Conversation.id == source.id
            )
        )
    ).one()
    if summary is not None and summary_ordinal is not None and summary_ordinal <= through.ordinal:
        covered = [original.id for original in originals if original.ordinal <= summary_ordinal]
        fork.summary_messages = restored_summary if restored_summary is not None else summary
        fork.summary_ordinal = (
            await db.scalar(select(Message.ordinal).where(Message.id == copied[covered[-1]]))
            if covered
            else 0
        )
        await db.flush()
    await db.refresh(fork)
    return fork


def _without_source_workspace(
    parts: list[dict[str, object]] | None, source_id: UUID
) -> list[dict[str, object]] | None:
    """A message's parts with any pointer at the source conversation's workspace removed."""
    if parts is None:
        return None
    kept: list[dict[str, object]] = []
    for part in parts:
        origin = part.get("file_source")
        if (
            isinstance(origin, dict)
            and origin.get("kind") == "conversation"
            and str(origin.get("id")) == str(source_id)
        ):
            part = {key: value for key, value in part.items() if key != "file_source"}
        kept.append(part)
    return kept


async def run_ids_through(db: AsyncSession, *, conversation_id: UUID, ordinal: int) -> set[UUID]:
    """The runs that wrote this conversation's messages up to and including `ordinal`."""
    result = await db.execute(
        select(Message.run_id)
        .where(
            Message.conversation_id == conversation_id,
            Message.ordinal <= ordinal,
            Message.run_id.is_not(None),
        )
        .distinct()
    )
    return {run_id for run_id in result.scalars().all() if run_id is not None}


async def owned_titles(
    db: AsyncSession, *, owner_id: UUID, conversation_ids: Collection[UUID]
) -> dict[UUID, str | None]:
    """The title of each of these conversations that `owner_id` owns, by id.

    One query for a page of forks naming their sources: a source that is gone or
    belongs to somebody else is simply absent.
    """
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(Conversation.id, Conversation.title).where(
            Conversation.id.in_(list(conversation_ids)), Conversation.user_id == owner_id
        )
    )
    return dict(result.tuples().all())


async def ensure_workflow_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    organization_id: UUID,
    workflow_id: UUID,
    source_conversation_id: UUID | None,
    project_id: UUID | None,
) -> Conversation | None:
    """Create a server-addressed internal thread once, without changing an existing row."""
    await db.execute(
        pg_insert(Conversation)
        .values(
            id=conversation_id,
            organization_id=organization_id,
            user_id=None,
            origin="workflow",
            workflow_id=workflow_id,
            source_conversation_id=source_conversation_id,
            project_id=project_id,
        )
        .on_conflict_do_nothing(index_elements=[Conversation.id])
    )
    await db.flush()
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.workflow_id == workflow_id,
            Conversation.origin == "workflow",
            Conversation.user_id.is_(None),
        )
    )
    return result.scalar_one_or_none()


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


async def get_owner(db: AsyncSession, conversation_id: UUID | None) -> UUID | None:
    """Whose conversation this is, or `None` for one with no owner or none at all."""
    if conversation_id is None:
        return None
    return await db.scalar(select(Conversation.user_id).where(Conversation.id == conversation_id))


async def delete_conversation(db: AsyncSession, *, db_conversation: Conversation) -> None:
    """Delete a conversation and all related messages/tool_calls (cascades)."""
    await db.delete(db_conversation)
    await db.flush()


class ToolCallSeen(NamedTuple):
    """One recorded tool call, with the agent that made it, for an audit list."""

    tool_name: str
    status: str
    started_at: datetime
    duration_ms: int | None
    agent_id: UUID | None
    agent_name: str | None
    run_id: UUID | None


async def recent_tool_calls(
    db: AsyncSession, *, organization_id: UUID, connection_id: UUID, limit: int
) -> list[ToolCallSeen]:
    """The organization's latest tool calls one MCP connection served (#2072).

    What the server was asked to do, newest first, by the connection recorded on
    each call - not by the tool-name prefix, which a member's own connection to
    the same service shares. Calls written before the connection was recorded
    have none and are not listed. The arguments and results are not read - they
    are the conversation's, and an audit of the server is not a window into it.
    """
    result = await db.execute(
        select(
            ToolCall.tool_name,
            ToolCall.status,
            ToolCall.started_at,
            ToolCall.duration_ms,
            Message.agent_id,
            Agent.name,
            Message.run_id,
        )
        .join(Message, Message.id == ToolCall.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(Agent, Agent.id == Message.agent_id)
        .where(
            Conversation.organization_id == organization_id,
            ToolCall.mcp_connection_id == connection_id,
        )
        .order_by(ToolCall.started_at.desc())
        .limit(limit)
    )
    return [ToolCallSeen(*row) for row in result.all()]


class ToolCallArgs(NamedTuple):
    """A recorded call's name and arguments, and the agent and run whose turn made it."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    agent_id: UUID | None = None
    run_id: UUID | None = None


def _tool_named(names: Collection[str]) -> ColumnElement[bool]:
    return or_(
        ToolCall.tool_id.in_(names),
        and_(
            ToolCall.tool_id.is_(None),
            ToolCall.presentation_kind.is_distinct_from("generic"),
            ToolCall.tool_name.in_(names),
        ),
    )


def _succeeded(result_prefixes: Collection[str]) -> ColumnElement[bool]:
    """A completed call whose result says it did its work.

    `completed` alone does not: a call refused with a retry prompt, or steered
    away with a sentence, is stored completed too.
    """
    return or_(*(ToolCall.result.startswith(prefix, autoescape=True) for prefix in result_prefixes))


async def tool_calls_named(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    names: Collection[str],
    result_prefixes: Collection[str],
    limit: int,
) -> list[ToolCallArgs]:
    """The conversation's latest calls of these tools that succeeded, oldest first.

    A call succeeded when it completed with a result opening on one of
    `result_prefixes` - see `_succeeded`.
    """
    newest = (
        select(
            ToolCall.tool_call_id,
            func.coalesce(ToolCall.tool_id, ToolCall.tool_name).label("tool_name"),
            ToolCall.args,
            ToolCall.started_at,
        )
        .join(Message, Message.id == ToolCall.message_id)
        .where(
            Message.conversation_id == conversation_id,
            _tool_named(names),
            ToolCall.status == "completed",
            _succeeded(result_prefixes),
        )
        .order_by(ToolCall.started_at.desc())
        .limit(limit)
        .subquery()
    )
    result = await db.execute(
        select(newest.c.tool_call_id, newest.c.tool_name, newest.c.args).order_by(
            newest.c.started_at.asc()
        )
    )
    return [ToolCallArgs(*row) for row in result.all()]


async def tool_call_in_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    tool_call_id: str,
    names: Collection[str],
    result_prefixes: Collection[str],
) -> ToolCallArgs | None:
    """One succeeded call of these tools, by the provider's id, within one conversation.

    Succeeded as `tool_calls_named` means it.

    The conversation is the boundary: the id is the model's to name, and a call in
    any other conversation is not one it may reach.
    """
    result = await db.execute(
        select(
            ToolCall.tool_call_id,
            func.coalesce(ToolCall.tool_id, ToolCall.tool_name),
            ToolCall.args,
            Message.agent_id,
            Message.run_id,
        )
        .join(Message, Message.id == ToolCall.message_id)
        .where(
            Message.conversation_id == conversation_id,
            ToolCall.tool_call_id == tool_call_id,
            _tool_named(names),
            ToolCall.status == "completed",
            _succeeded(result_prefixes),
        )
        .order_by(ToolCall.started_at.desc())
        .limit(1)
    )
    row = result.first()
    return ToolCallArgs(*row) if row is not None else None


class PersonRequest(NamedTuple):
    """A prompt `person_requests_since` found, and the run that took it, if one still exists."""

    message: Message
    run: AgentRun | None


async def person_requests_since(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, since: datetime, limit: int
) -> list[PersonRequest]:
    """What one person asked agents here since `since`, newest first (#2301).

    Their own messages: written by them in a shared chat, or unattributed in a
    conversation that is theirs - a one-person chat records no author per turn.

    Only a prompt that can have reached the input edge, because the nightly job
    hands what this returns to a model with no guardrails of its own (#2746). The
    row is committed before that edge reads it, so a row says nothing by being
    there. Left out:

    - A prompt a guardrail refused (`guardrail_refused`, set by the run and by
      `link_message_to_run`).
    - A prompt whose run is still going: marked only when the run ends.
    - A prompt with no run. It is a turn still being prepared, one refused before
      its run existed - an archived agent, a build that failed, a file the edge
      stopped - or one sent to a workflow, whose agent step keeps its own run.
      The exception is a turn that run retention took the run of: `run_id` is
      `SET NULL`, on the answer too, and an answer a model wrote is what shows
      the edge was passed. That also separates a row older than the mark, whose
      run is gone: the input edge left no answer under what it stopped. Nothing
      ties an answer to its prompt, so the turn must stand alone: a prompt under
      another prompt can be sitting inside that one's turn, above its answer.
      A spoken turn records no model, so it is left out once its run is gone.

    A run that ended is returned with its row for the caller to judge: one that
    stopped before its first request - a budget, a failure, a stop, a crash -
    never reached the edge either, and only the run's spec can say what it would
    have done.
    """
    following = aliased(Message)
    preceding = aliased(Message)
    answered_by_a_lost_run = (
        select(
            and_(
                following.role == "assistant",
                following.model_name.is_not(None),
                following.run_id.is_(None),
            )
        )
        .where(
            following.conversation_id == Message.conversation_id,
            following.ordinal > Message.ordinal,
        )
        .order_by(following.ordinal)
        .limit(1)
        .scalar_subquery()
    )
    under_a_prompt = (
        select(preceding.role == "user")
        .where(
            preceding.conversation_id == Message.conversation_id,
            preceding.ordinal < Message.ordinal,
        )
        .order_by(preceding.ordinal.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(Message, AgentRun)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(AgentRun, AgentRun.id == Message.run_id)
        .where(
            Conversation.organization_id == organization_id,
            Message.role == "user",
            Message.guardrail_refused.is_(False),
            or_(
                AgentRun.status != RunStatus.RUNNING,
                and_(
                    Message.run_id.is_(None),
                    answered_by_a_lost_run,
                    func.coalesce(under_a_prompt, False).is_(False),
                ),
            ),
            Message.created_at >= since,
            or_(
                Message.author_user_id == user_id,
                and_(Message.author_user_id.is_(None), Conversation.user_id == user_id),
            ),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return [PersonRequest(message, run) for message, run in result.tuples().all()]


async def mark_nightly_reads(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    content_hashes: Mapping[UUID, str],
) -> None:
    """Remember the source snapshots read by a successful look in this transaction.

    Recheck ownership and refusal after the model call. A changed message keeps
    its old digest, so its new content remains unread. Sorted row locks keep
    overlapping batches from taking the message locks in opposite orders.
    """
    if not content_hashes:
        return
    owned = (
        select(Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.organization_id == organization_id,
            Message.role == "user",
            Message.guardrail_refused.is_(False),
            or_(
                Message.author_user_id == user_id,
                and_(Message.author_user_id.is_(None), Conversation.user_id == user_id),
            ),
        )
    )
    for message_id in sorted(content_hashes):
        await db.execute(
            sql_update(Message)
            .where(Message.id == message_id, Message.id.in_(owned))
            .values(
                nightly_read_by_user_id=user_id,
                nightly_read_content_hash=content_hashes[message_id],
            )
            .execution_options(synchronize_session="fetch")
        )
    await db.flush()


async def get_fork_point(db: AsyncSession, message_id: UUID) -> Message | None:
    """Read only an answer's identity and position before applying copy quotas."""
    return await db.scalar(
        select(Message)
        .where(Message.id == message_id)
        .options(
            load_only(
                Message.id, Message.conversation_id, Message.role, Message.ordinal, raiseload=True
            ),
            raiseload("*"),
        )
    )


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
    latest: bool = False,
    before: UUID | None = None,
    for_model: bool = False,
    fresh: bool = False,
) -> list[Message]:
    """Get messages for a conversation, in the order they were written.

    `latest` selects the newest page, still returned oldest first; `before` selects
    messages older than that message of this conversation (a conversation-scoped
    ordinal cursor). Combine both to page backwards without concurrent appends
    shifting offsets. The default is ascending offset pagination.

    Ordered by `ordinal` rather than `created_at`: one turn writes the question
    and the answer in a single transaction, and `func.now()` gives both the same
    timestamp - so this used to return the answer above the question whenever the
    planner felt like it. See `Message.ordinal`.
    """
    query = select(Message).where(Message.conversation_id == conversation_id)
    if for_model:
        query = query.where(Message.guardrail_refused.is_(False))
    if include_tool_calls or fresh:
        query = query.options(selectinload(Message.tool_calls))
    query = query.options(
        selectinload(Message.files).load_only(*_MESSAGE_FILE_COLUMNS, raiseload=True)
    )
    if before is not None:
        boundary = (
            select(Message.ordinal)
            .where(Message.id == before, Message.conversation_id == conversation_id)
            .scalar_subquery()
        )
        query = query.where(Message.ordinal < boundary)
    order = Message.ordinal.desc() if latest else Message.ordinal.asc()
    query = query.order_by(order).offset(skip).limit(limit)
    result = await db.execute(query.execution_options(populate_existing=fresh))
    items = list(result.scalars().all())
    return list(reversed(items)) if latest else items


async def count_messages(
    db: AsyncSession, conversation_id: UUID, *, for_model: bool = False
) -> int:
    """Count messages in a conversation."""
    query = select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    if for_model:
        query = query.where(Message.guardrail_refused.is_(False))
    result = await db.execute(query)
    return result.scalar() or 0


async def conversation_cost(
    db: AsyncSession, conversation_id: UUID
) -> tuple[int, int, Decimal, bool | None] | None:
    """Input tokens, output tokens, money and whether the money is a floor.

    Aggregated here rather than summed by a client, because a client only holds
    the page it asked for: the transcript endpoint pages at 100, so adding up
    what is on screen answers "the first hundred turns" while reading as "this
    conversation".

    `None` when nothing in the thread was ever measured - a conversation older
    than the columns, or one whose every turn failed before a cost was read.
    Zeroes would be a claim, and this has none to make.

    The partial flag is `bool_or`: one unpriced turn makes the whole total a
    floor. It stays `None` where no turn recorded the flag at all, which is the
    honest "nobody knows" rather than "exact".
    """
    # Follow-up runs have no transcript message of their own. Count them once
    # beside the measured messages, without changing the main answer's cost.
    costs = union_all(
        select(
            Message.input_tokens, Message.output_tokens, Message.cost_usd, Message.cost_is_partial
        ).where(Message.conversation_id == conversation_id),
        select(
            AgentRun.input_tokens,
            AgentRun.output_tokens,
            AgentRun.cost_usd,
            AgentRun.cost_is_partial,
        ).where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.surface == RunSurface.FOLLOW_UPS.value,
            AgentRun.ended_at.is_not(None),
        ),
    ).subquery()
    result = await db.execute(
        select(
            type_coerce(func.coalesce(func.sum(costs.c.input_tokens), 0), Integer),
            type_coerce(func.coalesce(func.sum(costs.c.output_tokens), 0), Integer),
            type_coerce(func.coalesce(func.sum(costs.c.cost_usd), 0), Numeric),
            func.bool_or(costs.c.cost_is_partial),
            func.count(costs.c.input_tokens),
        )
    )
    input_tokens, output_tokens, cost_usd, partial, measured = result.one()
    if not measured:
        return None
    return int(input_tokens), int(output_tokens), Decimal(cost_usd), partial


class Attributed(NamedTuple):
    """What a run's messages already claim of what the run spent."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


async def attributed_to_run(db: AsyncSession, run_id: UUID) -> Attributed:
    """What this run's messages already claim of what the run spent.

    A run row carries *cumulative* totals, and one run can write more than one
    assistant turn: a run that parks and is resumed writes the parked half and the
    continuation, and the resume's row says what the whole run has cost by then.
    Stamping each with the row's figure would count the parked half twice, so each
    turn is written with the difference - and the messages of a run then sum to
    exactly what the run says it spent.

    Zero for a run that has written nothing yet, which is every ordinary turn.
    """
    result = await db.execute(
        select(
            type_coerce(func.coalesce(func.sum(Message.input_tokens), 0), Integer),
            type_coerce(func.coalesce(func.sum(Message.output_tokens), 0), Integer),
            type_coerce(func.coalesce(func.sum(Message.cost_usd), 0), Numeric),
            type_coerce(func.coalesce(func.sum(Message.cache_read_tokens), 0), Integer),
            type_coerce(func.coalesce(func.sum(Message.cache_write_tokens), 0), Integer),
        ).where(Message.run_id == run_id)
    )
    input_tokens, output_tokens, cost_usd, cache_read, cache_write = result.one()
    return Attributed(
        int(input_tokens), int(output_tokens), Decimal(cost_usd), int(cache_read), int(cache_write)
    )


class RunOutcome(NamedTuple):
    """How a run ended and how long it took, for the turns it produced."""

    status: str
    duration_ms: int | None
    started_at: datetime | None = None


async def run_outcomes(db: AsyncSession, run_ids: Collection[UUID]) -> dict[UUID, RunOutcome]:
    """How each of these runs ended and how long it took, for the turns they produced.

    One query for a page of messages, the same bargain the rating counts make. A
    transcript needs the status to say that a turn was *stopped*: a cancelled run
    leaves a half-written answer that reads exactly like a complete one. It needs the
    duration to fold the work before an answer into "Worked for 12s" - a span that
    includes any wait for an approval, because the run was open all that time.
    """
    if not run_ids:
        return {}
    result = await db.execute(
        select(AgentRun.id, AgentRun.status, AgentRun.started_at, AgentRun.ended_at).where(
            AgentRun.id.in_(list(run_ids))
        )
    )
    return {
        run_id: RunOutcome(
            status=status,
            started_at=started,
            duration_ms=(
                round((ended - started).total_seconds() * 1000)
                if started is not None and ended is not None
                else None
            ),
        )
        for run_id, status, started, ended in result.all()
    }


def _refused(run_id: UUID) -> ColumnElement[bool]:
    """Whether `run_id` ended `guardrail_blocked`, for a row written after it did (#2578)."""
    return exists().where(
        AgentRun.id == run_id, AgentRun.status == RunStatus.GUARDRAIL_BLOCKED.value
    )


async def get_recent_messages(
    db: AsyncSession, conversation_id: UUID, *, limit: int
) -> list[Message]:
    """The last `limit` messages of a conversation, still oldest first.

    The window every surface reminds a model of, in one place because the offset
    has been got wrong from both ends already. `get_messages_by_conversation`
    orders oldest-first, so a bare `limit` returns a thread's *opening*
    exchanges and drops what was just said: that is how the widget forgot the
    question before the one it was answering (#39), and how a channel bot past
    200 messages came to answer plausibly from a conversation that had stopped
    hundreds of turns ago (#638). Neither errored.

    One `COUNT(*)` on an indexed column is what the right offset costs.
    """
    total = await count_messages(db, conversation_id)
    return await get_messages_by_conversation(
        db, conversation_id, skip=max(0, total - limit), limit=limit, fresh=True
    )


async def get_messages_after(
    db: AsyncSession, conversation_id: UUID, *, ordinal: int, limit: int
) -> list[Message]:
    """The last `limit` messages written after `ordinal`, still oldest first.

    What a conversation has said since its summary was taken, which is the half
    of the history the summary does not account for. Bounded like
    `get_recent_messages` is, and for the same reason: a thread nobody compacts
    again must not grow into an unbounded prompt.

    Refresh the refusal flag while keeping serializable relationships loaded:
    the same identity-map rows can still be returned by the turn that wrote them.
    """
    total = await db.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id, Message.ordinal > ordinal
        )
    )
    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.ordinal > ordinal)
        .options(
            selectinload(Message.tool_calls),
            selectinload(Message.files).load_only(*_MESSAGE_FILE_COLUMNS, raiseload=True),
        )
        .order_by(Message.ordinal.asc())
        .offset(max(0, (total or 0) - limit))
        .limit(limit)
    )
    result = await db.execute(query.execution_options(populate_existing=True))
    return list(result.scalars().all())


async def capability_loads_in_messages(
    db: AsyncSession, message_ids: Collection[UUID]
) -> list[ToolCall]:
    """Completed capability loads in an already-authorized history window.

    Read only these calls, not every potentially large tool result in the thread.
    The service verifies the recorded return before restoring the load state.
    """
    if not message_ids:
        return []
    result = await db.scalars(
        select(ToolCall)
        .where(
            ToolCall.message_id.in_(message_ids),
            ToolCall.tool_name.in_(("load_capability", "read_skill")),
            ToolCall.status == "completed",
            ToolCall.result.is_not(None),
        )
        .order_by(ToolCall.started_at, ToolCall.id)
    )
    return list(result.all())


async def set_summary(
    db: AsyncSession,
    *,
    db_conversation: Conversation,
    messages: list[dict[str, Any]],
    ordinal: int,
    expected_revision: int,
) -> bool:
    """Record the history a summary reduced this conversation to.

    One row per conversation rather than a log of them: the newest summary is
    written over the last, because it was produced *from* it and the older one
    describes a thread that no longer exists.
    """
    updated = await db.scalar(
        sql_update(Conversation)
        .where(
            Conversation.id == db_conversation.id,
            Conversation.guardrail_revision == expected_revision,
        )
        .values(summary_messages=messages, summary_ordinal=ordinal)
        .returning(Conversation.id)
    )
    await db.flush()
    await db.refresh(db_conversation)
    return updated is not None


async def set_overhead(
    db: AsyncSession, *, db_conversation: Conversation, tokens: int
) -> Conversation:
    """Record what a request here carries before a single message."""
    db_conversation.overhead_tokens = tokens
    await db.flush()
    await db.refresh(db_conversation)
    return db_conversation


async def set_reminder_state(
    db: AsyncSession, *, db_conversation: Conversation, state: dict[str, Any]
) -> Conversation:
    """Record how far this conversation's system-reminders cadence has advanced."""
    db_conversation.reminder_state = state
    await db.flush()
    await db.refresh(db_conversation)
    return db_conversation


async def set_plan(
    db: AsyncSession, *, db_conversation: Conversation, items: list[dict[str, Any]]
) -> Conversation:
    """Record the checklist this conversation's agent is working to."""
    db_conversation.plan_items = items
    await db.flush()
    await db.refresh(db_conversation)
    return db_conversation


async def last_ordinal(db: AsyncSession, conversation_id: UUID) -> int:
    """The ordinal of the newest message, or 0 for a conversation with none."""
    highest = await db.scalar(
        select(func.max(Message.ordinal)).where(Message.conversation_id == conversation_id)
    )
    return highest or 0


async def get_messages_by_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    skip: int = 0,
    limit: int = 100,
    include_tool_calls: bool = False,
    newest: bool = False,
) -> list[Message]:
    """The turns one run produced, chronologically; optionally select its newest page.

    Narrowed by `messages.run_id` rather than by a time window over the
    conversation: two runs started in one thread interleave, so windowing by the
    run's `started_at`/`ended_at` returns the wrong rows for the first and none
    for a run that never ended.
    """
    query = select(Message).where(Message.run_id == run_id)
    if include_tool_calls:
        query = query.options(selectinload(Message.tool_calls))
    query = query.options(
        selectinload(Message.files).load_only(*_MESSAGE_FILE_COLUMNS, raiseload=True)
    )
    query = (
        query.order_by(Message.ordinal.desc() if newest else Message.ordinal.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    rows = list(result.scalars().all())
    return list(reversed(rows)) if newest else rows


async def last_answer_of_run(db: AsyncSession, run_id: UUID) -> str | None:
    """The latest assistant turn one run wrote that says something, or `None`."""
    result = await db.execute(
        select(Message.content)
        .where(
            Message.run_id == run_id,
            Message.role == "assistant",
            Message.content.is_not(None),
            Message.content != "",
        )
        .order_by(Message.ordinal.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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
    client_message_id: str | None = None,
    thinking: str | None = None,
    parts: list[dict[str, object]] | None = None,
    model_name: str | None = None,
    tokens_used: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    cost_usd: Decimal | None = None,
    cost_is_partial: bool | None = None,
    context_used_tokens: int | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    run_id: UUID | None = None,
    channel_identity_id: UUID | None = None,
    author_user_id: UUID | None = None,
    reply_to_message_id: UUID | None = None,
    attachment_context: str | None = None,
) -> Message:
    """Create a new message."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        client_message_id=client_message_id,
        attachment_context=attachment_context,
        channel_identity_id=channel_identity_id,
        author_user_id=author_user_id,
        reply_to_message_id=reply_to_message_id,
        thinking=thinking,
        parts=parts,
        model_name=model_name,
        tokens_used=tokens_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
        context_used_tokens=context_used_tokens,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        run_id=run_id,
        guardrail_refused=False if run_id is None else _refused(run_id),
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    # Nothing hangs off a message that was just written, so say so rather than
    # leave both collections to a lazy load: a route serializing the new row
    # read them outside the session's async context and answered 500.
    set_committed_value(message, "tool_calls", [])
    set_committed_value(message, "files", [])

    await db.execute(
        sql_update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=message.created_at)
    )

    if message.guardrail_refused:
        await _invalidate_refused_history(db, conversation_id, message.ordinal)
    return message


async def save_workflow_message(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    workflow_run_id: UUID,
    content: str,
    parts: list[dict[str, object]],
) -> Message:
    """Keep the pending workflow card and its final answer in the same chat message.

    A stable identity lets a reloaded chat discover a waiting workflow and keeps
    terminal delivery from adding a second copy of the card.

    The card is admitted early in the thread, but its answer can arrive after the
    person has sent more turns and those turns have been compacted into a summary.
    Left at its admission `ordinal`, the answer would sit at or below the summary
    cutoff and vanish from the next turn's history - it is in neither the saved
    summary nor the rows replayed after it. On a material change the row moves to
    the `ordinal` this INSERT allocated: PostgreSQL evaluates the identity default
    before `ON CONFLICT`, so `excluded.ordinal` is a fresh position even when no
    row is inserted. An identical redelivery keeps its ordinal, so a terminal
    answer already compacted into a summary is not replayed a second time.
    """
    statement = pg_insert(Message).values(
        id=uuid5(workflow_run_id, "workflow-chat-message"),
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        parts=parts,
    )
    advanced = case(
        (
            or_(
                Message.content.is_distinct_from(statement.excluded.content),
                Message.parts.is_distinct_from(statement.excluded.parts),
            ),
            statement.excluded.ordinal,
        ),
        else_=Message.ordinal,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Message.id],
        set_={
            "content": content,
            "parts": parts,
            "ordinal": advanced,
        },
    ).returning(Message)
    message = (await db.execute(statement)).scalar_one()
    await db.execute(
        sql_update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(UTC))
    )
    await db.flush()
    await db.refresh(message)
    return message


async def create_voice_turn(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    role: Literal["user", "assistant"],
    content: str,
    turn_id: str,
    interrupted: bool,
    run_id: UUID,
    agent_id: UUID | None,
    agent_version_id: UUID | None,
    parts: list[dict[str, object]] | None,
) -> Message | None:
    """Write one spoken turn, or nothing when this turn is already written (#54).

    `ON CONFLICT DO NOTHING` on (conversation_id, turn_id): the voice service
    writes each turn the moment it finishes, from its own session, and a
    retried write after a timeout must not leave the turn twice. Like
    :func:`create_message`, a written turn moves the conversation up the list.
    """
    statement = (
        pg_insert(Message)
        .values(
            conversation_id=conversation_id,
            role=role,
            content=content,
            turn_id=turn_id,
            interrupted=interrupted,
            run_id=run_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            parts=parts,
        )
        .on_conflict_do_nothing(
            index_elements=[Message.conversation_id, Message.turn_id],
            index_where=Message.turn_id.is_not(None),
        )
        .returning(Message)
    )
    message = (await db.execute(statement)).scalar_one_or_none()
    if message is None:
        return None
    await db.execute(
        sql_update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=message.created_at)
    )
    await db.flush()
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
    await _mark_refused(
        db,
        and_(
            Message.id == message_id, Message.conversation_id == conversation_id, _refused(run_id)
        ),
    )


async def _invalidate_refused_history(
    db: AsyncSession, conversation_id: UUID, ordinal: int
) -> None:
    covered = Conversation.summary_ordinal >= ordinal
    await db.execute(
        sql_update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(
            guardrail_revision=Conversation.guardrail_revision + 1,
            summary_messages=case((covered, None), else_=Conversation.summary_messages),
            summary_ordinal=case((covered, None), else_=Conversation.summary_ordinal),
        )
    )


async def _mark_refused(db: AsyncSession, predicate: ColumnElement[bool]) -> None:
    rows = await db.execute(
        sql_update(Message)
        .where(predicate, Message.guardrail_refused.is_(False))
        .values(guardrail_refused=True, attachment_context=None)
        .returning(Message.conversation_id, Message.ordinal)
    )
    earliest: dict[UUID, int] = {}
    for conversation_id, ordinal in rows.all():
        earliest[conversation_id] = min(earliest.get(conversation_id, ordinal), ordinal)
    for conversation_id, ordinal in earliest.items():
        await _invalidate_refused_history(db, conversation_id, ordinal)


async def mark_run_messages_refused(db: AsyncSession, *, run_id: UUID) -> None:
    """Mark the run's rows and fence summaries built before its verdict."""
    await _mark_refused(db, Message.run_id == run_id)


async def message_refusal(
    db: AsyncSession, *, message_id: UUID, conversation_id: UUID
) -> bool | None:
    """Read a source verdict freshly; None means the exact source no longer exists."""
    return await db.scalar(
        select(Message.guardrail_refused).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
    )


async def mark_message_refused(
    db: AsyncSession, *, message_id: UUID, conversation_id: UUID
) -> None:
    """Record a workflow refusal on its exact source and fence summaries covering it."""
    await _mark_refused(
        db,
        and_(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.role == "user",
        ),
    )


async def set_attachment_context(
    db: AsyncSession, *, message_id: UUID, conversation_id: UUID, context: str | None
) -> None:
    """Record what a prompt's attachments added for the model - see `Message.attachment_context`.

    Written after the prompt row, because where a file goes depends on whether
    the agent has a workspace and that is known only once the run is prepared.
    Narrowed by `conversation_id` for the reason `link_message_to_run` is.
    `None` takes it back off a turn a guardrail refused (#2578).
    """
    await db.execute(
        sql_update(Message)
        .where(Message.id == message_id, Message.conversation_id == conversation_id)
        .values(attachment_context=context)
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
    status: str = "running",
    mcp_connection_id: UUID | None = None,
    tool_id: str | None = None,
    presentation_kind: Literal["draft", "generic", "platform"] | None = None,
) -> ToolCall:
    """Create a new tool call record.

    `status` is `awaiting_approval` for a call the run parked on: the parked
    state otherwise lives only on `agent_runs` and the `approvals` rows, so a
    reloaded conversation read the one call somebody has to decide about as a
    step that ran (#601). `complete_tool_call` closes the row whichever way the
    call ends - a resume, a rejection replayed, or an expiry.
    """
    tool_call = ToolCall(
        message_id=message_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args=args,
        started_at=started_at,
        status=status,
        mcp_connection_id=mcp_connection_id,
        tool_id=tool_id,
        presentation_kind=presentation_kind,
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


async def prompt_for_answer(db: AsyncSession, message: Message) -> str:
    """The prompt of this run, never a different person's interleaved question."""
    result = await db.execute(
        select(Message.content)
        .where(
            Message.run_id == message.run_id,
            Message.conversation_id == message.conversation_id,
            Message.role == "user",
            Message.ordinal < message.ordinal,
        )
        .order_by(Message.ordinal.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or ""


async def store_next_steps(
    db: AsyncSession, *, message_id: UUID, organization_id: UUID, steps: list[str]
) -> bool:
    """Append one persisted synthetic call, scoped and locked against duplicate completion."""
    import json

    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.id == message_id,
            Conversation.organization_id == organization_id,
            Conversation.is_archived.is_(False),
        )
        .with_for_update(of=Message)
        .execution_options(populate_existing=True)
    )
    message = result.scalar_one_or_none()
    if message is None:
        return False
    call_id = f"next_steps_{message_id}"
    found = await db.execute(
        select(ToolCall.id).where(
            ToolCall.message_id == message_id, ToolCall.tool_call_id == call_id
        )
    )
    if found.scalar_one_or_none() is not None:
        return False
    now = datetime.now(UTC)
    call = await create_tool_call(
        db,
        message_id=message_id,
        tool_call_id=call_id,
        tool_name="suggest_next_steps",
        args={"steps": steps},
        started_at=now,
    )
    await complete_tool_call(
        db,
        db_tool_call=call,
        result=json.dumps({"steps": steps}, ensure_ascii=False),
        completed_at=now,
    )
    if message.parts is not None:
        message.parts = [*message.parts, {"type": "tool", "tool_call_id": call_id}]
        await db.flush()
    return True


async def last_answer_message(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> Message | None:
    """The latest saved answer of this tenant's run, regardless of transcript length."""
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.run_id == run_id,
            Message.role == "assistant",
            Conversation.organization_id == organization_id,
        )
        .order_by(Message.ordinal.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
