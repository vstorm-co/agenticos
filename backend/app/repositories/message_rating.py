"""Message rating repository for database operations."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, delete, func, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.db.models.group import Group, GroupMember
from app.db.models.message_rating import MessageRating


async def get_rating_by_message_and_user(
    db: AsyncSession,
    message_id: UUID,
    user_id: UUID,
) -> MessageRating | None:
    """Get a user's rating for a specific message."""
    query = select(MessageRating).where(
        MessageRating.message_id == message_id,
        MessageRating.user_id == user_id,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_rating(
    db: AsyncSession,
    *,
    message_id: UUID,
    user_id: UUID,
    rating: int,
    comment: str | None = None,
) -> MessageRating:
    """Create a new rating.

    Note: The unique constraint on (message_id, user_id) prevents duplicates
    at the database level. Callers should handle IntegrityError.
    """
    rating_obj = MessageRating(
        message_id=message_id,
        user_id=user_id,
        rating=rating,
        comment=comment,
    )
    db.add(rating_obj)
    await db.flush()
    await db.refresh(rating_obj)
    return rating_obj


async def upsert_channel_rating(
    db: AsyncSession,
    *,
    message_id: UUID,
    channel_identity_id: UUID,
    rating: int | None,
    comment: str | None = None,
) -> MessageRating:
    """One verified channel participant's vote, atomically inserted or changed.

    A later comment preserves the verdict; a repeated vote preserves its comment.
    Unlinked participants use their channel identity. Linked participants share
    the same author key as the console; the identity lock serializes linking
    with a vote so an anonymous vote cannot land after its transfer.
    """
    identity = (
        await db.execute(
            select(ChannelIdentity)
            .where(ChannelIdentity.id == channel_identity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    linked = identity.user_id is not None
    statement = pg_insert(MessageRating).values(
        message_id=message_id,
        user_id=identity.user_id,
        channel_identity_id=None if linked else channel_identity_id,
        rating=-1 if rating is None else rating,
        comment=comment,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_message_user_rating" if linked else "uq_message_channel_rating",
        set_={
            "rating": MessageRating.rating if rating is None else statement.excluded.rating,
            "comment": MessageRating.comment if comment is None else statement.excluded.comment,
            "updated_at": func.now(),
        },
    ).returning(MessageRating)
    result = await db.execute(statement.execution_options(populate_existing=True))
    return result.scalar_one()


async def adopt_channel_ratings(db: AsyncSession, *, identity_id: UUID, user_id: UUID) -> None:
    """Transfer earlier channel votes in the account-link transaction.

    Lock the identity in the same order as channel writes. A web vote may already
    exist; keep whichever opinion was changed most recently rather than counting
    the person twice. Unlinking later leaves these authenticated votes with their
    owner, just like votes originally cast in the console.
    """
    await db.execute(
        select(ChannelIdentity.id).where(ChannelIdentity.id == identity_id).with_for_update()
    )
    ratings = (
        (
            await db.execute(
                select(MessageRating)
                .where(MessageRating.channel_identity_id == identity_id)
                .order_by(MessageRating.message_id)
            )
        )
        .scalars()
        .all()
    )
    for rating in ratings:
        statement = pg_insert(MessageRating).values(
            message_id=rating.message_id,
            user_id=user_id,
            rating=rating.rating,
            comment=rating.comment,
            created_at=rating.created_at,
            updated_at=rating.updated_at,
        )
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_message_user_rating",
                set_={
                    "rating": statement.excluded.rating,
                    "comment": statement.excluded.comment,
                    "updated_at": statement.excluded.updated_at,
                },
                where=func.coalesce(MessageRating.updated_at, MessageRating.created_at)
                <= func.coalesce(statement.excluded.updated_at, statement.excluded.created_at),
            )
        )
    await db.execute(delete(MessageRating).where(MessageRating.channel_identity_id == identity_id))


async def update_rating(
    db: AsyncSession,
    rating: MessageRating,
    *,
    new_rating: int,
    comment: str | None = None,
) -> MessageRating:
    """Update an existing rating."""
    rating.rating = new_rating
    rating.comment = comment
    await db.flush()
    await db.refresh(rating)
    return rating


async def delete_rating(db: AsyncSession, rating: MessageRating) -> None:
    """Delete a rating."""
    await db.delete(rating)
    await db.flush()


async def get_user_ratings_for_messages(
    db: AsyncSession,
    *,
    message_ids: list[UUID],
    user_id: UUID,
) -> dict[UUID, int]:
    """Return mapping of message_id → rating value for a single user."""
    if not message_ids:
        return {}
    query = select(MessageRating).where(
        MessageRating.message_id.in_(message_ids),
        MessageRating.user_id == user_id,
    )
    result = await db.execute(query)
    return {rating.message_id: rating.rating for rating in result.scalars().all()}


async def get_rating_counts_for_messages(
    db: AsyncSession,
    *,
    message_ids: list[UUID],
) -> dict[UUID, dict[str, int]]:
    """Return mapping of message_id → {likes, dislikes} counts."""
    if not message_ids:
        return {}
    query = (
        select(
            MessageRating.message_id,
            func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
            func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
        )
        .where(MessageRating.message_id.in_(message_ids))
        .group_by(MessageRating.message_id)
    )
    result = await db.execute(query)
    return {
        row.message_id: {"likes": row.likes or 0, "dislikes": row.dislikes or 0}
        for row in result.all()
    }


async def get_down_rating_comments_for_messages(
    db: AsyncSession,
    *,
    message_ids: list[UUID],
) -> dict[UUID, str]:
    """Return mapping of message_id → the most recent down rating's comment.

    Only down ratings (`rating == -1`) that carry a comment, newest first, so a
    message maps to the latest word left objecting to it. A message nobody
    down-rated, or down-rated without leaving a comment, is simply absent - the
    caller reads that as "no comment to show" rather than an empty string.
    """
    if not message_ids:
        return {}
    query = (
        select(MessageRating.message_id, MessageRating.comment)
        .where(
            MessageRating.message_id.in_(message_ids),
            MessageRating.rating == -1,
            MessageRating.comment.is_not(None),
        )
        .order_by(MessageRating.created_at.desc())
    )
    result = await db.execute(query)
    comments: dict[UUID, str] = {}
    for message_id, comment in result.all():
        # Newest first, so the first comment seen for a message is its latest.
        if message_id not in comments and comment:
            comments[message_id] = comment
    return comments


async def list_ratings(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
    rating_filter: int | None = None,  # 1 or -1 to filter
    with_comments_only: bool = False,
) -> tuple[list[MessageRating], int]:
    """List ratings with optional filters."""
    query = select(MessageRating)

    if rating_filter is not None:
        query = query.where(MessageRating.rating == rating_filter)

    if with_comments_only:
        query = query.where(MessageRating.comment.isnot(None), MessageRating.comment != "")

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    query = query.order_by(MessageRating.created_at.desc()).offset(skip).limit(limit)

    query = query.options(
        selectinload(MessageRating.message),
        selectinload(MessageRating.user),
    )

    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def _by_surface(
    db: AsyncSession, conditions: Sequence[ColumnElement[bool]], *, scoped: bool
) -> list[dict[str, Any]]:
    """Likes and dislikes per surface the rated answer was given on (#2084).

    Read off the run that produced the message; an answer with no run - a
    console turn from before runs were recorded - counts as the web chat.
    """
    surface = func.coalesce(AgentRun.surface, RunSurface.WEB.value)
    query = (
        select(
            surface.label("surface"),
            func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
            func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
        )
        .join(Message, Message.id == MessageRating.message_id)
        .outerjoin(AgentRun, AgentRun.id == Message.run_id)
    )
    if scoped:
        query = query.join(Conversation, Conversation.id == Message.conversation_id)
    query = query.where(*conditions).group_by(surface).order_by(surface)
    return [
        {"surface": row.surface, "likes": row.likes or 0, "dislikes": row.dislikes or 0}
        for row in await db.execute(query)
    ]


async def get_rating_summary(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Aggregated rating statistics across every organization.

    A half-open window rather than a trailing day count, because the question
    the dashboard asks is often about a period that has already ended - "last
    month" cannot be said as a number of days back from now. Days bucket in
    UTC, as they do in `get_rating_summary_scoped`, so the deployment-wide
    chart and an organization's chart put the same rating on the same day.
    """
    conditions = [MessageRating.created_at >= start, MessageRating.created_at < end]

    counts_query = select(
        func.count().label("total"),
        func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
        func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
        func.avg(MessageRating.rating).label("avg_rating"),
        func.sum(
            case((and_(MessageRating.comment.isnot(None), MessageRating.comment != ""), 1), else_=0)
        ).label("with_comments"),
    ).where(*conditions)

    result = await db.execute(counts_query)
    row = result.one()

    day = func.date(func.timezone("UTC", MessageRating.created_at))
    daily_query = (
        select(
            day.label("date"),
            func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
            func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
        )
        .where(*conditions)
        .group_by(day)
        .order_by(day)
    )

    ratings_by_day = [
        {"date": str(entry.date), "likes": entry.likes or 0, "dislikes": entry.dislikes or 0}
        for entry in await db.execute(daily_query)
    ]

    return {
        "total_ratings": row.total or 0,
        "like_count": row.likes or 0,
        "dislike_count": row.dislikes or 0,
        "average_rating": float(row.avg_rating) if row.avg_rating else 0.0,
        "with_comments": row.with_comments or 0,
        "ratings_by_day": ratings_by_day,
        "ratings_by_surface": await _by_surface(db, conditions, scoped=False),
    }


async def get_rating_summary_scoped(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """The summary's shape, bounded to one organization's conversations.

    Ratings carry no organization of their own, so the tenant bound is a
    two-hop join: rating -> message -> conversation. `user_id` narrows to the
    caller's own: their conversations, and the answers they rated in a chat
    channel, whose conversation belongs to nobody (#2084).
    """
    conditions = [
        Conversation.organization_id == organization_id,
        MessageRating.created_at >= start,
        MessageRating.created_at < end,
    ]
    if user_id is not None:
        conditions.append(
            or_(
                Conversation.user_id == user_id,
                MessageRating.user_id == user_id,
                MessageRating.channel_identity_id.in_(
                    select(ChannelIdentity.id).where(ChannelIdentity.user_id == user_id)
                ),
            )
        )

    counts_query = (
        select(
            func.count().label("total"),
            func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
            func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
            func.avg(MessageRating.rating).label("avg_rating"),
            func.sum(
                case(
                    (and_(MessageRating.comment.isnot(None), MessageRating.comment != ""), 1),
                    else_=0,
                )
            ).label("with_comments"),
        )
        .join(Message, Message.id == MessageRating.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(*conditions)
    )
    row = (await db.execute(counts_query)).one()

    day = func.date(func.timezone("UTC", MessageRating.created_at))
    daily_query = (
        select(
            day.label("date"),
            func.sum(case((MessageRating.rating == 1, 1), else_=0)).label("likes"),
            func.sum(case((MessageRating.rating == -1, 1), else_=0)).label("dislikes"),
        )
        .join(Message, Message.id == MessageRating.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(*conditions)
        .group_by(day)
        .order_by(day)
    )
    ratings_by_day = [
        {"date": str(entry.date), "likes": entry.likes or 0, "dislikes": entry.dislikes or 0}
        for entry in await db.execute(daily_query)
    ]

    return {
        "total_ratings": row.total or 0,
        "like_count": row.likes or 0,
        "dislike_count": row.dislikes or 0,
        "average_rating": float(row.avg_rating) if row.avg_rating else 0.0,
        "with_comments": row.with_comments or 0,
        "ratings_by_day": ratings_by_day,
        "ratings_by_surface": await _by_surface(db, conditions, scoped=True),
    }


async def rating_counts_by_version(
    db: AsyncSession,
    *,
    version_ids: Sequence[UUID],
    start: datetime,
    end: datetime,
) -> dict[UUID, tuple[int, int]]:
    """(likes, total) per agent version, over ratings given in the window.

    Joined through the message rather than the run: `Message.agent_version_id`
    records which frozen spec produced the words a thumb was given to. The
    caller supplies the version ids it is comparing, which is also the tenant
    bound - version ids come off that organization's own version rows.
    """
    # The `in_` filter excludes a null version, which the nullable column cannot
    # say by itself - `type_coerce` does.
    result = await db.execute(
        select(
            type_coerce(Message.agent_version_id, PG_UUID(as_uuid=True)),
            func.sum(case((MessageRating.rating == 1, 1), else_=0)),
            func.count(MessageRating.id),
        )
        .join(Message, Message.id == MessageRating.message_id)
        .where(
            Message.agent_version_id.in_(version_ids),
            MessageRating.created_at >= start,
            MessageRating.created_at < end,
        )
        .group_by(Message.agent_version_id)
    )
    return {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in result.all()}


async def ratings_by_group(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    group_id: UUID | None = None,
) -> list[tuple[UUID, int, int]]:
    """How each department's people rated answers in a window (#2101).

    Returns (group_id, likes, dislikes) rows, only for departments whose members
    rated something. A rating counts for the department of whoever gave it - the
    question is how well agents answer *its* people - and for every department
    that person is in, so the rows are not a partition. Bounded to the
    organization through the rated message's conversation, as every rating read
    is.
    """
    conditions = [
        Group.organization_id == organization_id,
        Conversation.organization_id == organization_id,
        MessageRating.created_at >= start,
        MessageRating.created_at < end,
    ]
    if group_id is not None:
        conditions.append(GroupMember.group_id == group_id)
    result = await db.execute(
        select(
            GroupMember.group_id,
            func.sum(case((MessageRating.rating > 0, 1), else_=0)),
            func.sum(case((MessageRating.rating < 0, 1), else_=0)),
        )
        .outerjoin(ChannelIdentity, ChannelIdentity.id == MessageRating.channel_identity_id)
        .join(
            GroupMember,
            GroupMember.user_id == func.coalesce(MessageRating.user_id, ChannelIdentity.user_id),
        )
        .join(Group, Group.id == GroupMember.group_id)
        .join(Message, Message.id == MessageRating.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(*conditions)
        .group_by(GroupMember.group_id)
    )
    return [(group, int(likes), int(dislikes)) for group, likes, dislikes in result.all()]


async def group_down_rated(
    db: AsyncSession,
    *,
    organization_id: UUID,
    group_id: UUID,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[tuple[datetime, str | None, UUID | None, UUID | None, str | None]]:
    """The latest answers a department's people rated down, newest first (#2101).

    Returns (rated_at, comment, run_id, agent_id, agent_name) rows. The run and
    agent are absent for an answer from before messages named their run. What
    was asked and answered is not read - the run holds it, behind its own gate.
    """
    result = await db.execute(
        select(
            MessageRating.created_at,
            MessageRating.comment,
            AgentRun.id,
            Agent.id,
            Agent.name,
        )
        .outerjoin(ChannelIdentity, ChannelIdentity.id == MessageRating.channel_identity_id)
        .join(
            GroupMember,
            GroupMember.user_id == func.coalesce(MessageRating.user_id, ChannelIdentity.user_id),
        )
        .join(Message, Message.id == MessageRating.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(AgentRun, AgentRun.id == Message.run_id)
        .outerjoin(Agent, Agent.id == AgentRun.agent_id)
        .where(
            GroupMember.group_id == group_id,
            Conversation.organization_id == organization_id,
            MessageRating.rating < 0,
            MessageRating.created_at >= start,
            MessageRating.created_at < end,
        )
        .order_by(MessageRating.created_at.desc())
        .limit(limit)
    )
    return [
        (rated_at, comment, run_id, agent_id, agent_name)
        for rated_at, comment, run_id, agent_id, agent_name in result.all()
    ]
