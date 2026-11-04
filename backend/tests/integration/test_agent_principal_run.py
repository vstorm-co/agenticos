"""A whole run as the agent itself, against a real database.

A customer who never linked an account is answered by the agent with no member behind
the turn. These drive the real runner and real rows, because what must hold is
end to end: the run row names no member, the agent's own spend is what is metered, and
a run with no spending limit is refused before a model is reached - on the turn and on
a continuation a member decides.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.agents.capabilities.workflows import _toolset as workflows_toolset
from app.agents.capabilities.workflows._toolset import build_workflows_toolset
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import NoSpendingLimitError
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Conversation
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.repositories import agent_run as agent_run_repo
from app.services.access import agent_context, publisher_context
from app.services.agent_runner import AgentRunnerService
from app.services.channel_bot import seal_bot_token
from app.services.channels.continuation import continue_in_chat
from app.services.channels.handback import REFUSED_NOTICE
from app.services.channels.router import Admission
from app.worker.jobs import DELIVER_CHANNEL_HANDBACK
from tests.integration.test_decisions_reach_chat import _context_on
from tests.integration.test_platform_flows import (
    Tenant,
    _answer,
    _keyed_model_profile,
    _published_agent,
    _tenant,
)

pytestmark = pytest.mark.anyio


async def _agent_under(db, tenant: Tenant, *, spec: AgentSpec):
    """A published agent, committed, and the context that is the agent itself."""
    await _keyed_model_profile(db, tenant)
    agent = await _published_agent(db, tenant, spec=spec)
    await db.commit()
    ctx = agent_context(organization_id=tenant.organization.id, agent_id=agent.id)
    return agent, ctx


class _NoSession:
    """A stand-in for `get_db_context`: a session nothing is read through."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def _runs_of(db, agent_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent_id)
        )
    ).scalar_one()


class TestARunAsTheAgent:
    async def test_a_run_as_the_agent_answers_with_knowledge_and_records_no_member(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        name = f"kb_{uuid.uuid4().hex[:8]}"
        knowledge = KnowledgeBase(
            id=uuid.uuid4(),
            name=name,
            scope=KBScope.ORG.value,
            collection_name=name,
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_provider="openrouter",
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            visibility="org",
        )
        db.add(knowledge)
        await db.flush()
        agent, ctx = await _agent_under(
            db, tenant, spec=AgentSpec(name="Support", collection_ids=[knowledge.id])
        )

        service = AgentRunnerService(db)
        prepared = await service.prepare(
            ctx, agent.id, surface=RunSurface.WHATSAPP, acts_for_sender=True
        )

        assert prepared.deps.kb_collection_names == [name]
        assert prepared.deps.user_id is None
        assert prepared.deps.run_person is None
        assert await _answer(prepared) == "thirty days"
        # What the model run spent: a million input tokens at gpt-4.1's price.
        prepared.built.ledger.record("gpt-4.1", RequestUsage(input_tokens=1_000_000), "openai")
        run_id = prepared.run.id
        await service.finish(prepared, status=RunStatus.COMPLETED)
        await db.commit()
        run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        assert run.user_id is None
        assert run.runs_as_agent is True
        assert run.initiated_by_publisher_fallback is True
        since = datetime(2000, 1, 1, tzinfo=UTC)
        spent = await agent_run_repo.sum_cost_since(
            db, organization_id=tenant.organization.id, since=since, agent_id=agent.id
        )
        assert run.cost_usd == Decimal("2.00")
        assert spent == Decimal("2.00")
        assert (
            await agent_run_repo.sum_cost_since(
                db, organization_id=tenant.organization.id, since=since
            )
            == spent
        )

    @pytest.mark.security
    async def test_it_is_refused_before_the_model_with_no_spending_limit(self, db) -> None:
        tenant = await _tenant(db, name="Unbounded")
        agent, ctx = await _agent_under(db, tenant, spec=AgentSpec(name="Support"))

        with (
            patch("app.services.agent_runner.build_agent") as build,
            pytest.raises(NoSpendingLimitError) as refused,
        ):
            await AgentRunnerService(db).prepare(ctx, agent.id, surface=RunSurface.WHATSAPP)

        build.assert_not_called()
        assert refused.value.message == "This line is not answering right now."
        assert refused.value.code == "NO_SPENDING_LIMIT"
        assert refused.value.details == {"agent_id": str(agent.id)}
        assert await _runs_of(db, agent.id) == 0

    @pytest.mark.security
    async def test_an_agent_budget_alone_is_enough(self, db) -> None:
        tenant = await _tenant(db, name="Agent budget")
        agent, ctx = await _agent_under(
            db, tenant, spec=AgentSpec(name="Support", budget={"monthly_usd": 5})
        )

        prepared = await AgentRunnerService(db).prepare(ctx, agent.id, surface=RunSurface.WHATSAPP)

        assert await _answer(prepared) == "thirty days"

    async def test_an_org_cap_alone_is_enough(self, db) -> None:
        tenant = await _tenant(db, name="Org cap", monthly_budget_usd=Decimal("20"))
        agent, ctx = await _agent_under(db, tenant, spec=AgentSpec(name="Support"))

        prepared = await AgentRunnerService(db).prepare(ctx, agent.id, surface=RunSurface.WHATSAPP)

        assert await _answer(prepared) == "thirty days"

    @pytest.mark.security
    async def test_a_run_under_the_binding_is_not_refused_for_a_missing_limit(self, db) -> None:
        """The guard is for a run with no member behind it. A group's unlinked sender runs as
        the binding's creator and a member as themselves: neither is refused, which a guard
        keyed on `initiated_by_publisher_fallback` would get wrong."""
        tenant = await _tenant(db, name="Binding")
        agent, _ctx = await _agent_under(db, tenant, spec=AgentSpec(name="Support"))
        group = await publisher_context(
            db, organization_id=tenant.organization.id, publisher_user_id=tenant.user.id
        )

        under_the_binding = await AgentRunnerService(db).prepare(
            group, agent.id, surface=RunSurface.WHATSAPP, acts_for_sender=True
        )
        as_a_member = await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

        assert under_the_binding.run.initiated_by_publisher_fallback is True
        assert under_the_binding.run.runs_as_agent is False
        assert as_a_member.run.runs_as_agent is False

    @pytest.mark.security
    async def test_a_continuation_with_no_limit_left_is_refused(self, db) -> None:
        """A decider approving a parked agent run after the cap is gone gets the refusal, and
        the run stays parked."""
        tenant = await _tenant(db, name="Parked", monthly_budget_usd=Decimal("20"))
        agent, ctx = await _agent_under(db, tenant, spec=AgentSpec(name="Support"))
        prepared = await AgentRunnerService(db).prepare(
            ctx, agent.id, surface=RunSurface.WHATSAPP, acts_for_sender=True
        )
        prepared.run.status = RunStatus.AWAITING_APPROVAL.value
        prepared.run.paused_state = {
            "messages": [],
            "tool_call_ids": {},
            "admitted_as": prepared.admitted_as.model_dump(mode="json"),
        }
        assert prepared.admitted_as.runs_as_agent is True
        run_id = prepared.run.id
        tenant.organization.monthly_budget_usd = None
        await db.commit()

        with pytest.raises(NoSpendingLimitError):
            await AgentRunnerService(db).resume(tenant.ctx, run_id)

        await db.rollback()
        run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        assert run.status == RunStatus.AWAITING_APPROVAL.value

    async def test_memory_conversation_search_workflows_and_background_tasks_refuse(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Refusals", monthly_budget_usd=Decimal("20"))
        agent, ctx = await _agent_under(
            db,
            tenant,
            spec=AgentSpec(
                name="Support",
                capabilities=[
                    CapabilityBindingSpec(id=capability)
                    for capability in ("memory_files", "conversation_search", "background_tasks")
                ],
            ),
        )
        conversation = Conversation(organization_id=tenant.organization.id, user_id=None)
        db.add(conversation)
        await db.flush()
        prepared = await AgentRunnerService(db).prepare(
            ctx, agent.id, surface=RunSurface.WHATSAPP, conversation_id=conversation.id
        )
        calls = ("list_memory", "search_conversations", "list_background_tasks")
        arguments = {"search_conversations": {"query": "refund"}}

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returned = [
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            if len(returned) < len(calls):
                name = calls[len(returned)]
                return ModelResponse(parts=[ToolCallPart(name, arguments.get(name, {}))])
            return ModelResponse(parts=[TextPart("done")])

        with prepared.built.agent.override(model=FunctionModel(respond)):
            result = await prepared.built.agent.run("hello", deps=prepared.deps)

        refusals = [
            str(part.content)
            for message in result.all_messages()
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert len(refusals) == len(calls)
        assert "has no memory" in refusals[0]
        assert "Nobody is identified" in refusals[1]
        assert "Background topics need an active organization member" in refusals[2]

        # The workflows tools are built only for an agent that names a workflow, so
        # they are called on the run's own deps rather than through the model.
        tools = build_workflows_toolset(workflow_ids=(uuid.uuid4(),), wait_seconds=0)
        with patch.object(workflows_toolset, "get_db_context", return_value=_NoSession()):
            listed = await tools.tools["list_workflows"].function(
                RunContext(
                    deps=prepared.deps,
                    model=TestModel(),
                    usage=RunUsage(),
                    tool_call_id="call-1",
                )
            )
        assert listed == "Workflows can only be started for a member of an organization."


class TestAContinuationInChatWithNoLimitLeft:
    @pytest.mark.security
    async def test_the_chat_is_told_once_and_the_run_stays_parked(
        self, db, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The whole seam on a real database: a member's approval in the chat reaches a parked
        agent run whose spending ceiling has gone, so nothing is built and the customer reads
        one fixed notice."""
        tenant = await _tenant(db, name="Chat", monthly_budget_usd=Decimal("20"))
        agent, ctx = await _agent_under(db, tenant, spec=AgentSpec(name="Support"))
        prepared = await AgentRunnerService(db).prepare(
            ctx, agent.id, surface=RunSurface.SLACK, acts_for_sender=True
        )
        bot = ChannelBot(
            organization_id=tenant.organization.id,
            platform="slack",
            name="Support",
            token_encrypted=seal_bot_token(
                "xoxb-test", organization_id=tenant.organization.id
            ).ciphertext,
        )
        db.add(bot)
        await db.flush()
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            surface="slack",
            channel_bot_id=bot.id,
            is_active=True,
        )
        db.add(exposure)
        await db.flush()
        destination = ChannelDestination(
            bot_id=bot.id, platform_chat_id="C1:1.0", private_chat=False
        )
        approval = ToolApproval(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            run_id=prepared.run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={},
            status=ApprovalStatus.APPROVED.value,
            decided_by_user_id=tenant.user.id,
            created_at=datetime.now(UTC),
        )
        db.add(approval)
        run_id = prepared.run.id
        prepared.run.exposure_id = exposure.id
        prepared.run.status = RunStatus.AWAITING_APPROVAL.value
        prepared.run.paused_state = {
            "messages": [],
            "tool_call_ids": {str(approval.id): "call-1"},
            "channel_destination": destination.model_dump(mode="json"),
            "admitted_as": prepared.admitted_as.model_dump(mode="json"),
        }
        tenant.organization.monthly_budget_usd = None
        await db.commit()
        module = "app.services.channels.continuation"
        router = MagicMock(admission=AsyncMock(return_value=Admission("admitted", "member")))

        with (
            patch(f"{module}.get_db_context", new=lambda: _context_on(engine)),
            patch(
                f"{module}.decider_context",
                new=AsyncMock(return_value=tenant.ctx),
            ),
            patch(f"{module}.incoming_for_run", new=AsyncMock(return_value=MagicMock())),
            patch(f"{module}.ChannelMessageRouter", return_value=router),
            patch("app.services.agent_runner.build_agent") as build,
            patch("app.services.channels.directory.get_adapter", return_value=MagicMock()),
            caplog.at_level("INFO", logger=module),
        ):
            await continue_in_chat(
                organization_id=tenant.organization.id,
                run_id=run_id,
                decider_user_id=tenant.user.id,
                impersonator_id=None,
                destination=destination,
                approval_id=approval.id,
            )

        build.assert_not_called()
        assert "reason=NoSpendingLimitError" in caplog.text
        await db.rollback()
        run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        await db.refresh(run)
        assert run.status == RunStatus.AWAITING_APPROVAL.value
        assert run.chat_notice_sent_at is not None
        jobs = (
            (
                await db.execute(
                    select(BackgroundJob).where(BackgroundJob.kind == DELIVER_CHANNEL_HANDBACK.kind)
                )
            )
            .scalars()
            .all()
        )
        assert len(jobs) == 1
        assert jobs[0].payload["output"] == REFUSED_NOTICE
