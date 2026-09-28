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
Two racing starts can both read below a ceiling and both be admitted, the same
boundary overshoot the fixed-window rate limiter accepts; the ceiling is a
defensive bound on sustained abuse, not an exact quota.
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
    headroom by racing under their own. A start with no principal (a triggered
    run acting as no interactive caller) is bounded by the organization ceiling
    alone.

    Raises:
        WorkflowAdmissionQuotaError: Admitting this run would exceed the
            organization's or the caller's outstanding-node-work ceiling.
    """
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
        db, organization_id=organization_id, principal_user_id=principal_user_id
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
