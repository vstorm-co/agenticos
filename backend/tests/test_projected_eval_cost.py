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


@pytest.mark.security
def test_retrieval_embeddings_and_repeats_are_visible_and_can_exhaust_the_budget():
    from app.schemas.eval_run import EvalRunEstimate, KnowledgeCheckRecord, ProposalCheckRecord

    estimate = EvalRunEstimate(
        cases=5,
        arms=[],
        judge_usd=Decimal(0),
        total_usd=Decimal("0.02"),
        rerun_ceiling_usd=Decimal("0.01"),
        expected_usd=Decimal("0.025"),
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
    # The embeddings are spent, and their repeats in the share reruns usually ask.
    assert with_cost.expected_usd == Decimal("0.025") + Decimal("0.01") + Decimal("0.01")
    assert with_cost.agent_after_usd == with_cost.org_after_usd == Decimal("-0.02")
    assert not with_cost.affordable
    unlimited = estimate.model_copy(update={"agent_after_usd": None, "org_after_usd": None})
    assert EvalRunService._knowledge_cost(unlimited, record).affordable


@pytest.mark.parametrize("cached", [False, True])
def test_replacement_prices_freeze_each_model_and_its_judge_share(cached):
    from app.schemas.eval_run import ArmEstimate, EvalRunEstimate, ProposalCheckRecord

    prices = [Decimal("0.1"), Decimal("3.9")]
    arms = [
        ArmEstimate(
            role=ArmRole.CANDIDATE,
            source=ArmSource.EXPLICIT,
            version_number=None,
            model_profile_id=uuid4(),
            model_label=str(price),
            cost_per_case_usd=price,
            cost_usd=price * 2,
            basis="history",
        )
        for price in prices
    ]
    if cached:
        arms.append(
            arms[0].model_copy(
                update={"basis": "cached", "cost_per_case_usd": Decimal(0), "cost_usd": Decimal(0)}
            )
        )
    estimate = EvalRunEstimate(
        cases=2,
        arms=arms,
        judge_usd=Decimal("0.8"),
        total_usd=Decimal("8.8"),
        rerun_ceiling_usd=Decimal(1),
        expected_usd=Decimal("9.3"),
        agent_remaining_usd=None,
        org_remaining_usd=None,
        agent_after_usd=None,
        org_after_usd=None,
        affordable=True,
    )
    record = ProposalCheckRecord(kind="agent", base_version=None, suggestions=1)
    assert not record.answer_estimates_usd
    assert EvalRunService._priced_check(None, estimate) is None
    priced = EvalRunService._priced_check(record, estimate)
    assert priced is not None
    assert priced.answer_estimates_usd == [
        Decimal("0.3"),
        Decimal("4.1"),
        *([Decimal(0)] if cached else []),
    ]
    assert ProposalCheckRecord.model_validate_json(priced.model_dump_json()) == priced
    empty = estimate.model_copy(update={"arms": [], "cases": 0})
    assert EvalRunService._priced_check(record, empty) == record


def test_stored_replacement_prices_cannot_be_negative():
    from pydantic import ValidationError

    from app.schemas.eval_run import ProposalCheckRecord

    with pytest.raises(ValidationError):
        ProposalCheckRecord(
            kind="agent", base_version=None, suggestions=1, answer_estimates_usd=[Decimal("-1")]
        )
