"""Deleting old activity cannot refund an improvement session's paid budget."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.repositories import improvement_repo, retention_repo
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.improvement_states import affordable
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _started

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def test_retirement_keeps_paid_cost_and_new_work_adds_to_it_once(db: AsyncSession) -> None:
    ctx, agent, _, session = await _started(db)
    now = datetime.now(UTC)
    old = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        improvement_run_id=session.id,
        status="completed",
        surface="eval",
        started_at=now - timedelta(days=30),
        cost_usd=Decimal("0.02"),
    )
    fresh = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        improvement_run_id=session.id,
        status="completed",
        surface="eval",
        started_at=now,
        cost_usd=Decimal("0.04"),
    )
    db.add_all([old, fresh])
    await db.flush()
    assert await improvement_repo.spent(
        db, session.id, organization_id=ctx.organization_id
    ) == Decimal("0.06")
    count, _ = await retention_repo.delete_runs_keeping_their_spend(
        db, organization_id=ctx.organization_id, cutoff=now - timedelta(days=1), limit=100
    )
    assert count == 1
    assert (
        await ImprovementPipelineService(db).read(ctx, agent.id, session.id)
    ).spent_usd == Decimal("0.06")
    again, _ = await retention_repo.delete_runs_keeping_their_spend(
        db, organization_id=ctx.organization_id, cutoff=now - timedelta(days=1), limit=100
    )
    assert again == 0
    db.add(
        AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            user_id=ctx.user_id,
            improvement_run_id=session.id,
            status="completed",
            surface="eval",
            started_at=now,
            cost_usd=Decimal("0.03"),
        )
    )
    await db.flush()
    total = await improvement_repo.spent(db, session.id, organization_id=ctx.organization_id)
    assert total == Decimal("0.09")
    assert not affordable(spent=total, step_estimate=Decimal("0.02"), budget=Decimal("0.10"))
    assert await improvement_repo.spent(db, session.id, organization_id=uuid4()) == 0


async def test_cost_archive_rolls_back_with_the_delete(db: AsyncSession) -> None:
    ctx, agent, _, session = await _started(db)
    now = datetime.now(UTC)
    old = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        improvement_run_id=session.id,
        status="completed",
        surface="eval",
        started_at=now - timedelta(days=30),
        cost_usd=Decimal("0.05"),
    )
    db.add(old)
    await db.flush()
    with pytest.raises(RuntimeError, match="rollback"):
        async with db.begin_nested():
            await retention_repo.delete_runs_keeping_their_spend(
                db, organization_id=ctx.organization_id, cutoff=now - timedelta(days=1), limit=100
            )
            raise RuntimeError("rollback")
    retained = await improvement_repo.get_run(db, session.id, organization_id=ctx.organization_id)
    assert retained is not None and retained.archived_cost_usd == 0
    assert await improvement_repo.spent(
        db, session.id, organization_id=ctx.organization_id
    ) == Decimal("0.05")
