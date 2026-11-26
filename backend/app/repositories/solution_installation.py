"""Installation receipts and transaction-scoped serialization for concurrent retries."""

import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.solution_installation import SolutionInstallation


async def lock(db: AsyncSession, *, organization_id: UUID, user_id: UUID, key: str) -> None:
    scope = f"solution:{organization_id}:{user_id}:{key}".encode()
    lock_id = int.from_bytes(hashlib.sha256(scope).digest()[:8], signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_id)))


async def get(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, key: str
) -> SolutionInstallation | None:
    return await db.scalar(
        select(SolutionInstallation).where(
            SolutionInstallation.organization_id == organization_id,
            SolutionInstallation.user_id == user_id,
            SolutionInstallation.installation_key == key,
        )
    )


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    key: str,
    manifest_hash: str,
    resources: dict[str, dict[str, str]],
) -> SolutionInstallation:
    row = SolutionInstallation(
        organization_id=organization_id,
        user_id=user_id,
        installation_key=key,
        manifest_hash=manifest_hash,
        resources=resources,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row
