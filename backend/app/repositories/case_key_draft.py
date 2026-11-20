"""Keys drafted from a case's reference answer - one draft per case."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.case_key_draft import CaseKeyDraft, KeyDraftStatus


async def get_for_case(
    db: AsyncSession, *, organization_id: UUID, dataset_id: UUID, case_id: UUID
) -> CaseKeyDraft | None:
    return await db.scalar(
        select(CaseKeyDraft).where(
            CaseKeyDraft.organization_id == organization_id,
            CaseKeyDraft.dataset_id == dataset_id,
            CaseKeyDraft.case_id == case_id,
        )
    )


async def get(db: AsyncSession, draft_id: UUID, *, organization_id: UUID) -> CaseKeyDraft | None:
    return await db.scalar(
        select(CaseKeyDraft).where(
            CaseKeyDraft.id == draft_id, CaseKeyDraft.organization_id == organization_id
        )
    )


async def replace(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    case_id: UUID,
    revision_id: UUID,
    requested_by_user_id: UUID | None,
    created_by_api_key_id: UUID | None,
) -> CaseKeyDraft:
    """A new running draft for a case, in place of the one it had."""
    await delete_for_case(
        db, organization_id=organization_id, dataset_id=dataset_id, case_id=case_id
    )
    draft = CaseKeyDraft(
        organization_id=organization_id,
        dataset_id=dataset_id,
        case_id=case_id,
        revision_id=revision_id,
        requested_by_user_id=requested_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        status=KeyDraftStatus.RUNNING.value,
        keys=[],
    )
    db.add(draft)
    await db.flush()
    await db.refresh(draft)
    return draft


async def finish(
    db: AsyncSession,
    draft: CaseKeyDraft,
    *,
    status: KeyDraftStatus,
    finished_at: datetime,
    keys: Sequence[dict[str, str]] = (),
    error: str | None = None,
    run_id: UUID | None = None,
) -> CaseKeyDraft:
    draft.status = status.value
    draft.keys = [dict(key) for key in keys]
    draft.error = error
    draft.run_id = run_id
    draft.finished_at = finished_at
    await db.flush()
    await db.refresh(draft)
    return draft


async def delete_for_case(
    db: AsyncSession, *, organization_id: UUID, dataset_id: UUID, case_id: UUID
) -> int:
    result = await db.execute(
        delete(CaseKeyDraft)
        .where(
            CaseKeyDraft.organization_id == organization_id,
            CaseKeyDraft.dataset_id == dataset_id,
            CaseKeyDraft.case_id == case_id,
        )
        .returning(CaseKeyDraft.id)
    )
    deleted = len(result.scalars().all())
    await db.flush()
    return deleted
