"""Case score repository (PostgreSQL async).

`organization_id` is a required keyword on every read: a score quotes an answer,
and a forgotten tenant filter must not look like an ordinary call (see
tests/test_org_scope_regression.py).
"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase
from app.repositories._visibility import visible_to_caller
from app.schemas.scoring import ScoreOutcome


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    case_revision_id: UUID,
    case_id: UUID,
    run_id: UUID | None,
    agent_id: UUID | None,
    eval_run_id: UUID | None,
    answer: str | None,
    scoring: dict[str, Any],
    results: list[dict[str, Any]],
    judge: dict[str, Any] | None,
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
        agent_id=agent_id,
        eval_run_id=eval_run_id,
        answer=answer,
        scoring=scoring,
        results=results,
        judge=judge,
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


async def get_many(
    db: AsyncSession, score_ids: list[UUID], *, organization_id: UUID, dataset_id: UUID
) -> dict[UUID, CaseScore]:
    """The scores of this dataset among `score_ids`, by id."""
    result = await db.execute(
        select(CaseScore).where(
            CaseScore.id.in_(score_ids),
            CaseScore.organization_id == organization_id,
            CaseScore.dataset_id == dataset_id,
        )
    )
    return {score.id: score for score in result.scalars().all()}


async def existing_ids(
    db: AsyncSession, score_ids: list[UUID], *, organization_id: UUID, dataset_id: UUID
) -> set[UUID]:
    """Which of `score_ids` are scores of this dataset."""
    result = await db.execute(
        select(CaseScore.id).where(
            CaseScore.id.in_(score_ids),
            CaseScore.organization_id == organization_id,
            CaseScore.dataset_id == dataset_id,
        )
    )
    return set(result.scalars().all())


async def waiting_for_cases(
    db: AsyncSession, case_ids: list[UUID], *, organization_id: UUID, dataset_id: UUID
) -> list[CaseScore]:
    """The scores of this dataset waiting for a person on any of `case_ids`."""
    result = await db.execute(
        select(CaseScore).where(
            CaseScore.case_id.in_(case_ids),
            CaseScore.organization_id == organization_id,
            CaseScore.dataset_id == dataset_id,
            CaseScore.review_state == "pending",
        )
    )
    return list(result.scalars().all())


async def queue_for_review(
    db: AsyncSession, score_ids: list[UUID], *, organization_id: UUID, dataset_id: UUID
) -> int:
    """Put the scores no one was asked to review in the queue; how many that was."""
    result = cast(
        CursorResult[Any],
        await db.execute(
            sql_update(CaseScore)
            .where(
                CaseScore.id.in_(score_ids),
                CaseScore.organization_id == organization_id,
                CaseScore.dataset_id == dataset_id,
                CaseScore.review_state == "none",
            )
            .values(review_state="pending")
            .execution_options(synchronize_session="fetch")
        ),
    )
    await db.flush()
    return result.rowcount or 0


async def dequeue(
    db: AsyncSession, score_ids: list[UUID], *, organization_id: UUID, dataset_id: UUID
) -> int:
    """Take the waiting scores out of the queue, undecided; how many that was."""
    result = cast(
        CursorResult[Any],
        await db.execute(
            sql_update(CaseScore)
            .where(
                CaseScore.id.in_(score_ids),
                CaseScore.organization_id == organization_id,
                CaseScore.dataset_id == dataset_id,
                CaseScore.review_state == "pending",
            )
            .values(review_state="none")
            .execution_options(synchronize_session="fetch")
        ),
    )
    await db.flush()
    return result.rowcount or 0


async def list_for_dataset(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    case_id: UUID | None = None,
    review_state: str | None = None,
    outcome: ScoreOutcome | None = None,
    agent_id: UUID | None = None,
    eval_run_id: UUID | None = None,
    judge_id: UUID | None = None,
    tag: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CaseScore], int]:
    """A dataset's scores, newest first, narrowed by case, review state, outcome, the
    agent that answered, the eval run that scored them, or a tag of the scored case.

    `outcome` reads the person's decision where there is one, the scorers' otherwise.
    """
    where = [CaseScore.organization_id == organization_id, CaseScore.dataset_id == dataset_id]
    if case_id is not None:
        where.append(CaseScore.case_id == case_id)
    if review_state is not None:
        where.append(CaseScore.review_state == review_state)
    if outcome is not None:
        settled = func.coalesce(CaseScore.human_passed, CaseScore.passed)
        where.append(
            settled.is_(None) if outcome == "not_graded" else settled.is_(outcome == "passed")
        )
    if agent_id is not None:
        where.append(CaseScore.agent_id == agent_id)
    if eval_run_id is not None:
        where.append(CaseScore.eval_run_id == eval_run_id)
    if judge_id is not None:
        where.append(CaseScore.judge["agent_id"].astext == str(judge_id))
    if tag is not None:
        where.append(
            CaseScore.case_revision_id.in_(
                select(DatasetCase.id).where(
                    DatasetCase.organization_id == organization_id,
                    DatasetCase.tags.contains([tag]),
                )
            )
        )
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
) -> tuple[list[tuple[CaseScore, str]], int]:
    """Scores waiting for a person's verdict in the datasets one member may see.

    Oldest first, so the queue is worked in the order it filled, each with its
    dataset's name. Visibility is the dataset listing's own predicate;
    `see_all` is a role reaching every dataset, `shared_ids` those shared with
    the member.
    """
    where = _pending(organization_id, user_id=user_id, see_all=see_all, shared_ids=shared_ids)
    joined = (
        select(CaseScore, Dataset.name)
        .join(Dataset, Dataset.id == CaseScore.dataset_id)
        .where(*where)
    )
    total = await db.scalar(select(func.count()).select_from(joined.subquery())) or 0
    result = await db.execute(
        joined.order_by(CaseScore.created_at.asc(), CaseScore.id.asc()).offset(skip).limit(limit)
    )
    return [(score, name) for score, name in result.all()], total


async def pending_counts(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
) -> list[tuple[UUID, str, bool | None, int]]:
    """How many scores wait in each dataset one member may see, by what the scorers concluded."""
    where = _pending(organization_id, user_id=user_id, see_all=see_all, shared_ids=shared_ids)
    result = await db.execute(
        select(Dataset.id, Dataset.name, CaseScore.passed, func.count())
        .join(Dataset, Dataset.id == CaseScore.dataset_id)
        .where(*where)
        .group_by(Dataset.id, Dataset.name, CaseScore.passed)
    )
    return [(row[0], row[1], row[2], row[3]) for row in result.all()]


async def decided_for_judge(
    db: AsyncSession,
    *,
    organization_id: UUID,
    judge_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
) -> list[tuple[list[dict[str, Any]], bool]]:
    """The results and the person's decision of every decided score one judge graded.

    In the datasets one member may see; whether the judge reached a verdict of
    its own is the caller's to read from the results.
    """
    where = [
        CaseScore.organization_id == organization_id,
        CaseScore.judge["agent_id"].astext == str(judge_id),
        CaseScore.human_passed.is_not(None),
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
    rows = await db.execute(
        select(CaseScore.results, CaseScore.human_passed)
        .join(Dataset, Dataset.id == CaseScore.dataset_id)
        .where(*where)
    )
    return [(results, bool(human)) for results, human in rows.all()]


def _pending(
    organization_id: UUID, *, user_id: UUID, see_all: bool, shared_ids: list[UUID]
) -> list[ColumnElement[bool]]:
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
    return where


async def update(db: AsyncSession, *, score: CaseScore, update_data: dict[str, Any]) -> CaseScore:
    for field, value in update_data.items():
        setattr(score, field, value)
    await db.flush()
    await db.refresh(score)
    return score
