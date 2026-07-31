"""Agent run and approval repositories (PostgreSQL async)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization_secret import OrganizationSecret


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID | None,
    user_id: UUID | None,
    conversation_id: UUID | None,
    surface: str,
    model_label: str | None,
    started_at: datetime,
    exposure_id: UUID | None = None,
    environment_id: UUID | None = None,
    provider: str | None = None,
    secret_id: UUID | None = None,
) -> AgentRun:
    run = AgentRun(
        organization_id=organization_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        user_id=user_id,
        conversation_id=conversation_id,
        exposure_id=exposure_id,
        environment_id=environment_id,
        surface=surface,
        model_label=model_label,
        provider=provider,
        secret_id=secret_id,
        status=RunStatus.RUNNING.value,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def finish_run(
    db: AsyncSession,
    *,
    run: AgentRun,
    status: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    cost_is_partial: bool,
    ended_at: datetime,
    error: str | None = None,
    logfire_trace_id: str | None = None,
    paused_state: dict[str, Any] | None = None,
) -> AgentRun:
    run.status = status
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.cost_usd = cost_usd
    run.cost_is_partial = cost_is_partial
    run.ended_at = ended_at
    run.error = error
    # Written on every finish, not only when parking: a run that ended must not
    # keep the state it was parked with, or it can be resumed a second time.
    run.paused_state = paused_state
    if logfire_trace_id is not None:
        run.logfire_trace_id = logfire_trace_id
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> AgentRun | None:
    result = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def claim_parked_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> AgentRun | None:
    """Read a run and hold its row for the rest of the transaction.

    Resuming replays a side-effecting tool call, so two requests arriving
    together - a double-clicked Approve - must not both replay it. The second
    waits here and then finds the run no longer parked.
    """
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def mark_running(db: AsyncSession, *, run: AgentRun) -> AgentRun:
    """Take a parked run out of the queue before replaying it."""
    run.status = RunStatus.RUNNING.value
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentRun], int]:
    query = select(AgentRun).where(AgentRun.organization_id == organization_id)
    count_query = select(func.count(AgentRun.id)).where(AgentRun.organization_id == organization_id)
    if agent_id is not None:
        query = query.where(AgentRun.agent_id == agent_id)
        count_query = count_query.where(AgentRun.agent_id == agent_id)

    query = query.order_by(AgentRun.started_at.desc().nullslast()).offset(skip).limit(limit)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def sum_cost_since(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    agent_id: UUID | None = None,
) -> Decimal:
    """Total run spend in a window - what a monthly budget is checked against.

    `agent_id` narrows the sum to one agent's runs, because the agent's cap has
    to be measured against the spend it is a cap *on*: checked against the
    organization's total it would be exhausted by the neighbours' runs while
    the agent's own spend stayed invisible in it.
    """
    query = select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(
        AgentRun.organization_id == organization_id,
        AgentRun.started_at >= since,
    )
    if agent_id is not None:
        query = query.where(AgentRun.agent_id == agent_id)
    result = await db.scalar(query)
    return Decimal(result or 0)


async def cost_breakdown(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
) -> list[tuple[UUID, str | None, Decimal, int]]:
    """Spend grouped by agent - the cost dashboard's main query.

    Returns (agent_id, model_label, total_cost, run_count) rows.
    """
    result = await db.execute(
        select(
            AgentRun.agent_id,
            AgentRun.model_label,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.started_at >= since,
        )
        .group_by(AgentRun.agent_id, AgentRun.model_label)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    return [(row[0], row[1], Decimal(row[2]), row[3]) for row in result.all()]


async def spend_by_provider(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
) -> list[tuple[str | None, Decimal, int]]:
    """Spend grouped by model provider - "what did we spend at OpenAI".

    Reads the provider recorded *on the run*, not the one its model profile
    points at today: a repointed profile would otherwise rewrite what last
    month appears to have cost. Runs from before this was recorded group under
    NULL, which the caller renders as "not recorded" rather than as a provider.
    """
    result = await db.execute(
        select(
            AgentRun.provider,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .where(AgentRun.organization_id == organization_id, AgentRun.started_at >= since)
        .group_by(AgentRun.provider)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    return [(row[0], Decimal(row[1]), row[2]) for row in result.all()]


async def spend_by_key(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
) -> list[tuple[UUID | None, str | None, Decimal, int]]:
    """Spend grouped by the stored key that paid for it.

    Left-joined, so a key deleted after it was used still shows its spend under
    a null label rather than dropping the rows: the money was spent whether or
    not the key still exists.
    """
    result = await db.execute(
        select(
            AgentRun.secret_id,
            OrganizationSecret.name,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .join(OrganizationSecret, OrganizationSecret.id == AgentRun.secret_id, isouter=True)
        .where(AgentRun.organization_id == organization_id, AgentRun.started_at >= since)
        .group_by(AgentRun.secret_id, OrganizationSecret.name)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    return [(row[0], row[1], Decimal(row[2]), row[3]) for row in result.all()]


async def create_approval(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    agent_id: UUID,
    tool_id: str,
    tool_args: dict,
) -> ToolApproval:
    approval = ToolApproval(
        organization_id=organization_id,
        run_id=run_id,
        agent_id=agent_id,
        tool_id=tool_id,
        tool_args=tool_args,
    )
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return approval


async def get_approval(
    db: AsyncSession, approval_id: UUID, *, organization_id: UUID
) -> ToolApproval | None:
    result = await db.execute(
        select(ToolApproval).where(
            ToolApproval.id == approval_id,
            ToolApproval.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_pending_approvals(
    db: AsyncSession, *, organization_id: UUID, skip: int = 0, limit: int = 50
) -> tuple[list[ToolApproval], int]:
    query = (
        select(ToolApproval)
        .where(
            ToolApproval.organization_id == organization_id,
            ToolApproval.status == ApprovalStatus.PENDING.value,
        )
        .order_by(ToolApproval.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    count_query = select(func.count(ToolApproval.id)).where(
        ToolApproval.organization_id == organization_id,
        ToolApproval.status == ApprovalStatus.PENDING.value,
    )
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def list_approvals_for_run(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID
) -> list[ToolApproval]:
    """Every approval raised by one run, oldest first - what a resume checks."""
    result = await db.execute(
        select(ToolApproval)
        .where(
            ToolApproval.run_id == run_id,
            ToolApproval.organization_id == organization_id,
        )
        .order_by(ToolApproval.created_at.asc())
    )
    return list(result.scalars().all())


async def decide_approval(
    db: AsyncSession,
    *,
    approval: ToolApproval,
    status: str,
    decided_by_user_id: UUID,
    decided_at: datetime,
    note: str | None = None,
) -> ToolApproval:
    approval.status = status
    approval.decided_by_user_id = decided_by_user_id
    approval.decided_at = decided_at
    approval.note = note
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return approval
