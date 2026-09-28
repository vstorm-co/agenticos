"""Artifact repository (PostgreSQL async).

Listing is scoped the way every shared resource is: `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them, the
shape `context_repo` and `skill_repo` use.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.repositories._search import contains_ci


async def get(db: AsyncSession, artifact_id: UUID, *, organization_id: UUID) -> Artifact | None:
    result = await db.execute(
        select(Artifact).where(
            Artifact.id == artifact_id, Artifact.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_for_update(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, name: str
) -> Artifact | None:
    """The artifact a publish writes to, locked until the transaction ends.

    Locked because two runs of one agent publishing the same name at once would
    otherwise both read version 7 as the newest and both try to write 8.
    """
    result = await db.execute(
        select(Artifact)
        .where(
            Artifact.organization_id == organization_id,
            Artifact.agent_id == agent_id,
            Artifact.name == name,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_by_public_key(db: AsyncSession, public_key: str) -> Artifact | None:
    result = await db.execute(select(Artifact).where(Artifact.public_key == public_key))
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
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Artifact], int]:
    """The artifacts one member may see, newest publication first, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization.
        shared_ids: Artifact ids explicitly shared with this member.
        shared_with_me: Narrow to rows shared with the caller and not their own.
    """
    where = [Artifact.organization_id == organization_id]
    if shared_with_me:
        where.append(
            and_(
                or_(
                    Artifact.visibility == Visibility.ORG.value,
                    Artifact.id.in_(shared_ids) if shared_ids else false(),
                ),
                Artifact.owner_user_id.is_distinct_from(user_id),
            )
        )
    elif not see_all:
        where.append(
            or_(
                Artifact.owner_user_id == user_id,
                Artifact.visibility == Visibility.ORG.value,
                Artifact.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    if search:
        where.append(or_(contains_ci(Artifact.title, search), contains_ci(Artifact.name, search)))
    items = await db.execute(
        select(Artifact)
        .where(*where)
        .order_by(Artifact.published_at.desc(), Artifact.name.asc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(Artifact.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    agent_id: UUID,
    name: str,
    title: str,
) -> Artifact:
    artifact = Artifact(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        name=name,
        title=title,
        visibility=Visibility.PRIVATE.value,
    )
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


async def update(db: AsyncSession, *, artifact: Artifact, update_data: dict[str, Any]) -> Artifact:
    for field, value in update_data.items():
        setattr(artifact, field, value)
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


async def delete_artifact(db: AsyncSession, artifact: Artifact) -> None:
    await db.delete(artifact)
    await db.flush()


async def latest_version(db: AsyncSession, artifact_id: UUID) -> ArtifactVersion | None:
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_versions(
    db: AsyncSession, artifact_ids: list[UUID]
) -> dict[UUID, ArtifactVersion]:
    """The current version of each artifact, in one query for a whole listing page."""
    if not artifact_ids:
        return {}
    newest = (
        select(
            ArtifactVersion.artifact_id,
            func.max(ArtifactVersion.number).label("number"),
        )
        .where(ArtifactVersion.artifact_id.in_(artifact_ids))
        .group_by(ArtifactVersion.artifact_id)
        .subquery()
    )
    result = await db.execute(
        select(ArtifactVersion).join(
            newest,
            and_(
                ArtifactVersion.artifact_id == newest.c.artifact_id,
                ArtifactVersion.number == newest.c.number,
            ),
        )
    )
    return {version.artifact_id: version for version in result.scalars().all()}


async def get_version(
    db: AsyncSession, version_id: UUID, *, artifact_id: UUID | None = None
) -> ArtifactVersion | None:
    where = [ArtifactVersion.id == version_id]
    if artifact_id is not None:
        where.append(ArtifactVersion.artifact_id == artifact_id)
    result = await db.execute(select(ArtifactVersion).where(*where))
    return result.scalar_one_or_none()


async def get_version_with_artifact(
    db: AsyncSession, version_id: UUID
) -> tuple[ArtifactVersion, Artifact] | None:
    """A version and the artifact it belongs to, by the version's id alone.

    Unscoped by organization on purpose: the only caller holds a token this
    deployment signed for exactly this version, and the tenant was checked when
    it was minted.
    """
    result = await db.execute(
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ArtifactVersion.id == version_id)
    )
    row = result.one_or_none()
    return None if row is None else (row[0], row[1])


async def list_versions(db: AsyncSession, artifact_id: UUID) -> list[ArtifactVersion]:
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
    )
    return list(result.scalars().all())


async def create_version(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    number: int,
    media_type: str,
    size_bytes: int,
    sha256: str,
    storage_path: str,
    run_id: UUID | None,
) -> ArtifactVersion:
    version = ArtifactVersion(
        artifact_id=artifact_id,
        number=number,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        run_id=run_id,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def versions_beyond(
    db: AsyncSession, artifact_id: UUID, *, keep: int
) -> list[ArtifactVersion]:
    """Every version older than the newest `keep` - what pruning removes."""
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
        .offset(keep)
    )
    return list(result.scalars().all())


async def delete_versions(db: AsyncSession, version_ids: list[UUID]) -> None:
    if not version_ids:
        return
    await db.execute(delete(ArtifactVersion).where(ArtifactVersion.id.in_(version_ids)))
    await db.flush()


async def storage_paths(db: AsyncSession, artifact_id: UUID) -> list[str]:
    result = await db.execute(
        select(ArtifactVersion.storage_path).where(ArtifactVersion.artifact_id == artifact_id)
    )
    return list(result.scalars().all())
