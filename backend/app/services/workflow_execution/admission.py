"""Admission quota: bound queued and running node work per organization and caller.

The per-minute run limit (`deps.limit_workflow_run`) charges one token per start,
which lets an authenticated caller start many wide graphs below the rate limit and
grow a persistent backlog on the runner shared with ingestion, triggers, approvals
and notifications - starving other tenants (#1907). This module charges by node
work instead: each start reserves its graph's node count against a ceiling on the
outstanding (queued or running) node work an organization, and a caller within it,
may hold at once, and refuses a start that would exceed it.

The reservation is durable, not just checked at the instant of admission: a run
stamps its whole graph node count on its row, and the ceiling is measured
against the sum of those counts over the organization's live runs. A wide graph
therefore holds its whole reservation from the moment it is admitted - not only
its single entry node, the one row that exists before the graph fans out - so
many wide graphs cannot slip in before their work materializes. The count is
authoritative (Postgres, not a Redis gauge a lost decrement would drift), and a
run that reaches a terminal status frees its reservation with no bookkeeping.
Concurrent starts are serialized by transaction-scoped advisory locks (per
organization, and per principal across organizations) taken before the sums are
read, so each check and its reservation are atomic and neither ceiling can be
overshot by racing reads.

A loop does not widen the reservation. `control.foreach` runs its body one
iteration at a time - the next is scheduled only once the one before has
settled - and a step fans out through one edge per port, so a run's outstanding
node work never exceeds its graph's node count, however many iterations it
takes in all. That total is bounded separately, by `WORKFLOW_RUN_MAX_NODE_RUNS`.

Cancelling a run releases its reservation the moment it goes terminal, before an
attempt already executing has settled. That does not reopen the backlog this
bounds: `cancel` drains every pending and claimed outbox row, `begin_attempt`
refuses to start a new attempt on a terminal run, and `settle` short-circuits
without enqueuing successors - so no new queued work appears. The one attempt
still in flight is bounded by `PREFECT_RUNNER_LIMIT` (global concurrency), and
how fast start-then-cancel can be cycled is bounded by the per-minute run limit.
So the queue-depth guarantee holds; only in-flight concurrency, already capped
elsewhere, is briefly held past a cancel.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution.exceptions import WorkflowAdmissionQuotaError


async def enforce_admission_quota(
    db: AsyncSession,
    *,
    organization_id: UUID,
    principal_user_id: UUID | None,
    requested_node_count: int,
) -> None:
    """Refuse a start that would push outstanding node work past a ceiling.

    Reserves `requested_node_count` - the run's graph node count, its worst-case
    node work - against the organization's ceiling first, then the caller's. The
    organization is checked first so one caller cannot spend another tenant's
    headroom by racing under their own. The caller's ceiling is counted across
    *every* organization, not just this one: on a deployment that lets a signed-in
    user create organizations, an org-scoped principal check would hand them a
    fresh allowance in each. A start with no principal (a triggered run acting as
    no interactive caller) is bounded by the organization ceiling alone.

    Raises:
        WorkflowAdmissionQuotaError: Admitting this run would exceed the
            organization's or the caller's outstanding-node-work ceiling.
    """
    # Serialize admission first: each check reads a sum and then a new run is
    # inserted, so without this two concurrent starts could both read below a
    # ceiling and both be admitted. The locks (per organization, and per
    # principal across organizations) are held to the request's commit, by which
    # point this run's reservation is visible.
    await workflow_run_repo.lock_admission(
        db, organization_id=organization_id, principal_user_id=principal_user_id
    )
    org_outstanding = await workflow_run_repo.sum_reserved_node_work(
        db, organization_id=organization_id
    )
    if org_outstanding + requested_node_count > settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG:
        raise WorkflowAdmissionQuotaError(
            scope="organization",
            limit=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG,
            outstanding=org_outstanding,
            requested=requested_node_count,
        )
    if principal_user_id is None:
        return
    principal_outstanding = await workflow_run_repo.sum_reserved_node_work(
        db, principal_user_id=principal_user_id
    )
    if (
        principal_outstanding + requested_node_count
        > settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_PRINCIPAL
    ):
        raise WorkflowAdmissionQuotaError(
            scope="principal",
            limit=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_PRINCIPAL,
            outstanding=principal_outstanding,
            requested=requested_node_count,
        )
