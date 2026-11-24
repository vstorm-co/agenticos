"""Serialize all capture kinds that can own one live browser view."""

import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingSession
from app.db.models.browser_teaching import BrowserTeachingSession


def _view_lock_key(organization_id: UUID, run_id: UUID, call_id: str) -> int:
    material = b"\0".join((organization_id.bytes, run_id.bytes, call_id.encode("utf-8")))
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


async def lock_view_and_check_active(
    db: AsyncSession, organization_id: UUID, run_id: UUID, call_id: str
) -> bool:
    """Take the transaction mutex, then check both active session tables.

    PostgreSQL partial indexes protect each table separately. The shared
    advisory lock supplies the cross-table exclusion so a quick capture and a
    procedure recording cannot both claim the same view in racing requests.
    """
    await db.execute(
        select(func.pg_advisory_xact_lock(_view_lock_key(organization_id, run_id, call_id)))
    )

    quick_active = await db.scalar(
        select(BrowserTeachingSession.id)
        .where(
            BrowserTeachingSession.organization_id == organization_id,
            BrowserTeachingSession.run_id == run_id,
            BrowserTeachingSession.call_id == call_id,
            BrowserTeachingSession.status.in_(("recording", "paused")),
        )
        .limit(1)
    )
    if quick_active is not None:
        return True

    procedure_active = await db.scalar(
        select(BrowserProcedureTeachingSession.id)
        .where(
            BrowserProcedureTeachingSession.organization_id == organization_id,
            BrowserProcedureTeachingSession.run_id == run_id,
            BrowserProcedureTeachingSession.call_id == call_id,
            BrowserProcedureTeachingSession.status.in_(("recording", "paused")),
        )
        .limit(1)
    )
    return procedure_active is not None
