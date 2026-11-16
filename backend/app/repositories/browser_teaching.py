"""Tenant-scoped teaching persistence. Services own transitions and transaction commits."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models.browser_teaching import (
    BrowserTeachingPolicy,
    BrowserTeachingPreference,
    BrowserTeachingSession,
)
from app.db.models.organization import Organization
from app.db.models.skill_proposal import SkillProposal


async def lock_organization(db: AsyncSession, organization_id: UUID) -> None:
    await db.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )


async def policy(
    db: AsyncSession, organization_id: UUID, *, locked: bool = False
) -> BrowserTeachingPolicy | None:
    statement = select(BrowserTeachingPolicy).where(
        BrowserTeachingPolicy.organization_id == organization_id
    )
    if locked:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement.execution_options(populate_existing=True))


async def preference(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    *,
    locked: bool = False,
) -> BrowserTeachingPreference | None:
    statement = select(BrowserTeachingPreference).where(
        BrowserTeachingPreference.organization_id == organization_id,
        BrowserTeachingPreference.user_id == user_id,
        BrowserTeachingPreference.agent_id == agent_id,
    )
    if locked:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement.execution_options(populate_existing=True))


async def session(
    db: AsyncSession, organization_id: UUID, session_id: UUID, *, locked: bool = False
) -> BrowserTeachingSession | None:
    statement = select(BrowserTeachingSession).where(
        BrowserTeachingSession.organization_id == organization_id,
        BrowserTeachingSession.id == session_id,
    )
    if locked:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement.execution_options(populate_existing=True))


async def active(
    db: AsyncSession, organization_id: UUID, controller_id: UUID
) -> BrowserTeachingSession | None:
    return await db.scalar(
        select(BrowserTeachingSession)
        .where(
            BrowserTeachingSession.organization_id == organization_id,
            BrowserTeachingSession.controller_id == controller_id,
            BrowserTeachingSession.status.in_(("recording", "paused")),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def owned_page(
    db: AsyncSession,
    organization_id: UUID,
    owner_user_id: UUID,
    *,
    limit: int,
    before: tuple[datetime, UUID] | None,
) -> list[BrowserTeachingSession]:
    """Read one bounded metadata page without loading captured material or locking rows."""
    row = BrowserTeachingSession
    statement = (
        select(row)
        .where(row.organization_id == organization_id, row.owner_user_id == owner_user_id)
        .options(
            load_only(
                row.id,
                row.agent_id,
                row.target_skill_id,
                row.title,
                row.allowed_origins,
                row.source,
                row.verified_success,
                row.status,
                row.revision,
                row.reason_code,
                row.generation_state,
                row.proposal_id,
                row.created_at,
                row.expires_at,
                row.capture_ends_at,
                raiseload=True,
            )
        )
    )
    if before is not None:
        statement = statement.where(tuple_(row.created_at, row.id) < before)
    rows = await db.scalars(
        statement.order_by(row.created_at.desc(), row.id.desc())
        .limit(limit + 1)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def owner_open_count(db: AsyncSession, organization_id: UUID, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(BrowserTeachingSession.id)).where(
                BrowserTeachingSession.organization_id == organization_id,
                BrowserTeachingSession.owner_user_id == user_id,
                BrowserTeachingSession.status.in_(("recording", "paused", "review")),
            )
        )
        or 0
    )


async def create(db: AsyncSession, row: BrowserTeachingSession) -> BrowserTeachingSession:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def cancellation_candidates(
    db: AsyncSession,
    organization_id: UUID,
    *,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    refinements_only: bool = False,
) -> list[BrowserTeachingSession]:
    statement = select(BrowserTeachingSession).where(
        BrowserTeachingSession.organization_id == organization_id,
        BrowserTeachingSession.status.in_(("recording", "paused", "review")),
    )
    if user_id is not None:
        statement = statement.where(BrowserTeachingSession.owner_user_id == user_id)
    if agent_id is not None:
        statement = statement.where(BrowserTeachingSession.agent_id == agent_id)
    if refinements_only:
        statement = statement.where(BrowserTeachingSession.source == "refinement")
    rows = await db.scalars(
        statement.order_by(BrowserTeachingSession.id)
        .limit(500)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def sweep_candidates(
    db: AsyncSession, now: datetime, generation_before: datetime
) -> list[tuple[UUID, UUID]]:
    rows = await db.execute(
        select(BrowserTeachingSession.organization_id, BrowserTeachingSession.id)
        .where(
            or_(
                (BrowserTeachingSession.expires_at <= now)
                & BrowserTeachingSession.status.in_(("recording", "paused", "review")),
                (BrowserTeachingSession.status == "proposed")
                & (func.jsonb_array_length(BrowserTeachingSession.sanitized_events) > 0),
                (BrowserTeachingSession.generation_state == "generating")
                & (BrowserTeachingSession.generation_started_at <= generation_before),
                BrowserTeachingSession.status == "recording",
                BrowserTeachingSession.generation_state == "queued",
                (BrowserTeachingSession.source == "refinement")
                & (BrowserTeachingSession.status == "review")
                & ~BrowserTeachingSession.verified_success,
            )
        )
        .order_by(BrowserTeachingSession.updated_at, BrowserTeachingSession.id)
        .limit(100)
    )
    return [(row[0], row[1]) for row in rows]


async def proposal_for_source(
    db: AsyncSession, organization_id: UUID, session_id: UUID
) -> SkillProposal | None:
    return await db.scalar(
        select(SkillProposal).where(
            SkillProposal.organization_id == organization_id,
            SkillProposal.source == "browser_teaching",
            SkillProposal.browser_procedure["source_session_id"].astext == str(session_id),
        )
    )


async def create_proposal(db: AsyncSession, row: SkillProposal) -> None:
    db.add(row)
    await db.flush()
    await db.refresh(row)


async def erase_decided(db: AsyncSession, organization_id: UUID, proposal_id: UUID) -> None:
    """The existing proposal decision commits its transient teaching erasure atomically."""
    await db.execute(
        update(BrowserTeachingSession)
        .where(
            BrowserTeachingSession.organization_id == organization_id,
            BrowserTeachingSession.proposal_id == proposal_id,
            BrowserTeachingSession.status == "proposed",
        )
        .values(sanitized_events=[], review=None, procedure=None, title="", allowed_origins=[])
    )
