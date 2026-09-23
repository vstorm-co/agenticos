"""The run event stream: append, and the cursor `GET .../events` reads.

`WorkflowEvent.seq` is a per-run monotonic counter, incremented in the same
transaction as the insert - never a shared sequence, so a cursor for one run
stays small, dense and meaningless for another. The codec below is
`app.services.notification_center.encode_cursor`/`decode_cursor`'s shape,
reused rather than reinvented, with the run-scoped `seq` in place of a
timestamp tiebreak - there is nothing to tie-break here, since `seq` alone
already orders a run's events without ambiguity.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.workflow_run import WorkflowEvent, WorkflowRun
from app.repositories import workflow_run as workflow_run_repo


class EventKind:
    """Every `WorkflowEvent.kind` this package writes.

    A plain namespace, not an enum stored on the column - `kind` is a free
    string so a later issue's node kind does not need a migration to add one.
    """

    RUN_STARTED = "run_started"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    RUN_NEEDS_ATTENTION = "run_needs_attention"
    RUN_BUDGET_EXCEEDED = "run_budget_exceeded"
    NODE_DISPATCHED = "node_dispatched"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_WAITING = "node_waiting"
    NODE_UNCERTAIN = "node_uncertain"
    NODE_SKIPPED = "node_skipped"
    NODE_RETRYING = "node_retrying"
    ATTEMPT_RECLAIMED = "attempt_reclaimed"


async def append(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    kind: str,
    node_run_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowEvent:
    """Append one event to `run`'s stream, consuming its next `seq`.

    `run` must already be held from this transaction - the dispatcher and
    reconciler both row-lock it before doing anything else, so this never
    races another writer for the same run's counter.
    """
    return await workflow_run_repo.append_event(
        db, run=run, kind=kind, node_run_id=node_run_id, payload=payload or {}
    )


def encode_cursor(seq: int) -> str:
    """The opaque `next_cursor` `GET /workflow-runs/{id}/events` hands back."""
    return str(seq)


def decode_cursor(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise BadRequestError(message="Invalid pagination cursor", details={"cursor": raw}) from exc
