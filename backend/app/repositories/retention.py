"""The reads and hard deletes one retention sweep makes.

Every function here is scoped to one organization and one cutoff, because a sweep
is per-organization policy applied to one class at a time - and because a query
that spanned tenants would be one mistake away from purging under the wrong
policy. The exception is `organizations_with_data`, which is the sweep's own
"who is there to sweep" and reads ids only.

**Batched, and the batch is the point.** An organization arriving at a ninety-day
policy after two years has two years to remove, and one statement deleting a
million rows takes a lock for the length of it. Each delete takes the oldest
`limit` rows and answers how many it removed, so the caller loops until a pass
removes nothing - which also makes a sweep that is killed halfway simply resume,
rather than start again.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization
from app.db.models.purged_run_spend import PurgedRunSpend
from app.db.models.rag_document import RAGDocument

#: The statuses a retention sweep may retire.
#:
#: `running` is a row a live process still means to finalize and
#: `awaiting_approval` is somebody's pending decision; deleting either loses work
#: rather than retiring it. A short window reaches both first, which is exactly
#: when this matters.
_RETIRABLE = (
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.BUDGET_EXCEEDED,
    RunStatus.GUARDRAIL_BLOCKED,
)


async def organizations_with_retention(
    db: AsyncSession,
) -> list[tuple[UUID, dict[str, Any] | None]]:
    """Every organization and the retention it asked for, ids and policy only.

    The whole table rather than a filtered one: an organization that has set
    nothing still inherits the deployment's defaults, so "has a policy" is not a
    question this query can answer - only `effective_policy` can.
    """
    rows = await db.execute(select(Organization.id, Organization.retention_days))
    return [(row[0], row[1]) for row in rows.all()]


async def stored_paths_for_expiring_conversations(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> list[str]:
    """The chat files belonging to conversations about to be purged.

    Read before the delete, because the rows cascade with the conversation and the
    bytes do not: a purge that removed the row and left the upload on disk would
    be a retention policy whose files outlive the policy.
    """
    expiring = (
        select(Conversation.id)
        .where(Conversation.organization_id == organization_id, Conversation.updated_at < cutoff)
        .order_by(Conversation.updated_at)
        .limit(limit)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(ChatFile.storage_path)
        .join(Message, Message.id == ChatFile.message_id)
        .where(Message.conversation_id.in_(expiring), ChatFile.storage_path.is_not(None))
    )
    return [path for (path,) in rows.all() if path]


async def delete_conversations(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> int:
    """Drop the oldest conversations untouched since `cutoff`. Messages cascade.

    `updated_at`, not `created_at`: a thread somebody is still returning to is not
    old, however long ago it started, and a policy that deleted it mid-use would
    be measuring the wrong thing.
    """
    expiring = (
        select(Conversation.id)
        .where(Conversation.organization_id == organization_id, Conversation.updated_at < cutoff)
        .order_by(Conversation.updated_at)
        .limit(limit)
        .scalar_subquery()
    )
    result = cast(
        CursorResult[Any],
        await db.execute(delete(Conversation).where(Conversation.id.in_(expiring))),
    )
    return result.rowcount or 0


async def delete_runs_keeping_their_spend(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> tuple[int, list[tuple[datetime, Decimal, int]]]:
    """Delete the oldest finished runs and answer what they cost, atomically.

    **One statement, and that is the point.** Reading the costs and then deleting
    the rows lets two overlapping sweeps read the same batch: the first delete
    wins, the second removes nothing, and its additive upsert of the same figure
    stays - permanently inflating the month and the budget metered on it. A
    `DELETE ... RETURNING` cannot be read by a sweep that is not going to remove
    the row, so the figure kept is exactly the figure lost.

    **Only terminal runs.** `running` is a row a live process still means to
    finalize and `awaiting_approval` is somebody's pending decision; deleting
    either loses work rather than retiring it, and a short window reaches both
    first. Manifests and tool approvals cascade; a delegated child whose parent
    goes keeps its own row (`parent_run_id` is `SET NULL`) and is retired by its
    own age like any other run.

    Returns:
        How many rows went, and their cost grouped by the month they started in -
        **top-level runs only**, because a parent's `cost_usd` already contains
        what its delegates spent and the live billing query filters the children
        out for exactly that reason. Counting both would double-charge the work
        the moment retention removed it.
    """
    expiring = (
        select(AgentRun.id)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.started_at < cutoff,
            AgentRun.status.in_(_RETIRABLE),
        )
        .order_by(AgentRun.started_at)
        .limit(limit)
        .scalar_subquery()
    )
    removed = await db.execute(
        delete(AgentRun)
        .where(AgentRun.id.in_(expiring))
        .returning(AgentRun.started_at, AgentRun.cost_usd, AgentRun.parent_run_id)
    )
    rows = removed.all()

    by_month: dict[datetime, tuple[Decimal, int]] = {}
    for started_at, cost, parent_run_id in rows:
        if parent_run_id is not None:
            continue
        period = started_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total, count = by_month.get(period, (Decimal(0), 0))
        by_month[period] = (total + Decimal(cost or 0), count + 1)
    return len(rows), [(period, total, count) for period, (total, count) in by_month.items()]


async def record_purged_spend(
    db: AsyncSession, *, organization_id: UUID, period_start: datetime, cost: Decimal, runs: int
) -> None:
    """Add a purged month's total to what is already kept for that month.

    An upsert that *adds*, because a sweep purges in batches and a month is
    reached by several of them - a replace would leave the month holding whatever
    the last batch happened to contain.
    """
    statement = insert(PurgedRunSpend).values(
        organization_id=organization_id,
        period_start=period_start,
        cost_usd=cost,
        run_count=runs,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="purged_run_spend_period_key",
            set_={
                "cost_usd": PurgedRunSpend.cost_usd + statement.excluded.cost_usd,
                "run_count": PurgedRunSpend.run_count + statement.excluded.run_count,
            },
        )
    )


async def sum_purged_cost_since(
    db: AsyncSession, *, organization_id: UUID, since: datetime
) -> Decimal:
    """What purged runs spent in months at or after `since`.

    The grain is a month, so a window starting mid-month counts the whole month
    it starts in. That is the honest answer available: the runs are gone, and
    under-reporting a cap's baseline is the worse error of the two.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(PurgedRunSpend.cost_usd), 0)).where(
            PurgedRunSpend.organization_id == organization_id,
            PurgedRunSpend.period_start
            >= since.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        )
    )
    return Decimal(total or 0)


async def delete_workspaces(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> int:
    """Drop the oldest workspaces unused since `cutoff`.

    For the `state` backend the row is the storage, so this is the whole purge.
    A workspace on a sandbox backend keeps its files in the sandbox, whose own
    TTL reaps them; what leaves here is the platform's record of it.
    """
    expiring = (
        select(AgentWorkspace.id)
        .where(
            AgentWorkspace.organization_id == organization_id, AgentWorkspace.last_used_at < cutoff
        )
        .order_by(AgentWorkspace.last_used_at)
        .limit(limit)
        .scalar_subquery()
    )
    result = cast(
        CursorResult[Any],
        await db.execute(delete(AgentWorkspace).where(AgentWorkspace.id.in_(expiring))),
    )
    return result.rowcount or 0


async def delete_memory(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> int:
    """Drop the oldest memory files untouched since `cutoff`.

    `updated_at` again, and it matters more here than anywhere: a memory file is
    written once and read for months, so an age measured from creation would
    delete precisely the notes an agent relies on most.
    """
    expiring = (
        select(AgentMemoryFile.id)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.updated_at < cutoff,
        )
        .order_by(AgentMemoryFile.updated_at)
        .limit(limit)
        .scalar_subquery()
    )
    result = cast(
        CursorResult[Any],
        await db.execute(delete(AgentMemoryFile).where(AgentMemoryFile.id.in_(expiring))),
    )
    return result.rowcount or 0


async def expiring_documents(
    db: AsyncSession, *, organization_id: UUID, cutoff: datetime, limit: int
) -> list[tuple[UUID, str, str | None, str | None]]:
    """Uploaded documents past their window: id, collection, vector id, file.

    **`source_path IS NULL` is the whole of the synchronization answer.** A
    document a connector put there is that source's to remove - purging it here
    would delete a row the next `new_only` sync recreates from the same unchanged
    file, which is a sweep that burns embedding spend to no effect. What is swept
    is what somebody uploaded, whose lifetime nothing else owns.
    """
    rows = await db.execute(
        select(
            RAGDocument.id,
            RAGDocument.collection_name,
            RAGDocument.vector_document_id,
            RAGDocument.storage_path,
        )
        .where(
            RAGDocument.organization_id == organization_id,
            RAGDocument.created_at < cutoff,
            RAGDocument.source_path.is_(None),
        )
        .order_by(RAGDocument.created_at)
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows.all()]


async def delete_documents(db: AsyncSession, *, document_ids: list[UUID]) -> int:
    """Drop exactly the document rows whose vectors and files were dealt with.

    Never called with an empty list: the caller reads the batch first and returns
    before this if there was nothing in it.
    """
    result = cast(
        CursorResult[Any],
        await db.execute(delete(RAGDocument).where(RAGDocument.id.in_(document_ids))),
    )
    return result.rowcount or 0


async def set_retention(
    db: AsyncSession, *, organization: Organization, retention_days: dict[str, int | None]
) -> Organization:
    """Store what this organization asks to keep, per class."""
    organization.retention_days = retention_days
    await db.flush()
    await db.refresh(organization)
    return organization
