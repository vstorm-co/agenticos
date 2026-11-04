"""Suggestions the platform made to a person, and what they decided (#2301)."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.suggestion import (
    RoutineFindingRevision,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
)


async def propose(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    kind: str,
    title: str,
    detail: str | None,
    payload: dict[str, Any],
    dedupe_key: str,
    watch_id: UUID | None = None,
    urgent: bool = False,
) -> Suggestion | None:
    """Record a proposal unless this person was already offered the same one.

    Returns the new row, or `None` when the key was taken - by an open proposal,
    one they accepted, or one they dismissed. One statement, so two sweeps that
    overlap cannot both propose it.
    """
    suggestion_id = uuid.uuid4()
    result = await db.execute(
        insert(Suggestion)
        .values(
            id=suggestion_id,
            organization_id=organization_id,
            user_id=user_id,
            kind=kind,
            title=title,
            detail=detail,
            payload=payload,
            dedupe_key=dedupe_key,
            status=SuggestionStatus.OPEN.value,
            watch_id=watch_id,
            urgent=urgent,
        )
        .on_conflict_do_nothing(constraint="uq_suggestion_person_key")
        .returning(Suggestion.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await db.get(Suggestion, suggestion_id)


async def list_open(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> list[Suggestion]:
    """This person's open proposals here, newest first."""
    result = await db.execute(
        select(Suggestion)
        .where(
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.status == SuggestionStatus.OPEN.value,
        )
        .order_by(Suggestion.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, limit: int
) -> list[Suggestion]:
    """Every proposal this person was made here, whatever they answered, newest first."""
    result = await db.execute(
        select(Suggestion)
        .where(Suggestion.organization_id == organization_id, Suggestion.user_id == user_id)
        .order_by(Suggestion.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def reopen(db: AsyncSession, *, suggestion: Suggestion) -> Suggestion:
    """Take a decision back: the proposal waits again."""
    suggestion.status = SuggestionStatus.OPEN.value
    suggestion.decided_at = None
    await db.flush()
    await db.refresh(suggestion)
    return suggestion


async def keys_for(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> set[str]:
    """Every proposal key this person was ever offered here - what a sweep must not repeat."""
    result = await db.execute(
        select(Suggestion.dedupe_key).where(
            Suggestion.organization_id == organization_id, Suggestion.user_id == user_id
        )
    )
    return set(result.scalars().all())


async def get_own(
    db: AsyncSession, suggestion_id: UUID, *, organization_id: UUID, user_id: UUID
) -> Suggestion | None:
    """One proposal, only if it was made to this person in this organization."""
    result = await db.execute(
        select(Suggestion).where(
            Suggestion.id == suggestion_id,
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def decide(
    db: AsyncSession, *, suggestion: Suggestion, status: SuggestionStatus
) -> Suggestion:
    suggestion.status = status.value
    suggestion.decided_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(suggestion)
    return suggestion


async def titles_for_watch(db: AsyncSession, *, watch_id: UUID, limit: int) -> list[str]:
    """What a watch reported lately, newest first - so its next look does not say it again."""
    result = await db.execute(
        select(Suggestion.title)
        .where(Suggestion.watch_id == watch_id)
        .order_by(Suggestion.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def open_findings_by_watch(db: AsyncSession, *, watch_ids: list[UUID]) -> dict[UUID, int]:
    """How many of each watch's findings still wait for their person; a watch with none is absent."""
    if not watch_ids:
        return {}
    result = await db.execute(
        select(Suggestion.watch_id, func.count())
        .where(
            Suggestion.watch_id.in_(watch_ids),
            Suggestion.status == SuggestionStatus.OPEN.value,
        )
        .group_by(Suggestion.watch_id)
    )
    return {watch_id: count for watch_id, count in result.tuples().all() if watch_id is not None}


async def unbriefed_findings(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[Suggestion]:
    """Open findings that were not sent at once and are in no briefing yet, newest first."""
    result = await db.execute(
        select(Suggestion)
        .where(
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.kind == SuggestionKind.FINDING.value,
            Suggestion.status == SuggestionStatus.OPEN.value,
            Suggestion.urgent.is_(False),
            Suggestion.briefed_at.is_(None),
            or_(Suggestion.outcome_id.is_(None), Suggestion.outcome_status == "open"),
        )
        .order_by(Suggestion.created_at.desc())
    )
    return list(result.scalars().all())


async def mark_briefed(db: AsyncSession, *, suggestion_ids: list[UUID], at: datetime) -> None:
    """Record the briefing these findings went out in, so the next one does not repeat them."""
    await db.execute(
        update(Suggestion).where(Suggestion.id.in_(suggestion_ids)).values(briefed_at=at)
    )


async def link_outcome(db: AsyncSession, *, suggestion: Suggestion, outcome_id: UUID) -> None:
    suggestion.outcome_id = outcome_id
    await db.flush()
    await db.refresh(suggestion)


async def project_outcome_status(
    db: AsyncSession,
    *,
    outcome_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    status: SuggestionStatus,
    at: datetime,
) -> None:
    """Keep the Inbox/dedupe projection in the outcome's own transaction."""
    await db.execute(
        update(Suggestion)
        .where(
            Suggestion.outcome_id == outcome_id,
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.kind == SuggestionKind.FINDING.value,
            Suggestion.status == SuggestionStatus.OPEN.value,
        )
        .values(status=status.value, decided_at=at)
    )


async def for_key(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, dedupe_key: str
) -> Suggestion | None:
    return await db.scalar(
        select(Suggestion).where(
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.dedupe_key == dedupe_key,
        )
    )


async def claim_finding_revision(db: AsyncSession, *, finding_id: UUID, revision: str) -> bool:
    result = await db.execute(
        insert(RoutineFindingRevision)
        .values(finding_id=finding_id, revision_hash=hashlib.sha256(revision.encode()).hexdigest())
        .on_conflict_do_nothing()
        .returning(RoutineFindingRevision.finding_id)
    )
    return result.scalar_one_or_none() is not None


async def finding_sources(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_ids: list[UUID]
) -> dict[UUID, dict[str, object]]:
    result = await db.execute(
        select(Suggestion.outcome_id, Suggestion.payload).where(
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.outcome_id.in_(outcome_ids),
            Suggestion.kind == SuggestionKind.FINDING.value,
        )
    )
    return {
        identifier: dict(payload) for identifier, payload in result.all() if identifier is not None
    }
