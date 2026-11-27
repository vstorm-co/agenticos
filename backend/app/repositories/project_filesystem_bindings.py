"""Tenant-scoped metadata for workspace mounts and their admitted run views."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease


async def binding_for_session(
    db: AsyncSession, *, organization_id: UUID, connection_id: UUID, session_name: str
) -> ProjectFilesystemBinding | None:
    return await db.scalar(
        select(ProjectFilesystemBinding).where(
            ProjectFilesystemBinding.organization_id == organization_id,
            ProjectFilesystemBinding.connection_id == connection_id,
            ProjectFilesystemBinding.session_name == session_name,
        )
    )


async def insert_binding(db: AsyncSession, *, row: ProjectFilesystemBinding) -> None:
    """Admit one session credential without racing another opener's identity."""
    await db.execute(
        insert(ProjectFilesystemBinding)
        .values(
            id=row.id,
            organization_id=row.organization_id,
            connection_id=row.connection_id,
            workspace_id=row.workspace_id,
            conversation_id=row.conversation_id,
            session_name=row.session_name,
            token_digest=row.token_digest,
            ciphertext=row.ciphertext,
            secret_key_version=row.secret_key_version,
        )
        .on_conflict_do_nothing(constraint="uq_project_filesystem_binding_session")
    )
    await db.flush()


async def binding_by_id(
    db: AsyncSession, binding_id: UUID, *, for_update: bool = False
) -> ProjectFilesystemBinding | None:
    """A public opaque ID is looked up only together with credential verification."""
    statement = select(ProjectFilesystemBinding).where(ProjectFilesystemBinding.id == binding_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement)


async def create_lease(
    db: AsyncSession, *, lease: ProjectFilesystemLease
) -> ProjectFilesystemLease:
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    return lease


async def lease_for_binding(
    db: AsyncSession, *, binding: ProjectFilesystemBinding, lease_id: UUID
) -> ProjectFilesystemLease | None:
    return await db.scalar(
        select(ProjectFilesystemLease).where(
            ProjectFilesystemLease.id == lease_id,
            ProjectFilesystemLease.binding_id == binding.id,
            ProjectFilesystemLease.organization_id == binding.organization_id,
        )
    )


async def live_leases(
    db: AsyncSession, *, binding: ProjectFilesystemBinding, now: datetime
) -> list[ProjectFilesystemLease]:
    rows = await db.scalars(
        select(ProjectFilesystemLease)
        .where(
            ProjectFilesystemLease.binding_id == binding.id,
            ProjectFilesystemLease.organization_id == binding.organization_id,
            ProjectFilesystemLease.revoked_at.is_(None),
            or_(
                (ProjectFilesystemLease.environment_id.is_(None))
                & (ProjectFilesystemLease.expires_at > now),
                exists().where(
                    ConversationEnvironment.id == ProjectFilesystemLease.environment_id,
                    ConversationEnvironment.organization_id == binding.organization_id,
                    ConversationEnvironment.state.in_(("starting", "ready")),
                    ConversationEnvironment.expires_at > now,
                ),
            ),
        )
        .order_by(ProjectFilesystemLease.created_at, ProjectFilesystemLease.id)
        .limit(64)
    )
    return list(rows)


async def renew_lease(
    db: AsyncSession,
    *,
    lease_id: UUID,
    run_id: UUID,
    organization_id: UUID,
    now: datetime,
    expires_at: datetime,
) -> bool:
    result = await db.execute(
        update(ProjectFilesystemLease)
        .where(
            ProjectFilesystemLease.id == lease_id,
            ProjectFilesystemLease.run_id == run_id,
            ProjectFilesystemLease.organization_id == organization_id,
            ProjectFilesystemLease.revoked_at.is_(None),
            ProjectFilesystemLease.expires_at > now,
        )
        .values(expires_at=expires_at)
        .returning(ProjectFilesystemLease.id)
    )
    return result.scalar_one_or_none() is not None


async def revoke_lease(
    db: AsyncSession, *, lease_id: UUID, run_id: UUID, organization_id: UUID, now: datetime
) -> None:
    await db.execute(
        update(ProjectFilesystemLease)
        .where(
            ProjectFilesystemLease.id == lease_id,
            ProjectFilesystemLease.run_id == run_id,
            ProjectFilesystemLease.organization_id == organization_id,
            ProjectFilesystemLease.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def environment_lease(
    db: AsyncSession, *, binding_id: UUID, environment_id: UUID
) -> ProjectFilesystemLease | None:
    """Find the immutable path, including a revoked row which must never revive."""
    return await db.scalar(
        select(ProjectFilesystemLease).where(
            ProjectFilesystemLease.binding_id == binding_id,
            ProjectFilesystemLease.environment_id == environment_id,
        )
    )
