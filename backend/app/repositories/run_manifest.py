"""Rows in `run_manifests` - what a run handed its model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.run_manifest import RunManifest


async def get_by_run(db: AsyncSession, run_id: UUID, organization_id: UUID) -> RunManifest | None:
    """The manifest for one run, within one organization.

    Scoped on both, like every read of a tenant's row: the run has already been
    resolved against the caller's organization by the time this is reached, and
    a second clause here is what keeps that true if it ever is not.
    """
    result = await db.execute(
        select(RunManifest).where(
            RunManifest.run_id == run_id,
            RunManifest.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def record(
    db: AsyncSession,
    *,
    run_id: UUID,
    organization_id: UUID,
    payload: dict[str, Any],
    truncated: bool,
) -> RunManifest:
    """Write what this run sent, replacing anything already recorded for it.

    Replacing rather than inserting, because a parked run is finished twice: once
    when it stops on an approval and once when it is resumed and ends. The second
    recording is the one that describes the whole run, and a unique `run_id` means
    a blind insert would raise on precisely the runs somebody most wants to read.
    """
    existing = await get_by_run(db, run_id, organization_id)
    if existing is not None:
        existing.payload = payload
        existing.truncated = truncated
        await db.flush()
        await db.refresh(existing)
        return existing
    manifest = RunManifest(
        run_id=run_id,
        organization_id=organization_id,
        payload=payload,
        truncated=truncated,
    )
    db.add(manifest)
    await db.flush()
    await db.refresh(manifest)
    return manifest
