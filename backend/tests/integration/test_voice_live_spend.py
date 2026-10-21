"""A live call's spend reaches every other run's budget check before the call ends (#54)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.spend import organization_monthly_spend

pytestmark = pytest.mark.anyio


@pytest.fixture
async def two_calls(db):
    """An organization with two calls running at once, neither one finished."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
        monthly_budget_usd=Decimal("1.00"),
    )
    db.add(organization)
    await db.flush()
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=user.id,
        name="Support",
        slug=f"support-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Support").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    runs = [
        AgentRun(
            id=uuid.uuid4(),
            organization_id=organization.id,
            agent_id=agent.id,
            status="running",
            modality="voice",
            started_at=datetime.now(UTC),
        )
        for _ in range(2)
    ]
    db.add_all(runs)
    await db.flush()
    return organization, runs


@pytest.mark.security
async def test_each_live_calls_spend_is_in_the_others_baseline(db, two_calls):
    """Two calls each spending $0.60 under a $1.00 cap must each see the other's $0.60."""
    organization, (first, second) = two_calls

    await agent_run_repo.record_live_cost(db, run_id=first.id, cost_usd=Decimal("0.60"))
    await agent_run_repo.record_live_cost(db, run_id=second.id, cost_usd=Decimal("0.60"))

    for own, other in ((first, second), (second, first)):
        baseline = await organization_monthly_spend(db, organization.id, exclude_run_id=own.id)
        assert baseline == Decimal("0.60"), other.id
        assert baseline + Decimal("0.60") >= organization.monthly_budget_usd


async def test_a_finished_runs_cost_is_never_rewritten_by_a_late_heartbeat(db, two_calls):
    _, (run, _) = two_calls
    run.status = "completed"
    run.cost_usd = Decimal("0.90")
    await db.flush()

    await agent_run_repo.record_live_cost(db, run_id=run.id, cost_usd=Decimal("0.40"))

    await db.refresh(run)
    assert run.cost_usd == Decimal("0.90")
