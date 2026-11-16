"""Tenant-scoped continuation receipts; the service owns every transaction."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_continuation import ACTIVE_CONTINUATION_STATES
from app.core.browser_session import CredentialGeneration
from app.db.models.browser_credential import BrowserCredentialPlan
from app.db.models.browser_credential_continuation import BrowserCredentialContinuation


async def get(
    db: AsyncSession, organization_id: UUID, continuation_id: UUID, *, locked: bool = False
) -> BrowserCredentialContinuation | None:
    query = select(BrowserCredentialContinuation).where(
        BrowserCredentialContinuation.organization_id == organization_id,
        BrowserCredentialContinuation.id == continuation_id,
    )
    if locked:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def for_submission(
    db: AsyncSession, organization_id: UUID, submission_id: UUID
) -> BrowserCredentialContinuation | None:
    return await db.scalar(
        select(BrowserCredentialContinuation)
        .where(
            BrowserCredentialContinuation.organization_id == organization_id,
            BrowserCredentialContinuation.source_submission_id == submission_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def active_for_view(
    db: AsyncSession, organization_id: UUID, run_id: UUID, call_id: str
) -> BrowserCredentialContinuation | None:
    return await db.scalar(
        select(BrowserCredentialContinuation)
        .where(
            BrowserCredentialContinuation.organization_id == organization_id,
            BrowserCredentialContinuation.run_id == run_id,
            BrowserCredentialContinuation.source_call_id == call_id,
            BrowserCredentialContinuation.state.in_(ACTIVE_CONTINUATION_STATES),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def create(
    db: AsyncSession, row: BrowserCredentialContinuation
) -> BrowserCredentialContinuation:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def contributors(
    db: AsyncSession, organization_id: UUID, run_id: UUID, tab_id: str
) -> list[CredentialGeneration]:
    """Overapproximate taint across every view of this tab, including uncertain writes."""
    rows = await db.execute(
        select(BrowserCredentialPlan.secret_id, BrowserCredentialPlan.authorization_generation)
        .where(
            BrowserCredentialPlan.organization_id == organization_id,
            BrowserCredentialPlan.run_id == run_id,
            BrowserCredentialPlan.tab_id == tab_id,
            BrowserCredentialPlan.output_protected.is_(True),
            BrowserCredentialPlan.attempt_id.is_not(None),
            BrowserCredentialPlan.state.in_(("claimed", "filled", "submitted", "unknown")),
        )
        .distinct()
        .limit(51)
    )
    return [
        CredentialGeneration(secret_id=secret_id, authorization_generation=generation)
        for secret_id, generation in rows
    ]
