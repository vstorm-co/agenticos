"""Saved profile rates round-trip through Postgres and remain tenant-scoped."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import credential_repo
from app.schemas.model_profile import ModelProfileRead, ModelProfileUpdate
from app.schemas.token_pricing import TokenPricing
from app.services.model_profile import ModelProfileService

pytestmark = pytest.mark.anyio


async def tenant(db: AsyncSession) -> AuthContext:
    owner = User(email=f"{uuid4()}@example.test", is_active=True)
    db.add(owner)
    await db.flush()
    org = Organization(name="Pricing", slug=f"pricing-{uuid4()}", created_by_user_id=owner.id)
    db.add(org)
    await db.flush()
    return AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def test_prices_persist_resolve_and_return_to_automatic_without_affecting_another_profile(
    db: AsyncSession,
) -> None:
    ctx = await tenant(db)
    first = TokenPricing(input="0", output="2", cache_read="0")
    second = TokenPricing(input="3", output="4")
    profiles = [
        await credential_repo.create_profile(
            db,
            organization_id=ctx.organization_id,
            label=f"Profile {index}",
            provider="ollama",
            model="alias",
            secret_id=None,
            base_url="http://localhost:11434/v1",
            runs_without_key=True,
            custom_pricing=rates.model_dump(mode="json"),
        )
        for index, rates in enumerate([first, second])
    ]
    service = ModelProfileService(db)
    before = await service.resolve(ctx, profile_id=profiles[0].id)
    assert before.credential.custom_pricing == first
    assert before.credential.profile_id == profiles[0].id
    assert ModelProfileRead.model_validate(profiles[0]).custom_pricing == first
    await service.update_profile(ctx, profiles[0].id, ModelProfileUpdate(custom_pricing=second))
    after = await service.resolve(ctx, profile_id=profiles[0].id)
    assert after.credential.custom_pricing == second
    assert before.credential.custom_pricing == first
    await service.update_profile(ctx, profiles[0].id, ModelProfileUpdate(custom_pricing=None))
    assert (await service.resolve(ctx, profile_id=profiles[0].id)).credential.custom_pricing is None
    assert (
        await service.resolve(ctx, profile_id=profiles[1].id)
    ).credential.custom_pricing == second
    other = await tenant(db)
    with pytest.raises(NotFoundError):
        await service.update_profile(
            other, profiles[1].id, ModelProfileUpdate(custom_pricing=first)
        )
    assert (
        await service.resolve(ctx, profile_id=profiles[1].id)
    ).credential.custom_pricing == second


async def test_keyless_profile_cost_counts_in_organization_reports_and_budget_enforcement(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from pydantic_ai.models.test import TestModel as PydanticTestModel
    from pydantic_ai.usage import RequestUsage

    from app.agents.capabilities.budget import BudgetExceeded, SpendLedger
    from app.agents.profile_pricing import ProfilePricingModel
    from app.db.models.agent import Agent
    from app.db.models.agent_run import AgentRun
    from app.services.spend import assert_organization_within_budget, organization_monthly_spend

    ctx = await tenant(db)
    usage = RequestUsage(input_tokens=1_000_000)
    model = ProfilePricingModel(PydanticTestModel(), TokenPricing(input="2", output="0"), None)
    model.apply(usage)
    ledger = SpendLedger()
    ledger.record("self-hosted-alias", usage, "ollama")
    agent = Agent(organization_id=ctx.organization_id, name="House", slug="house")
    db.add(agent)
    await db.flush()
    run = AgentRun(
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        surface="web",
        status="completed",
        started_at=datetime.now(UTC),
        secret_id=None,
        cost_usd=ledger.total_usd,
    )
    db.add(run)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    org.monthly_budget_usd = Decimal("1")
    await db.flush()
    assert await organization_monthly_spend(db, ctx.organization_id) == Decimal("2")
    with pytest.raises(BudgetExceeded) as refused:
        await assert_organization_within_budget(db, ctx.organization_id)
    assert refused.value.spent_usd == ledger.total_usd
