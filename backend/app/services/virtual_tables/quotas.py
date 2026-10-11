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

import asyncio
import json
import weakref
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.virtual_table import VirtualTable
from app.db.session import get_worker_db_context
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import CellValue
from app.services.virtual_tables.exceptions import Quota, QuotaExceededError


def record_size(values: dict[str, CellValue]) -> int:
    """The serialized size of a record's values in bytes, as stored.

    Compact JSON, UTF-8 encoded: the size of what the record puts in a history row and
    a receipt, which is what the ceiling exists to bound.
    """
    return len(json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def delete_snapshot(values: dict[str, Any]) -> dict[str, Any]:
    """What a delete's history row keeps of the record: its values, or a bounded marker.

    The record limit caps what a create and an update can write, but a record that predates
    the limit, or was written before `TABLES_MAX_RECORD_BYTES` was lowered, can be larger than
    it. Copying it whole would put an oversized snapshot in history on the way out, so an
    over-limit record is replaced by `{"omitted": {"bytes": <its size>, "limit": <the limit>}}`.
    A key `omitted` cannot be a column id, so it cannot be mistaken for a value. The delete
    itself is never refused for this.
    """
    size = record_size(values)
    limit = settings.TABLES_MAX_RECORD_BYTES
    if size <= limit:
        return dict(values)
    return {"omitted": {"bytes": size, "limit": limit}}


# One gate per event loop, for the reason `app/core/blocking.py` keys its own limiter
# that way: an `asyncio.Semaphore` binds to the loop that created it, and a worker or a
# test suite may run more than one loop in a process. Keyed weakly so a finished loop's
# gate is collected with it.
#
# `get_worker_db_context` moved the audit connection off the request's pool, which fixed
# the pool-drain deadlock but left it unbounded: a burst of refusals each opens a live
# `NullPool` connection, multiplied by every worker process, and same-organization audits
# then queue on `record_audit`'s advisory chain lock while holding those connections open.
# `TABLES_MAX_CONCURRENT_QUOTA_AUDITS` bounds it, the same shape `app/core/blocking.py`
# and `app/services/ml/parsing.py` bound their own pools of concurrent work with, at the
# scale of an occasional refusal instead of a file or a parse.
_audit_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _audit_gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _audit_gates.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(settings.TABLES_MAX_CONCURRENT_QUOTA_AUDITS)
        _audit_gates[loop] = gate
    return gate


async def refuse(
    ctx: AuthContext,
    *,
    quota: Quota,
    limit: int,
    message: str,
    target_id: UUID,
) -> NoReturn:
    """Audit the refusal in its own transaction, then raise it.

    The session comes from `get_worker_db_context`, which connects on a `NullPool` engine of
    its own, and not from `get_db_context`: on the API's loop that one draws from the same pool
    as the request that is being refused, which already holds a connection. With the default
    pool, that many concurrent refusals each hold one and wait for a second until the pool
    timeout, and answer 500 instead of `QUOTA_EXCEEDED` (the circular wait `vector_engine` was
    added to avoid). A refusal is rare and a connect is cheap beside the request around it.

    `_audit_gate` bounds how many of these connections exist at once: unbounded, a large
    burst opens one live connection per refused request, and same-organization audits then
    queue on the audit chain's advisory lock while holding them. The rest of a burst waits on
    the semaphore instead, holding nothing.
    """
    async with _audit_gate(), get_worker_db_context() as audit_db:
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


async def lock_record_count(db: AsyncSession, table: VirtualTable) -> None:
    """Take turns with every other create into this table, until the transaction ends.

    Re-entrant within one transaction. An upsert takes it *before* deciding whether its
    external id exists, so that a concurrent upsert of the same new id has committed by the
    time it looks: the loser then sees the winner's row and updates it instead of counting a
    table its rival just filled and being refused for it.
    """
    await hold_subject(db, LockScope.VIRTUAL_TABLE_RECORD_COUNT, table.id)


async def enforce_record_count(db: AsyncSession, ctx: AuthContext, table: VirtualTable) -> None:
    """Refuse a new record when the table already holds as many as it may."""
    limit = settings.TABLES_MAX_RECORDS_PER_TABLE
    await lock_record_count(db, table)
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
