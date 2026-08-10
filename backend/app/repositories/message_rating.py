"""Message rating repository for database operations."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation, Message
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
    caller's own conversations, which is what scope=own means - a rating can
    only ever be given by a conversation's owner, so "my conversations" and
    "ratings I gave" are the same set.
    """
    conditions = [
        Conversation.organization_id == organization_id,
        MessageRating.created_at >= start,
        MessageRating.created_at < end,
    ]
    if user_id is not None:
        conditions.append(Conversation.user_id == user_id)

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
    result = await db.execute(
        select(
            Message.agent_version_id,
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
