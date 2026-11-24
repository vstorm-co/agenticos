"""Tenant-scoped teaching persistence. Services own transitions and transaction commits."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models.browser_procedure_teaching import (
    BrowserProcedureTeachingPolicy,
    BrowserProcedureTeachingPreference,
    BrowserProcedureTeachingSession,
)
from app.db.models.organization import Organization
from app.db.models.skill_proposal import SkillProposal


async def lock_organization(db: AsyncSession, organization_id: UUID) -> None:
    await db.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )


async def policy(
    db: AsyncSession, organization_id: UUID, *, locked: bool = False
) -> BrowserProcedureTeachingPolicy | None:
    statement = select(BrowserProcedureTeachingPolicy).where(
        BrowserProcedureTeachingPolicy.organization_id == organization_id
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
) -> BrowserProcedureTeachingPreference | None:
    statement = select(BrowserProcedureTeachingPreference).where(
        BrowserProcedureTeachingPreference.organization_id == organization_id,
        BrowserProcedureTeachingPreference.user_id == user_id,
        BrowserProcedureTeachingPreference.agent_id == agent_id,
    )
    if locked:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement.execution_options(populate_existing=True))


async def session(
    db: AsyncSession, organization_id: UUID, session_id: UUID, *, locked: bool = False
) -> BrowserProcedureTeachingSession | None:
    statement = select(BrowserProcedureTeachingSession).where(
        BrowserProcedureTeachingSession.organization_id == organization_id,
        BrowserProcedureTeachingSession.id == session_id,
    )
    if locked:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement.execution_options(populate_existing=True))


async def active(
    db: AsyncSession, organization_id: UUID, controller_id: UUID
) -> BrowserProcedureTeachingSession | None:
    return await db.scalar(
        select(BrowserProcedureTeachingSession)
        .where(
            BrowserProcedureTeachingSession.organization_id == organization_id,
            BrowserProcedureTeachingSession.controller_id == controller_id,
            BrowserProcedureTeachingSession.status.in_(("recording", "paused")),
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
) -> list[BrowserProcedureTeachingSession]:
    """Read one bounded metadata page without loading captured material or locking rows."""
    row = BrowserProcedureTeachingSession
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
            select(func.count(BrowserProcedureTeachingSession.id)).where(
                BrowserProcedureTeachingSession.organization_id == organization_id,
                BrowserProcedureTeachingSession.owner_user_id == user_id,
                BrowserProcedureTeachingSession.status.in_(("recording", "paused", "review")),
            )
        )
        or 0
    )


async def create(
    db: AsyncSession, row: BrowserProcedureTeachingSession
) -> BrowserProcedureTeachingSession:
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
) -> list[BrowserProcedureTeachingSession]:
    statement = select(BrowserProcedureTeachingSession).where(
        BrowserProcedureTeachingSession.organization_id == organization_id,
        BrowserProcedureTeachingSession.status.in_(("recording", "paused", "review")),
    )
    if user_id is not None:
        statement = statement.where(BrowserProcedureTeachingSession.owner_user_id == user_id)
    if agent_id is not None:
        statement = statement.where(BrowserProcedureTeachingSession.agent_id == agent_id)
    if refinements_only:
        statement = statement.where(BrowserProcedureTeachingSession.source == "refinement")
    rows = await db.scalars(
        statement.order_by(BrowserProcedureTeachingSession.id)
        .limit(500)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def sweep_candidates(
    db: AsyncSession, now: datetime, generation_before: datetime
) -> list[tuple[UUID, UUID]]:
    rows = await db.execute(
        select(BrowserProcedureTeachingSession.organization_id, BrowserProcedureTeachingSession.id)
        .where(
            or_(
                (BrowserProcedureTeachingSession.expires_at <= now)
                & BrowserProcedureTeachingSession.status.in_(("recording", "paused", "review")),
                (BrowserProcedureTeachingSession.status == "proposed")
                & (func.jsonb_array_length(BrowserProcedureTeachingSession.sanitized_events) > 0),
                (BrowserProcedureTeachingSession.generation_state == "generating")
                & (BrowserProcedureTeachingSession.generation_started_at <= generation_before),
                BrowserProcedureTeachingSession.status == "recording",
                BrowserProcedureTeachingSession.generation_state == "queued",
                (BrowserProcedureTeachingSession.source == "refinement")
                & (BrowserProcedureTeachingSession.status == "review")
                & ~BrowserProcedureTeachingSession.verified_success,
            )
        )
        .order_by(BrowserProcedureTeachingSession.updated_at, BrowserProcedureTeachingSession.id)
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
        update(BrowserProcedureTeachingSession)
        .where(
            BrowserProcedureTeachingSession.organization_id == organization_id,
            BrowserProcedureTeachingSession.proposal_id == proposal_id,
            BrowserProcedureTeachingSession.status == "proposed",
        )
        .values(sanitized_events=[], review=None, procedure=None, title="", allowed_origins=[])
    )
