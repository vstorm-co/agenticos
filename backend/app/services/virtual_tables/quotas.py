"""What one organization may store in Virtual Tables, and the refusal when it would exceed it.

Three ceilings, all deployment settings and all per organization, so one tenant's usage
never counts against another's: how many tables it has, how many records one table
holds, and how large one record's values may be. The third also bounds what history and
receipts copy, since a create's snapshot, a delete's snapshot and a receipt's outcome
each hold one record at most and an update's history holds only the cells that changed.

A refusal is **audited without content**: the entry names the quota and its ceiling,
never a value. It is written in a session of its own that commits at once, because the
refused request's transaction rolls back and would take the entry with it - and a
refusal that leaves no trace is one nobody can see a tenant hitting.

The two counting quotas read a count and then let the caller insert, which two writers
can do at once and both pass at limit - 1. Each takes an advisory lock for the length of
the check, so the check and the insert are one step (`app.db.locks`).
"""

import json
from typing import NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.virtual_table import VirtualTable
from app.db.session import get_db_context
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import CellValue
from app.services.virtual_tables.exceptions import Quota, QuotaExceededError


def record_size(values: dict[str, CellValue]) -> int:
    """The serialized size of a record's values in bytes, as stored.

    Compact JSON, UTF-8 encoded: the size of what the record puts in a history row and
    a receipt, which is what the ceiling exists to bound.
    """
    return len(json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


async def refuse(
    ctx: AuthContext,
    *,
    quota: Quota,
    limit: int,
    message: str,
    target_id: UUID,
) -> NoReturn:
    """Audit the refusal in its own transaction, then raise it."""
    async with get_db_context() as audit_db:
        await record_audit(
            audit_db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.quota_refused",
            target_type="table" if quota != "tables" else "organization",
            target_id=str(target_id),
            details={"quota": quota, "limit": limit},
        )
    raise QuotaExceededError(quota=quota, limit=limit, message=message)


async def enforce_record_size(
    ctx: AuthContext, table: VirtualTable, values: dict[str, CellValue]
) -> None:
    """Refuse a record whose values are larger than the deployment allows."""
    limit = settings.TABLES_MAX_RECORD_BYTES
    if record_size(values) > limit:
        await refuse(
            ctx,
            quota="record_bytes",
            limit=limit,
            message=f"A record's values may take at most {limit} bytes",
            target_id=table.id,
        )


async def enforce_table_count(db: AsyncSession, ctx: AuthContext) -> None:
    """Refuse a new table when the organization already has as many as it may.

    Called with the organization's table-name lock held, which is what makes the count
    and the insert that follows it one step.
    """
    limit = settings.TABLES_MAX_PER_ORGANIZATION
    if await virtual_table_repo.count_tables(db, organization_id=ctx.organization_id) >= limit:
        await refuse(
            ctx,
            quota="tables",
            limit=limit,
            message=f"An organization may have at most {limit} tables, archived ones included",
            target_id=ctx.organization_id,
        )


async def enforce_record_count(db: AsyncSession, ctx: AuthContext, table: VirtualTable) -> None:
    """Refuse a new record when the table already holds as many as it may."""
    limit = settings.TABLES_MAX_RECORDS_PER_TABLE
    await hold_subject(db, LockScope.VIRTUAL_TABLE_RECORD_COUNT, table.id)
    held = await virtual_table_repo.count_records_up_to(
        db, table_id=table.id, organization_id=ctx.organization_id, ceiling=limit
    )
    if held >= limit:
        await refuse(
            ctx,
            quota="records",
            limit=limit,
            message=f"A table may hold at most {limit} records",
            target_id=table.id,
        )
