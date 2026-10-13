"""Dataset repository (PostgreSQL async).

Cases are read through a version: a version's membership rows say which case
revisions it holds and in which order, so every case read here takes a version
id rather than a dataset id. Minting a version is the service's to sequence; the
pieces it is built from are here.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion, DatasetVersionCase
from app.repositories._search import contains_ci
from app.repositories._visibility import shared_with_caller, visible_to_caller
from app.schemas.dataset import DatasetSort


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
    search: str | None = None,
    sort: DatasetSort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Dataset], int]:
    """The datasets one member may see, filtered and paged, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization.
        shared_ids: Dataset ids explicitly shared with this member.
        shared_with_me: Narrow to rows shared with the caller and not their own.
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
    if search:
        where.append(contains_ci(Dataset.name, search) | contains_ci(Dataset.description, search))

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
) -> Dataset:
    dataset = Dataset(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
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


async def list_cases(
    db: AsyncSession, version_id: UUID, *, skip: int = 0, limit: int | None = 50
) -> list[DatasetCase]:
    """A version's cases in their order. `limit=None` reads them all, for an export."""
    query = (
        select(DatasetCase)
        .join(DatasetVersionCase, DatasetVersionCase.case_revision_id == DatasetCase.id)
        .where(DatasetVersionCase.version_id == version_id)
        .order_by(DatasetVersionCase.position.asc())
        .offset(skip)
    )
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def find_case(
    db: AsyncSession, version_id: UUID, case_id: UUID
) -> tuple[DatasetCase, int] | None:
    """The revision of a case a version holds, and its position there."""
    result = await db.execute(
        select(DatasetCase, DatasetVersionCase.position)
        .join(DatasetVersionCase, DatasetVersionCase.case_revision_id == DatasetCase.id)
        .where(DatasetVersionCase.version_id == version_id, DatasetCase.case_id == case_id)
    )
    row = result.one_or_none()
    return None if row is None else (row[0], row[1])


async def last_position(db: AsyncSession, version_id: UUID) -> int:
    """The highest position a version uses, or -1 when it holds nothing."""
    value = await db.scalar(
        select(func.max(DatasetVersionCase.position)).where(
            DatasetVersionCase.version_id == version_id
        )
    )
    return -1 if value is None else value


async def add_cases(db: AsyncSession, cases: list[DatasetCase]) -> None:
    """Write new case revisions. Their ids are set before the flush returns."""
    db.add_all(cases)
    await db.flush()


async def copy_membership(
    db: AsyncSession, *, source_version_id: UUID, target_version_id: UUID, skip: set[UUID]
) -> None:
    """Give the new version every revision the old one held, bar `skip`, in place.

    One `INSERT ... SELECT`, so a one-case edit to a ten-thousand-case dataset
    moves ten thousand ids inside the database rather than through Python.
    """
    query = select(
        literal(target_version_id),
        DatasetVersionCase.case_revision_id,
        DatasetVersionCase.position,
    ).where(DatasetVersionCase.version_id == source_version_id)
    if skip:
        query = query.where(DatasetVersionCase.case_revision_id.not_in(skip))
    await db.execute(
        insert(DatasetVersionCase).from_select(
            ["version_id", "case_revision_id", "position"], query
        )
    )
    await db.flush()


async def add_membership(
    db: AsyncSession, *, version_id: UUID, placements: list[tuple[UUID, int]]
) -> None:
    """Place case revisions in a version, each at its position."""
    if not placements:
        return
    db.add_all(
        DatasetVersionCase(version_id=version_id, case_revision_id=revision_id, position=position)
        for revision_id, position in placements
    )
    await db.flush()
