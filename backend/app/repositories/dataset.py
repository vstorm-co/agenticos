"""Dataset repository (PostgreSQL async).

Cases are read through a version: the versions a revision is held by are kept
on the revision (see `app.db.models.dataset`), so every case read here takes a
version id rather than a dataset id. Minting a version is the service's to
sequence; the pieces it is built from are here.
"""

from collections.abc import Sequence
from typing import Any, get_args
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, true
from sqlalchemy import update as update_rows
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Scope
from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion
from app.repositories._search import contains_ci
from app.repositories._visibility import reached_by_scope, shared_with_caller, visible_to_caller
from app.schemas.dataset import (
    CaseSourceLiteral,
    DatasetSort,
    DatasetStats,
    DatasetTagCount,
    ExpectationMix,
)


def _asks(question: str) -> ColumnElement[bool]:
    """A case asking this question, compared without regard to case, surrounding
    space or how the space inside it runs."""
    spaced = func.btrim(func.regexp_replace(DatasetCase.input, r"\s+", " ", "g"))
    return func.lower(spaced) == " ".join(question.split()).lower()


async def get(db: AsyncSession, dataset_id: UUID, *, organization_id: UUID) -> Dataset | None:
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str, *, organization_id: UUID) -> Dataset | None:
    result = await db.execute(
        select(Dataset).where(Dataset.name == name, Dataset.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def lock(db: AsyncSession, dataset_id: UUID, *, organization_id: UUID) -> Dataset | None:
    """The dataset locked until the transaction ends, read afresh.

    What serializes minting: the next version's number and the membership it
    copies are both read after this, so two edits to one dataset queue rather
    than both writing version N+1.
    """
    result = await db.execute(
        select(Dataset)
        .where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool = False,
    edit_scope: Scope | None = None,
    edit_ids: Sequence[UUID] = (),
    run_scope: Scope | None = None,
    run_ids: Sequence[UUID] = (),
    search: str | None = None,
    judge_id: UUID | None = None,
    judge_is_default: bool = False,
    asking: str | None = None,
    sort: DatasetSort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Dataset], int]:
    """The datasets one member may see, filtered and paged, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization.
        shared_ids: Dataset ids explicitly shared with this member.
        shared_with_me: Narrow to rows shared with the caller and not their own.
        edit_scope: Narrow to the rows the caller may also edit: their role's
            scope for editing, with `edit_ids` granted at edit level. None
            narrows nothing.
        run_scope: Narrow, the same way, to the rows the caller may run, with
            `run_ids` granted at the level running takes - and to those whose
            newest version holds a case, since there is nothing to run otherwise.
        judge_id: Narrow to the datasets of this judge: the ones that picked
            it, grading or not, and when `judge_is_default` the ones that
            picked none and grade with the judge or the reference comparison.
        asking: Narrow to the datasets whose newest version holds a case asking
            this question, compared as `list_cases`' `same_input` compares.
    """
    where = [Dataset.organization_id == organization_id]
    if shared_with_me:
        where.append(
            shared_with_caller(
                Dataset.owner_user_id,
                Dataset.visibility,
                Dataset.id,
                user_id=user_id,
                shared_ids=shared_ids,
            )
        )
    elif not see_all:
        where.append(
            visible_to_caller(
                Dataset.owner_user_id,
                Dataset.visibility,
                Dataset.id,
                user_id=user_id,
                shared_ids=shared_ids,
            )
        )
    if edit_scope is not None:
        where.append(
            reached_by_scope(
                Dataset.owner_user_id,
                Dataset.visibility,
                Dataset.id,
                scope=edit_scope,
                user_id=user_id,
                granted_ids=edit_ids,
            )
        )
    if run_scope is not None:
        where.append(
            reached_by_scope(
                Dataset.owner_user_id,
                Dataset.visibility,
                Dataset.id,
                scope=run_scope,
                user_id=user_id,
                granted_ids=run_ids,
            )
        )
        where.append(
            exists(
                select(DatasetVersion.id).where(
                    DatasetVersion.dataset_id == Dataset.id,
                    DatasetVersion.number == Dataset.latest_version,
                    DatasetVersion.case_count > 0,
                )
            )
        )
    if search:
        where.append(contains_ci(Dataset.name, search) | contains_ci(Dataset.description, search))
    if judge_id is not None:
        picked = Dataset.scoring["judge"]["agent_id"].astext
        grading = or_(
            Dataset.scoring["judge"]["enabled"].as_boolean().is_(True),
            Dataset.scoring["reference"]["enabled"].as_boolean().is_(True),
        )
        where.append(
            or_(picked == str(judge_id), and_(picked.is_(None), grading))
            if judge_is_default
            else picked == str(judge_id)
        )
    if asking is not None:
        where.append(
            # The newest version holds exactly the revisions no change has removed yet.
            exists(
                select(DatasetCase.id).where(
                    DatasetCase.dataset_id == Dataset.id,
                    DatasetCase.removed_in.is_(None),
                    _asks(asking),
                )
            )
        )

    order_by = (
        (func.coalesce(Dataset.updated_at, Dataset.created_at).desc(), Dataset.name.asc())
        if sort == "updated"
        else (Dataset.name.asc(),)
    )
    items = await db.execute(
        select(Dataset).where(*where).order_by(*order_by).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(Dataset.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str | None,
    visibility: str,
) -> Dataset:
    dataset = Dataset(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        visibility=visibility,
    )
    db.add(dataset)
    await db.flush()
    await db.refresh(dataset)
    return dataset


async def update(db: AsyncSession, *, dataset: Dataset, update_data: dict[str, Any]) -> Dataset:
    for field, value in update_data.items():
        setattr(dataset, field, value)
    db.add(dataset)
    await db.flush()
    await db.refresh(dataset)
    return dataset


async def delete(db: AsyncSession, dataset: Dataset) -> None:
    await db.delete(dataset)
    await db.flush()


async def get_version(
    db: AsyncSession, dataset_id: UUID, number: int, *, organization_id: UUID
) -> DatasetVersion | None:
    result = await db.execute(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.number == number,
            DatasetVersion.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, dataset_id: UUID, *, organization_id: UUID, skip: int = 0, limit: int = 50
) -> tuple[list[DatasetVersion], int]:
    """A dataset's versions, newest first, with the total."""
    where = (
        DatasetVersion.dataset_id == dataset_id,
        DatasetVersion.organization_id == organization_id,
    )
    items = await db.execute(
        select(DatasetVersion)
        .where(*where)
        .order_by(DatasetVersion.number.desc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(DatasetVersion.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create_version(
    db: AsyncSession,
    *,
    dataset_id: UUID,
    organization_id: UUID,
    number: int,
    case_count: int,
    change: str,
    changed_cases: int,
    created_by_user_id: UUID | None,
) -> DatasetVersion:
    version = DatasetVersion(
        dataset_id=dataset_id,
        organization_id=organization_id,
        number=number,
        case_count=case_count,
        change=change,
        changed_cases=changed_cases,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


def _held(version_id: UUID) -> ColumnElement[bool]:
    """Join a version to the revisions it holds: those its number falls within."""
    return and_(
        DatasetVersion.id == version_id,
        DatasetCase.dataset_id == DatasetVersion.dataset_id,
        DatasetCase.added_in <= DatasetVersion.number,
        or_(DatasetCase.removed_in.is_(None), DatasetCase.removed_in > DatasetVersion.number),
    )


async def list_cases(
    db: AsyncSession,
    version_id: UUID,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int | None = 50,
    same_input: str | None = None,
) -> list[DatasetCase]:
    """A version's cases in their order. `limit=None` reads them all, for an export.

    `same_input` keeps the cases asking that question, compared without regard
    to case, surrounding space or how the space inside it runs.
    """
    query = (
        select(DatasetCase)
        .join(DatasetVersion, _held(version_id))
        .where(DatasetCase.organization_id == organization_id)
        .order_by(DatasetCase.position.asc())
        .offset(skip)
    )
    if same_input is not None:
        query = query.where(_asks(same_input))
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


TOP_TAGS = 3


async def case_stats(
    db: AsyncSession, dataset_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, DatasetStats]:
    """What the newest version of each dataset tests against, counted.

    Two queries for any number of datasets - the counts, and the most used tags -
    so a listing page costs the same whichever size it is. A dataset with no
    version yet is absent; the caller's default is all zeros.
    """
    if not dataset_ids:
        return {}
    # The newest version holds exactly the revisions no change has removed yet.
    held = (
        select(
            DatasetCase.dataset_id,
            DatasetCase.reference_answer,
            DatasetCase.counter_example,
            DatasetCase.expected_tool_calls,
            DatasetCase.checks,
            DatasetCase.source,
            DatasetCase.tags,
        )
        .where(
            DatasetCase.dataset_id.in_(dataset_ids),
            DatasetCase.organization_id == organization_id,
            DatasetCase.removed_in.is_(None),
        )
        .subquery()
    )
    sources: tuple[CaseSourceLiteral, ...] = get_args(CaseSourceLiteral)
    has_reference = func.nullif(held.c.reference_answer, "").is_not(None)
    has_counter = func.nullif(held.c.counter_example, "").is_not(None)
    compared = has_reference | has_counter
    has_calls = func.jsonb_array_length(held.c.expected_tool_calls) > 0
    has_checks = func.jsonb_array_length(held.c.checks) > 0
    mixes = [
        (checks, calls, reference)
        for checks in (False, True)
        for calls in (False, True)
        for reference in (False, True)
    ]
    counts = await db.execute(
        select(
            held.c.dataset_id,
            func.count().filter(has_reference),
            func.count().filter(has_counter),
            func.count().filter(has_calls),
            func.count().filter(has_checks),
            *(func.count().filter(held.c.source == source) for source in sources),
            *(
                func.count().filter(
                    has_checks.is_(checks), has_calls.is_(calls), compared.is_(reference)
                )
                for checks, calls, reference in mixes
            ),
        ).group_by(held.c.dataset_id)
    )
    stats = {}
    for row in counts.all():
        mixed = row[5 + len(sources) :]
        stats[row[0]] = DatasetStats(
            with_reference=row[1],
            with_counter_example=row[2],
            with_tool_calls=row[3],
            with_checks=row[4],
            by_source=dict(zip(sources, row[5 : 5 + len(sources)], strict=True)),
            expectation_mix=[
                ExpectationMix(checks=checks, tool_calls=calls, reference=reference, cases=cases)
                for (checks, calls, reference), cases in zip(mixes, mixed, strict=True)
                if cases > 0
            ],
        )

    tag = func.jsonb_array_elements_text(held.c.tags).table_valued("value").lateral("tag")
    used = func.count()
    rank = func.row_number().over(
        partition_by=held.c.dataset_id, order_by=(used.desc(), tag.c.value.asc())
    )
    ranked = (
        select(held.c.dataset_id, tag.c.value.label("tag"), used.label("cases"), rank.label("rank"))
        .select_from(held)
        .join(tag, true())
        .group_by(held.c.dataset_id, tag.c.value)
        .subquery()
    )
    tags = await db.execute(
        select(ranked.c.dataset_id, ranked.c.tag, ranked.c.cases)
        .where(ranked.c.rank <= TOP_TAGS)
        .order_by(ranked.c.dataset_id, ranked.c.rank)
    )
    for dataset_id, name, cases in tags.all():
        stats[dataset_id].top_tags.append(DatasetTagCount(tag=name, cases=cases))
    return stats


async def stored_revisions(db: AsyncSession, *, organization_id: UUID) -> int:
    """How many case revisions an organization's datasets store, all of them together."""
    total = await db.scalar(
        select(func.count(DatasetCase.id)).where(DatasetCase.organization_id == organization_id)
    )
    return int(total or 0)


async def find_case(
    db: AsyncSession, version_id: UUID, case_id: UUID, *, organization_id: UUID
) -> tuple[DatasetCase, int] | None:
    """The revision of a case a version holds, and its position there."""
    result = await db.execute(
        select(DatasetCase, DatasetCase.position)
        .join(DatasetVersion, _held(version_id))
        .where(
            DatasetCase.case_id == case_id,
            DatasetCase.organization_id == organization_id,
        )
    )
    row = result.one_or_none()
    return None if row is None else (row[0], row[1])


async def case_from_message(
    db: AsyncSession, version_id: UUID, message_id: UUID, *, organization_id: UUID
) -> DatasetCase | None:
    """The case of a version made from this agent answer, if one was."""
    result = await db.execute(
        select(DatasetCase)
        .join(DatasetVersion, _held(version_id))
        .where(
            DatasetCase.source_message_id == message_id,
            DatasetCase.organization_id == organization_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def messages_held(
    db: AsyncSession, version_id: UUID, message_ids: Sequence[UUID], *, organization_id: UUID
) -> set[UUID]:
    """Which of these agent answers a version already holds a case made from."""
    if not message_ids:
        return set()
    result = await db.execute(
        select(DatasetCase.source_message_id)
        .join(DatasetVersion, _held(version_id))
        .where(
            DatasetCase.source_message_id.in_(message_ids),
            DatasetCase.organization_id == organization_id,
        )
    )
    return {message_id for message_id in result.scalars() if message_id is not None}


async def last_position(db: AsyncSession, version_id: UUID, *, organization_id: UUID) -> int:
    """The highest position a version uses, or -1 when it holds nothing."""
    value = await db.scalar(
        select(func.max(DatasetCase.position))
        .join(DatasetVersion, _held(version_id))
        .where(DatasetCase.organization_id == organization_id)
    )
    return -1 if value is None else value


async def add_cases(db: AsyncSession, cases: list[DatasetCase]) -> None:
    """Write new case revisions, each already placed. Their ids are set before the flush returns."""
    db.add_all(cases)
    await db.flush()


async def close_revisions(
    db: AsyncSession, revision_ids: Sequence[UUID], *, organization_id: UUID, at: int
) -> None:
    """Leave these revisions out of version `at` and every version after it.

    Only a revision still held by the newest version, and added before `at`, is
    closed, so no version that already exists can change what it holds.
    """
    if not revision_ids:
        return
    await db.execute(
        update_rows(DatasetCase)
        .where(
            DatasetCase.id.in_(revision_ids),
            DatasetCase.organization_id == organization_id,
            DatasetCase.removed_in.is_(None),
            DatasetCase.added_in < at,
        )
        .values(removed_in=at)
    )
    await db.flush()
