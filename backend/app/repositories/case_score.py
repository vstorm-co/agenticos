"""Case score repository (PostgreSQL async).

`organization_id` is a required keyword on every read: a score quotes an answer,
and a forgotten tenant filter must not look like an ordinary call (see
tests/test_org_scope_regression.py).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset
from app.repositories._visibility import visible_to_caller


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    case_revision_id: UUID,
    case_id: UUID,
    run_id: UUID | None,
    scoring: dict[str, Any],
    results: list[dict[str, Any]],
    passed: bool | None,
    review_state: str,
    created_by_user_id: UUID | None,
) -> CaseScore:
    score = CaseScore(
        organization_id=organization_id,
        dataset_id=dataset_id,
        case_revision_id=case_revision_id,
        case_id=case_id,
        run_id=run_id,
        scoring=scoring,
        results=results,
        passed=passed,
        review_state=review_state,
        created_by_user_id=created_by_user_id,
    )
    db.add(score)
    await db.flush()
    await db.refresh(score)
    return score


async def get(
    db: AsyncSession, score_id: UUID, *, organization_id: UUID, dataset_id: UUID
) -> CaseScore | None:
    result = await db.execute(
        select(CaseScore).where(
            CaseScore.id == score_id,
            CaseScore.organization_id == organization_id,
            CaseScore.dataset_id == dataset_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_dataset(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    case_id: UUID | None = None,
    review_state: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CaseScore], int]:
    """A dataset's scores, newest first, narrowed to one case or one review state."""
    where = [CaseScore.organization_id == organization_id, CaseScore.dataset_id == dataset_id]
    if case_id is not None:
        where.append(CaseScore.case_id == case_id)
    if review_state is not None:
        where.append(CaseScore.review_state == review_state)
    total = await db.scalar(select(func.count(CaseScore.id)).where(*where)) or 0
    result = await db.execute(
        select(CaseScore)
        .where(*where)
        .order_by(CaseScore.created_at.desc(), CaseScore.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def list_pending(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CaseScore], int]:
    """Scores waiting for a person's verdict in the datasets one member may see.

    Oldest first, so the queue is worked in the order it filled. Visibility is
    the dataset listing's own predicate; `see_all` is a role reaching every
    dataset, `shared_ids` those shared with the member.
    """
    where = [
        CaseScore.organization_id == organization_id,
        CaseScore.review_state == "pending",
    ]
    if not see_all:
        where.append(
            visible_to_caller(
                Dataset.owner_user_id,
                Dataset.visibility,
                Dataset.id,
                user_id=user_id,
                shared_ids=shared_ids,
            )
        )
    joined = select(CaseScore).join(Dataset, Dataset.id == CaseScore.dataset_id).where(*where)
    total = await db.scalar(select(func.count()).select_from(joined.subquery())) or 0
    result = await db.execute(
        joined.order_by(CaseScore.created_at.asc(), CaseScore.id.asc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def update(db: AsyncSession, *, score: CaseScore, update_data: dict[str, Any]) -> CaseScore:
    for field, value in update_data.items():
        setattr(score, field, value)
    await db.flush()
    await db.refresh(score)
    return score
