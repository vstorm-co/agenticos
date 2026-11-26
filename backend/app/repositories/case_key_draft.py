"""Keys drafted from a case's reference answer - one draft per case.

The key extractor's run kept the reference answer in its manifest, so every way a
draft is deleted forgets that run in the same transaction: the run outlives its
draft only as its cost.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.case_key_draft import CaseKeyDraft, KeyDraftStatus
from app.repositories.personal_data import forget_runs


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
    draft_id: UUID,
    *,
    organization_id: UUID,
    status: KeyDraftStatus,
    finished_at: datetime,
    keys: Sequence[dict[str, str]] = (),
    error: str | None = None,
    run_id: UUID | None = None,
) -> bool:
    """End a draft that is still running. Answers whether it was.

    A draft replaced, dismissed, anonymised or expired while its job ran is gone;
    the run the job made is forgotten then, as the deletion would have done.
    """
    ended = await db.scalar(
        update(CaseKeyDraft)
        .where(
            CaseKeyDraft.id == draft_id,
            CaseKeyDraft.organization_id == organization_id,
            CaseKeyDraft.status == KeyDraftStatus.RUNNING.value,
        )
        .values(
            status=status.value,
            keys=[dict(key) for key in keys],
            error=error,
            run_id=run_id,
            finished_at=finished_at,
        )
        .returning(CaseKeyDraft.id)
    )
    if ended is None and run_id is not None:
        await forget_runs(db, [run_id])
    await db.flush()
    return ended is not None


async def delete_for_case(
    db: AsyncSession, *, organization_id: UUID, dataset_id: UUID, case_id: UUID
) -> int:
    return await _deleted(
        db,
        CaseKeyDraft.organization_id == organization_id,
        CaseKeyDraft.dataset_id == dataset_id,
        CaseKeyDraft.case_id == case_id,
    )


async def delete_for_dataset(db: AsyncSession, *, organization_id: UUID, dataset_id: UUID) -> int:
    """Every draft of a dataset, before the dataset goes and would take them unforgotten."""
    return await _deleted(
        db,
        CaseKeyDraft.organization_id == organization_id,
        CaseKeyDraft.dataset_id == dataset_id,
    )


async def delete_expired(db: AsyncSession, *, created_before: datetime) -> int:
    """Every organization's drafts requested before `created_before` - the daily expiry."""
    return await _deleted(db, CaseKeyDraft.created_at < created_before)


async def _deleted(db: AsyncSession, *where: ColumnElement[bool]) -> int:
    result = await db.execute(
        delete(CaseKeyDraft).where(*where).returning(CaseKeyDraft.id, CaseKeyDraft.run_id)
    )
    rows = result.all()
    await forget_runs(db, [run_id for _, run_id in rows if run_id is not None])
    await db.flush()
    return len(rows)
