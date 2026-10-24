"""Counterfactual resource bodies add to the estimate before a paid check starts."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBody
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.eval_run import ArmRole, ArmSource
from app.services.eval_run import ArmPlan, EvalRunService

pytestmark = pytest.mark.anyio


async def test_a_projected_body_is_priced_as_additional_input_on_its_actual_model():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = EvalRunService(AsyncMock(spec=AsyncSession))
    profile = uuid4()
    arm = ArmPlan(
        role=ArmRole.CANDIDATE,
        source=ArmSource.EXPLICIT,
        version=None,
        spec=AgentSpec(name="Clerk"),
        model_profile_id=profile,
        model_label="model",
        skill_bodies={
            uuid4(): SkillBody(name="procedure", description="Procedure", content="A" * 2000)
        },
    )
    resolve = AsyncMock(return_value=SimpleNamespace(model="priced-model", provider="openai"))
    with (
        patch.object(service.models, "resolve", resolve),
        patch("app.services.eval_run.price_request", return_value=0.002) as price,
    ):
        assert await service._projected_input_cost(ctx, arm) == Decimal("0.002000")
        resolve.assert_awaited_once_with(ctx, profile_id=profile)
        usage = price.call_args.args[0]
        assert usage.input_tokens > 500 and usage.output_tokens == 0
    with (
        patch.object(service.models, "resolve", resolve),
        patch("app.services.eval_run.price_request", return_value=None),
    ):
        assert await service._projected_input_cost(ctx, arm) > 0


async def test_no_projection_adds_no_cost_and_an_unprofiled_body_uses_the_fallback():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = EvalRunService(AsyncMock(spec=AsyncSession))
    arm = ArmPlan(
        role=ArmRole.CANDIDATE,
        source=ArmSource.EXPLICIT,
        version=None,
        spec=AgentSpec(name="Clerk"),
        model_profile_id=None,
        model_label="model",
    )
    assert await service._projected_input_cost(ctx, arm) == 0
    from dataclasses import replace

    with_body = replace(
        arm, skill_bodies={uuid4(): SkillBody(description="Procedure", content="A" * 2000)}
    )
    assert await service._projected_input_cost(ctx, with_body) > 0


def test_retrieval_embeddings_and_repeats_are_visible_and_can_exhaust_the_budget():
    from app.schemas.eval_run import EvalRunEstimate, KnowledgeCheckRecord, ProposalCheckRecord

    estimate = EvalRunEstimate(
        cases=5,
        arms=[],
        judge_usd=Decimal(0),
        total_usd=Decimal("0.02"),
        rerun_ceiling_usd=Decimal("0.01"),
        agent_remaining_usd=Decimal("0.04"),
        org_remaining_usd=Decimal("0.04"),
        agent_after_usd=Decimal("0.01"),
        org_after_usd=Decimal("0.01"),
        affordable=True,
    )
    assert EvalRunService._knowledge_cost(estimate, None) is estimate
    record = ProposalCheckRecord(
        kind="context",
        base_version=None,
        suggestions=1,
        knowledge=KnowledgeCheckRecord(
            topic_id=uuid4(),
            draft_hash="x",
            mode="retrieval",
            supported=False,
            embedding_estimate_usd=Decimal("0.01"),
            embedding_rerun_ceiling_usd=Decimal("0.02"),
        ),
    )
    with_cost = EvalRunService._knowledge_cost(estimate, record)
    assert (with_cost.total_usd, with_cost.rerun_ceiling_usd) == (Decimal("0.03"), Decimal("0.03"))
    assert with_cost.agent_after_usd == with_cost.org_after_usd == Decimal("-0.02")
    assert not with_cost.affordable
    unlimited = estimate.model_copy(update={"agent_after_usd": None, "org_after_usd": None})
    assert EvalRunService._knowledge_cost(unlimited, record).affordable
