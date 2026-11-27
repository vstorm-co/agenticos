"""Independent published and pending budgets keep independent historical terms."""

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.currency import MonetaryTerm
from app.core.exceptions import NotFoundError
from app.db.models.agent import Agent, AgentVersion
from app.services import agent_registry
from app.services.agent_registry import AgentRegistryService
from tests.test_agent_registry import _ctx

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _spec(amount: int, *, foreign: bool) -> AgentSpec:
    return AgentSpec(
        name="Support",
        budget=BudgetSpec(
            monthly_usd=amount,
            monetary_terms={
                "monthly_usd": MonetaryTerm(
                    amount=Decimal(amount) * 4,
                    currency="PLN",
                    units_per_usd=4,
                    cost_usd=amount,
                )
            }
            if foreign
            else {},
        ),
    )


@pytest.mark.parametrize("published_exists", [False, True])
@pytest.mark.parametrize("incoming_usd", [20, 25])
async def test_separate_publication_keeps_each_versions_own_budget_terms(
    monkeypatch: pytest.MonkeyPatch, published_exists: bool, incoming_usd: int
) -> None:
    ctx = _ctx()
    published = _spec(incoming_usd, foreign=True)
    draft = _spec(3, foreign=True)
    agent = Agent(
        id=uuid4(),
        organization_id=ctx.organization_id,
        draft_spec=draft.model_dump(mode="json"),
        current_version_id=uuid4() if published_exists else None,
    )
    service = AgentRegistryService(AsyncMock(spec=AsyncSession))
    service.get = AsyncMock(return_value=agent)
    service.validate_spec = AsyncMock()
    frozen = AgentVersion(id=uuid4())
    service._freeze = AsyncMock(return_value=frozen)
    previous = _spec(20, foreign=False).model_copy(
        update={
            "budget": BudgetSpec(
                monthly_usd=20,
                monetary_terms={
                    "monthly_usd": MonetaryTerm(
                        amount=20, currency="USD", units_per_usd=1, cost_usd=20
                    )
                },
            )
        }
    )
    read = AsyncMock(return_value=AgentVersion(spec=previous.model_dump(mode="json")))
    monkeypatch.setattr(agent_registry.agent_repo, "get_version", read)
    result = await service.publish_spec(ctx, agent.id, published, draft=draft)
    assert result is frozen
    assert service._freeze.call_args.args[2] == published
    service.validate_spec.assert_awaited_once_with(ctx, published, agent_id=agent.id)
    assert service._freeze.call_args.kwargs["draft"].budget == draft.budget
    if published_exists:
        read.assert_awaited_once_with(
            service.db, agent.current_version_id, organization_id=ctx.organization_id
        )
    else:
        read.assert_not_awaited()


async def test_missing_published_version_cannot_rebase_budget_on_pending_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx()
    draft = _spec(3, foreign=True)
    agent = Agent(
        id=uuid4(),
        organization_id=ctx.organization_id,
        draft_spec=draft.model_dump(mode="json"),
        current_version_id=uuid4(),
    )
    service = AgentRegistryService(AsyncMock(spec=AsyncSession))
    service.get = AsyncMock(return_value=agent)
    service._freeze = AsyncMock()
    monkeypatch.setattr(agent_registry.agent_repo, "get_version", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="published version is missing"):
        await service.publish_spec(ctx, agent.id, _spec(20, foreign=True), draft=draft)
    service._freeze.assert_not_awaited()
    assert agent.draft_spec == draft.model_dump(mode="json")
