"""Skill versions, forks and file bodies (PostgreSQL async).

Versions are written and read, never updated: there is deliberately no update
function here. Every function takes the organization, and every query filters on
it, so a version id from another tenant reads as absent.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, any_, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.skill_version import ManifestEntry, SkillFile, SkillFork, SkillVersion


async def create_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    fork_id: UUID | None,
    number: int,
    description: str,
    content: str,
    resources: dict[str, ManifestEntry],
    source: str,
    restored_from_id: UUID | None,
    proposal_id: UUID | None,
    library_fingerprint: str | None,
    created_by_user_id: UUID | None,
    merged_from_id: UUID | None = None,
) -> SkillVersion:
    version = SkillVersion(
        organization_id=organization_id,
        skill_id=skill_id,
        fork_id=fork_id,
        number=number,
        description=description,
        content=content,
        resources=resources,
        source=source,
        restored_from_id=restored_from_id,
        merged_from_id=merged_from_id,
        proposal_id=proposal_id,
        library_fingerprint=library_fingerprint,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def get_version(
    db: AsyncSession, version_id: UUID, *, organization_id: UUID, skill_id: UUID
) -> SkillVersion | None:
    """One version, only as a version of this skill - another skill's id reads as absent."""
    result = await db.execute(
        select(SkillVersion).where(
            SkillVersion.id == version_id,
            SkillVersion.organization_id == organization_id,
            SkillVersion.skill_id == skill_id,
        )
    )
    return result.scalar_one_or_none()


async def get_versions(
    db: AsyncSession, version_ids: Collection[UUID], *, organization_id: UUID
) -> dict[UUID, SkillVersion]:
    if not version_ids:
        return {}
    result = await db.execute(
        select(SkillVersion).where(
            SkillVersion.id.in_(list(version_ids)),
            SkillVersion.organization_id == organization_id,
        )
    )
    return {version.id: version for version in result.scalars().all()}


async def latest_number(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, fork_id: UUID | None
) -> int:
    """The highest number on one line, or 0 for a line with no version yet."""
    line = SkillVersion.fork_id.is_(None) if fork_id is None else SkillVersion.fork_id == fork_id
    number = await db.scalar(
        select(func.max(SkillVersion.number)).where(
            SkillVersion.organization_id == organization_id,
            SkillVersion.skill_id == skill_id,
            line,
        )
    )
    return number or 0


async def get_by_numbers(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    fork_id: UUID | None,
    numbers: Collection[int],
) -> dict[int, SkillVersion]:
    """Versions of one line by number - main's when `fork_id` is None."""
    if not numbers:
        return {}
    line = SkillVersion.fork_id.is_(None) if fork_id is None else SkillVersion.fork_id == fork_id
    result = await db.execute(
        select(SkillVersion).where(
            SkillVersion.organization_id == organization_id,
            SkillVersion.skill_id == skill_id,
            line,
            SkillVersion.number.in_(list(numbers)),
        )
    )
    return {version.number: version for version in result.scalars().all()}


async def main_digests(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, first: int, last: int
) -> list[tuple[int, str]]:
    """Main's versions `first` to `last` by number, oldest first, each with a hash of what
    it says: its description, its text and its files.

    Hashed by the database, so no version's text is read to tell two versions apart.
    """
    said = (
        SkillVersion.description
        + "\x1e"
        + SkillVersion.content
        + "\x1e"
        + cast(SkillVersion.resources, Text)
    )
    result = await db.execute(
        select(SkillVersion.number, func.encode(func.sha256(func.convert_to(said, "UTF8")), "hex"))
        .where(
            SkillVersion.organization_id == organization_id,
            SkillVersion.skill_id == skill_id,
            SkillVersion.fork_id.is_(None),
            SkillVersion.number.between(first, last),
        )
        .order_by(SkillVersion.number)
    )
    return [(number, digest) for number, digest in result.all()]


async def list_versions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    fork_id: UUID | None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[SkillVersion], int]:
    """One line's versions, newest first, with the unpaged total."""
    line = SkillVersion.fork_id.is_(None) if fork_id is None else SkillVersion.fork_id == fork_id
    where = [
        SkillVersion.organization_id == organization_id,
        SkillVersion.skill_id == skill_id,
        line,
    ]
    items = await db.execute(
        select(SkillVersion)
        .where(*where)
        .order_by(SkillVersion.number.desc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(SkillVersion.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def put_files(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, bodies: dict[str, str]
) -> None:
    """Store file bodies by hash; a body the skill already has is not written twice."""
    if not bodies:
        return
    await db.execute(
        insert(SkillFile)
        .values(
            [
                {
                    "skill_id": skill_id,
                    "sha256": sha256,
                    "organization_id": organization_id,
                    "content": content,
                }
                for sha256, content in bodies.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["skill_id", "sha256"])
    )


async def get_files(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, hashes: Collection[str]
) -> dict[str, str]:
    if not hashes:
        return {}
    result = await db.execute(
        select(SkillFile.sha256, SkillFile.content).where(
            SkillFile.organization_id == organization_id,
            SkillFile.skill_id == skill_id,
            SkillFile.sha256.in_(list(hashes)),
        )
    )
    return dict(result.tuples().all())


async def create_fork(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    name: str,
    base_version_id: UUID,
    created_for_agent_id: UUID | None,
    created_by_user_id: UUID | None,
) -> SkillFork:
    fork = SkillFork(
        organization_id=organization_id,
        skill_id=skill_id,
        name=name,
        base_version_id=base_version_id,
        started_from_id=base_version_id,
        created_for_agent_id=created_for_agent_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(fork)
    await db.flush()
    await db.refresh(fork)
    return fork


async def get_fork(
    db: AsyncSession, fork_id: UUID, *, organization_id: UUID, skill_id: UUID, lock: bool = False
) -> SkillFork | None:
    """One fork of this skill; locked, it is about to get a version or change state."""
    query = select(SkillFork).where(
        SkillFork.id == fork_id,
        SkillFork.organization_id == organization_id,
        SkillFork.skill_id == skill_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_forks(
    db: AsyncSession, fork_ids: Collection[UUID], *, organization_id: UUID
) -> dict[UUID, SkillFork]:
    """Forks of any of the organization's skills, by id."""
    if not fork_ids:
        return {}
    result = await db.execute(
        select(SkillFork).where(
            SkillFork.id.in_(list(fork_ids)), SkillFork.organization_id == organization_id
        )
    )
    return {fork.id: fork for fork in result.scalars().all()}


async def hold_forks(
    db: AsyncSession, fork_ids: Collection[UUID], *, organization_id: UUID
) -> dict[UUID, SkillFork]:
    """Forks an agent is about to read, read afresh and kept from being archived until the
    transaction ends.

    `FOR KEY SHARE`: archiving locks the fork `FOR UPDATE`, so it waits for a binding
    written now and then sees it, and a binding waits for an archive in progress and
    then finds the fork archived.
    """
    if not fork_ids:
        return {}
    result = await db.execute(
        select(SkillFork)
        .where(SkillFork.id.in_(list(fork_ids)), SkillFork.organization_id == organization_id)
        .with_for_update(read=True, key_share=True)
        .execution_options(populate_existing=True)
    )
    return {fork.id: fork for fork in result.scalars().all()}


async def get_fork_by_name(
    db: AsyncSession, name: str, *, organization_id: UUID, skill_id: UUID
) -> SkillFork | None:
    result = await db.execute(
        select(SkillFork).where(
            SkillFork.organization_id == organization_id,
            SkillFork.skill_id == skill_id,
            SkillFork.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_forks(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, archived: bool
) -> list[SkillFork]:
    archived_now = SkillFork.archived_at.is_not(None)
    result = await db.execute(
        select(SkillFork)
        .where(
            SkillFork.organization_id == organization_id,
            SkillFork.skill_id == skill_id,
            archived_now if archived else ~archived_now,
        )
        .order_by(SkillFork.name.asc())
    )
    return list(result.scalars().all())


async def update_fork(
    db: AsyncSession, *, fork: SkillFork, update_data: dict[str, Any]
) -> SkillFork:
    for field, value in update_data.items():
        setattr(fork, field, value)
    await db.flush()
    await db.refresh(fork)
    return fork


async def count_versions(
    db: AsyncSession, *, organization_id: UUID, fork_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """How many own versions each fork has - its changes since its base."""
    counts: dict[UUID, int] = dict.fromkeys(fork_ids, 0)
    if not fork_ids:
        return counts
    result = await db.execute(
        select(SkillVersion.fork_id, func.count(SkillVersion.id))
        .where(
            SkillVersion.organization_id == organization_id,
            SkillVersion.fork_id.in_(list(fork_ids)),
        )
        .group_by(SkillVersion.fork_id)
    )
    counts.update(
        (fork_id, count) for fork_id, count in result.tuples().all() if fork_id is not None
    )
    return counts


async def count_active_forks(
    db: AsyncSession, *, organization_id: UUID, skill_ids: Sequence[UUID]
) -> dict[UUID, int]:
    counts: dict[UUID, int] = dict.fromkeys(skill_ids, 0)
    if not skill_ids:
        return counts
    result = await db.execute(
        select(SkillFork.skill_id, func.count(SkillFork.id))
        .where(
            SkillFork.organization_id == organization_id,
            SkillFork.skill_id.in_(list(skill_ids)),
            SkillFork.archived_at.is_(None),
        )
        .group_by(SkillFork.skill_id)
    )
    for skill_id, count in result.tuples().all():
        counts[skill_id] = count
    return counts


async def forks_served_since(
    db: AsyncSession, *, organization_id: UUID, fork_ids: Sequence[UUID], since: datetime
) -> set[UUID]:
    """The forks a run has served one of its own versions of since `since`."""
    if not fork_ids:
        return set()
    served = (
        select(SkillVersion.fork_id)
        .join(
            AgentRun,
            and_(
                AgentRun.organization_id == organization_id,
                AgentRun.created_at >= since,
                SkillVersion.id == any_(AgentRun.skill_version_ids),
            ),
        )
        .where(
            SkillVersion.organization_id == organization_id,
            SkillVersion.fork_id.in_(list(fork_ids)),
        )
        .distinct()
    )
    result = await db.execute(served)
    return {fork_id for fork_id in result.scalars().all() if fork_id is not None}
