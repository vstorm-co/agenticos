"""Tests for run execution, accounting and approvals.

Three invariants carry most of the weight here: a run that fails still records
what it spent, a budget stop is recorded as a budget stop rather than as a
failure, and a run parked on an approval can be picked up again - on the version
it was parked on, with the spend it had already booked.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import RequestUsage
from pydantic_ai_harness.planning import PlanItem

from app.agents.capabilities.approval import ApprovalGranted, ApprovalRejected
from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendLedger
from app.agents.capabilities.channel_tools import CHANNEL_DIRECTORY_RESOURCE
from app.agents.capabilities.compaction import ContextGauge
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.capabilities.planning import PLANNING_STORE_RESOURCE
from app.agents.spec import AgentSpec, CapabilityBindingSpec, McpServerRef, ObservabilitySpec
from app.agents.subagent_runtime import DelegationSpend, DelegationStash, ParkedDelegation
from app.core.exceptions import BadRequestError, NotFoundError, RunExecutionError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus, RunStatus, RunSurface
from app.services.agent_runner import (
    AgentRunnerService,
    ApprovalChannel,
    ParkedApproval,
    PausedRunState,
    PreparedRun,
    RecordedDelegation,
    RunSegment,
    month_start,
    run_failure_summary,
)
from app.services.approvals import ApprovalService
from app.services.transcript import RecordedToolCall


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _db(monthly_budget_usd: Decimal | None = None):
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # `_run` commits its own terminal write rather than leaving it to the session
    # context, because that exit rolls back on an exception and is skipped
    # entirely by a cancellation.
    db.commit = AsyncMock()
    # `db.get` is how the organization row - and with it the org-wide spending
    # cap the runner reads for every run - comes back. Uncapped by default,
    # which is what an organization that never opened the setting looks like.
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=monthly_budget_usd))
    return db


def _prepared(
    ledger: SpendLedger | None = None, *, conversation_id: uuid.UUID | None = None
) -> PreparedRun:
    """A run with its agent stubbed - but a real `PreparedRun`, and a real ledger.

    Mocking the prepared run itself would mock away `execute`, which is what
    opens the spend meter: the test would prove the runner calls something and
    nothing at all about what the run was billed.

    No conversation unless a test asks for one. `_run` writes the transcript into
    the run's conversation, and a `MagicMock` there is truthy - which would send
    every accounting test through a write it is not about, against a session that
    cannot serve it.
    """
    built = MagicMock()
    built.ledger = ledger or SpendLedger()
    built.model_label = "gpt-4.1"
    # A real gauge: what a turn records against its conversation is read off
    # this, and a `MagicMock` answers "yes, summarised" to every turn.
    built.context = ContextGauge()
    return PreparedRun(
        run=MagicMock(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            agent_version_id=uuid.uuid4(),
            conversation_id=conversation_id,
        ),
        agent=MagicMock(),
        spec=MagicMock(),
        built=built,
        # Real containers, not mocks: `finish` walks both to fold the delegation
        # tree into whatever parked state the surface reported, and a `MagicMock`
        # is not iterable. An agent that never delegated leaves them empty.
        approvals=MagicMock(parked={}, requested=[]),
    )


def _parked_run(**overrides):
    """A run row as it looks after the gate parked a tool call on it."""
    run = MagicMock(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        conversation_id=None,
        # No binding by default: most resume tests are about the approval
        # machinery, and a run that arrived through an exposure is its own case
        # below. A MagicMock here would be truthy and send the resume path
        # looking up a binding that does not exist.
        exposure_id=None,
        # Same reasoning for the environment: None keeps the resume path from
        # looking up observability for an environment that does not exist.
        environment_id=None,
        surface=RunSurface.API.value,
        status=RunStatus.AWAITING_APPROVAL.value,
        paused_state={"messages": [], "tool_call_ids": {}},
        model_label="gpt-4.1",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=Decimal("0.25"),
        cost_is_partial=False,
    )
    for name, value in overrides.items():
        setattr(run, name, value)
    return run


class TestMonthBoundary:
    def test_month_start_is_calendar_aligned(self):
        """A rolling window cannot be reconciled against an invoice."""
        moment = datetime(2026, 7, 26, 22, 30, tzinfo=UTC)
        assert month_start(moment) == datetime(2026, 7, 1, tzinfo=UTC)


class TestPrepare:
    """Assembling a run: resolve the model, open the row, gather what the agent may reach."""

    @pytest.mark.anyio
    async def test_preparing_a_run_opens_its_row_on_the_version_that_will_execute(self):
        """Accounting and history hang off that row, so it exists before a token is spent.

        It records the version rather than the agent alone: a run that is read
        back next month has to say what it was actually running at the time.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        spec = AgentSpec(name="Support", model_profile_id=uuid.uuid4())
        run = MagicMock(id=uuid.uuid4())
        conversation_id = uuid.uuid4()
        built = MagicMock()

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ) as resolve,
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=run),
            ) as create_run,
            patch("app.services.agent_runner.build_agent", return_value=built),
        ):
            prepared = await service.prepare(
                ctx,
                agent.id,
                surface=RunSurface.SLACK,
                conversation_id=conversation_id,
            )

        assert resolve.call_args.kwargs["profile_id"] == spec.model_profile_id
        opened = create_run.call_args.kwargs
        assert opened["organization_id"] == ctx.organization_id
        assert opened["agent_id"] == agent.id
        assert opened["agent_version_id"] == agent.current_version_id
        assert opened["user_id"] == ctx.user_id
        assert opened["conversation_id"] == conversation_id
        assert opened["surface"] == RunSurface.SLACK.value
        assert opened["model_label"] == "gpt-4.1"
        assert (prepared.run, prepared.agent, prepared.spec) == (run, agent, spec)
        # Streaming surfaces run their own loop and need the deps the agent was
        # built with; re-deriving them there is how the two drift apart.
        assert prepared.deps is built.deps

    @pytest.mark.anyio
    async def test_a_collection_that_is_gone_or_foreign_narrows_the_agent_instead_of_failing_the_run(
        self,
    ):
        """A collection deleted after publish makes the answer worse, not absent.

        The same skip covers a collection belonging to another organization: ids
        are resolved server-side against the caller's tenant, so a spec carrying
        a foreign id reaches nothing rather than reading across the boundary.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        live_id, deleted_id, foreign_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        collections = {
            live_id: MagicMock(organization_id=ctx.organization_id, collection_name="kb_live"),
            deleted_id: None,
            foreign_id: MagicMock(organization_id=uuid.uuid4(), collection_name="kb_other_tenant"),
        }
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        spec = AgentSpec(name="Support", collection_ids=[live_id, deleted_id, foreign_id])

        async def get_collections(_db, ids):
            # A batched read: an id with no row is absent from the map, the way
            # `deleted_id` is here, rather than returning a None value.
            return {cid: collections[cid] for cid in ids if collections.get(cid) is not None}

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.knowledge_base_repo.get_by_ids",
                new=AsyncMock(side_effect=get_collections),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(ctx, agent.id)

        assert build.call_args.kwargs["resources"]["kb_collection_names"] == ["kb_live"]

    @pytest.mark.anyio
    async def test_the_mcp_servers_the_spec_binds_reach_the_agent_that_is_built(self):
        """`mcp_servers` is part of the published contract, so it has to act.

        Resolved here, in the one place every surface goes through, and against
        the run's own organization - an agent's reach is a property of the agent,
        not of whichever session happens to run it.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        refs = [McpServerRef(connection_id=uuid.uuid4()), McpServerRef(connection_id=uuid.uuid4())]
        spec = AgentSpec(name="Support", mcp_servers=refs)

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "app.services.agent_runner.build_toolsets_for_agent",
                new=AsyncMock(return_value=["linear-toolset"]),
            ) as toolsets,
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(ctx, agent.id, extra_toolsets=["surface-toolset"])

        assert toolsets.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "refs": refs,
            # An API run has neither a private conversation nor, necessarily, a
            # person - so no binding may reach for anybody's own account.
            "personal_for_user_id": None,
        }
        # Alongside what the surface brought, not instead of it: the WebSocket
        # chat still attaches its own, and dropping either half would leave an
        # agent silently short of tools.
        assert build.call_args.kwargs["extra_toolsets"] == ["surface-toolset", "linear-toolset"]

    @pytest.mark.anyio
    async def test_a_resumed_run_gets_its_servers_back(self):
        """The parked call may be an MCP tool, and it is answered after resume.

        Rebuilding without them would leave the model holding a tool result it
        can no longer follow up on.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        run = _parked_run()
        agent = MagicMock(id=run.agent_id, current_version_id=run.agent_version_id)
        spec = AgentSpec(name="Support", mcp_servers=[McpServerRef(connection_id=uuid.uuid4())])

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.agent_run_repo.mark_running", new=AsyncMock()),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service, "_parked_spec", new=AsyncMock(return_value=(agent, spec))),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.build_toolsets_for_agent",
                new=AsyncMock(return_value=["linear-toolset"]),
            ) as toolsets,
            patch("app.services.agent_runner.build_agent") as build,
        ):
            build.return_value.agent.run = AsyncMock(return_value=MagicMock(output="done"))
            build.return_value.ledger = SpendLedger()
            await service.resume(ctx, run.id)

        assert toolsets.await_args.kwargs["refs"] == spec.mcp_servers
        assert build.call_args.kwargs["extra_toolsets"] == ["linear-toolset"]

    @pytest.mark.anyio
    async def test_a_resumed_channel_run_keeps_its_binding_prompt_and_tools(self):
        """A channel run parks, a reviewer approves, and the continuation must be
        the same agent: with the platform's formatting prompt and the
        `channel_tools` capability the binding grants. Resuming without them
        answered the approval formatted for the wrong platform and with the
        channel lookups gone (#513, S14)."""
        ctx = _ctx()
        service = AgentRunnerService(_db())
        exposure_id = uuid.uuid4()
        run = _parked_run(exposure_id=exposure_id, surface=RunSurface.MATTERMOST.value)
        agent = MagicMock(id=run.agent_id, current_version_id=run.agent_version_id)
        spec = AgentSpec(name="Support")
        exposure = MagicMock(
            id=exposure_id, prompt="Answer in Mattermost style.", tools=["get_channel_info"]
        )

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.agent_run_repo.mark_running", new=AsyncMock()),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch(
                "app.services.agent_runner.agent_exposure_repo.get",
                new=AsyncMock(return_value=exposure),
            ) as get_exposure,
            patch.object(service, "_parked_spec", new=AsyncMock(return_value=(agent, spec))),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.build_toolsets_for_agent",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            build.return_value.agent.run = AsyncMock(return_value=MagicMock(output="done"))
            build.return_value.ledger = SpendLedger()
            await service.resume(ctx, run.id)

        assert get_exposure.await_args.args[1] == exposure_id
        assert get_exposure.await_args.kwargs["organization_id"] == ctx.organization_id
        built_spec = build.call_args.args[0]
        assert "Answer in Mattermost style." in built_spec.instructions
        assert "channel_tools" in {capability.id for capability in built_spec.capabilities}

    @pytest.mark.anyio
    async def test_a_resumed_run_with_no_binding_reloads_no_exposure(self):
        """The common resume has no binding, so it must not go looking one up."""
        ctx = _ctx()
        service = AgentRunnerService(_db())
        run = _parked_run()  # exposure_id is None by default
        agent = MagicMock(id=run.agent_id, current_version_id=run.agent_version_id)
        spec = AgentSpec(name="Support")

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.agent_run_repo.mark_running", new=AsyncMock()),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch(
                "app.services.agent_runner.agent_exposure_repo.get", new=AsyncMock()
            ) as get_exposure,
            patch.object(service, "_parked_spec", new=AsyncMock(return_value=(agent, spec))),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.build_toolsets_for_agent",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            build.return_value.agent.run = AsyncMock(return_value=MagicMock(output="done"))
            build.return_value.ledger = SpendLedger()
            await service.resume(ctx, run.id)

        get_exposure.assert_not_awaited()
        assert build.call_args.args[0].capabilities == []

    @staticmethod
    async def _period_lookups(ctx) -> dict[str, object]:
        """The two spend lookups the runner hands the factory, by argument name."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        run = MagicMock(id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=run),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(ctx, agent.id)

        return {"agent_id": agent.id, "run_id": run.id, **build.call_args.kwargs}

    @pytest.mark.anyio
    async def test_the_spend_the_agent_checks_its_budget_against_is_this_calendar_month(self):
        """The monthly limit is checked mid-run, against a window that matches the invoice.

        The runner hands the agent a callable rather than a number so the guard
        reads the spend at the moment it checks, not at the moment the run began.
        """
        ctx = _ctx()
        built = await self._period_lookups(ctx)

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("4.50")),
            ) as total,
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("0")),
            ),
        ):
            spent = await built["org_period_spend"]()

        assert spent == Decimal("4.50")
        assert total.call_args.kwargs["organization_id"] == ctx.organization_id
        assert total.call_args.kwargs["since"] == month_start()
        # The organization-wide sum narrows to no agent - that absence is the
        # difference between this lookup and the one above it.
        assert total.call_args.kwargs.get("agent_id") is None

    @pytest.mark.anyio
    async def test_the_agents_own_cap_is_metered_on_the_agents_own_spend(self):
        """The defect this pair exists to keep fixed.

        `AgentSpec.budget.monthly_usd` used to be checked against the very
        lookup above - the organization's month-to-date - so an agent with a $10
        cap was refused once *other* agents had spent $10, and its own spend was
        never isolated. The narrowing argument existed the whole time; this path
        did not pass it.
        """
        ctx = _ctx()
        built = await self._period_lookups(ctx)

        with patch(
            "app.services.agent_runner.agent_run_repo.sum_cost_since",
            new=AsyncMock(return_value=Decimal("0.75")),
        ) as total:
            spent = await built["agent_period_spend"]()

        assert spent == Decimal("0.75")
        assert total.call_args.kwargs["agent_id"] == built["agent_id"]
        assert total.call_args.kwargs["organization_id"] == ctx.organization_id
        assert total.call_args.kwargs["since"] == month_start()

    @pytest.mark.anyio
    async def test_a_resumed_runs_own_prior_spend_is_not_counted_twice(self):
        """Both baselines leave this run's own row out, and the resume path is why.

        A resumed run keeps its row. It spent $6 and parked, so `finish_run` has
        committed `cost_usd = 6.00`, and `_spend_already_booked` re-seeds the
        ledger with the same $6 - which it must, or finishing the continuation
        would overwrite the cost with only what the continuation cost. Summed
        into the baseline as well, the first model request after the approval
        saw $12 against a $10 cap and refused a run with $4 of headroom (#15).

        A baseline is what *other* runs have already spent; what this one spends
        is the ledger's. On a fresh run the row is there too, at zero, so there
        is no branch to get wrong.
        """
        ctx = _ctx()
        built = await self._period_lookups(ctx)

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("0")),
            ) as total,
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("0")),
            ),
        ):
            await built["agent_period_spend"]()
            agent_scoped = total.call_args.kwargs
            await built["org_period_spend"]()
            organization_scoped = total.call_args.kwargs

        assert agent_scoped["exclude_run_id"] == built["run_id"]
        # The organization's cap double-counted identically, through
        # `organization_monthly_spend`.
        assert organization_scoped["exclude_run_id"] == built["run_id"]


class TestSpendReporting:
    @pytest.mark.anyio
    async def test_monthly_spend_counts_from_the_first_of_the_month(self):
        """The figure shown next to a monthly budget has to be the one it enforces."""
        ctx = _ctx()
        agent_id = uuid.uuid4()

        with patch(
            "app.services.agent_runner.agent_run_repo.sum_cost_since",
            new=AsyncMock(return_value=Decimal("12.34")),
        ) as total:
            spent = await AgentRunnerService(_db()).monthly_spend(ctx, agent_id=agent_id)

        assert spent == Decimal("12.34")
        assert total.call_args.kwargs["organization_id"] == ctx.organization_id
        assert total.call_args.kwargs["since"] == month_start()
        assert total.call_args.kwargs["agent_id"] == agent_id

    @pytest.mark.anyio
    async def test_the_organizations_month_includes_what_ingestion_embedded(self):
        """The organization's cap is a cap on the bill, not on one kind of line
        item - and ingestion spend is the half of the bill runs cannot see."""
        ctx = _ctx()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("10")),
            ),
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("2.5")),
            ) as ingested,
        ):
            spent = await AgentRunnerService(_db()).monthly_spend(ctx)

        assert spent == Decimal("12.5")
        assert ingested.call_args.kwargs["organization_id"] == ctx.organization_id
        assert ingested.call_args.kwargs["since"] == month_start()

    @pytest.mark.anyio
    async def test_an_agents_month_does_not_carry_ingestion_spend(self):
        """Indexing a shared knowledge base is nobody's agent's spend - charging
        it to whichever agent runs first would exhaust that agent's cap for work
        every agent shares."""
        ctx = _ctx()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("10")),
            ),
            patch("app.services.spend.ingestion_spend_repo.sum_cost_since") as ingested,
        ):
            spent = await AgentRunnerService(_db()).monthly_spend(ctx, agent_id=uuid.uuid4())

        assert spent == Decimal("10")
        ingested.assert_not_called()


class TestAPlanThatOutlivesTheTurn:
    """A plan store is one pydantic-ai run's, and here a run is one turn - so the
    checklist an agent wrote in one message was gone by the next, and the agent
    answered that no plan existed and it had never created one (#1077)."""

    @pytest.mark.anyio
    async def test_a_fresh_turn_seeds_the_plan_its_conversation_left(self):
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        spec = AgentSpec(name="Support", model_profile_id=uuid.uuid4())
        conversation = MagicMock(
            overhead_tokens=None,
            reminder_state=None,
            plan_items=[{"id": "aa11", "content": "Write the fix", "status": "in_progress"}],
        )

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "app.services.agent_runner.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch("app.services.agent_runner.build_agent"),
        ):
            prepared = await service.prepare(ctx, agent.id, conversation_id=uuid.uuid4())

        items = await prepared.plan_store.get_items()
        assert [(item.content, item.status.value) for item in items] == [
            ("Write the fix", "in_progress")
        ]

    @pytest.mark.anyio
    async def test_a_fresh_turn_does_not_seed_a_finished_one(self):
        """The other half of #1077, filed as #1221: `keep_plan` stores completed
        steps too, so a thread whose plan was finished in August opened in
        November with the tail reminder calling it "your current plan"."""
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        spec = AgentSpec(name="Support", model_profile_id=uuid.uuid4())
        conversation = MagicMock(
            overhead_tokens=None,
            reminder_state=None,
            plan_items=[
                {"id": "aa11", "content": "Write the fix", "status": "completed"},
                {"id": "bb22", "content": "Ship it", "status": "cancelled"},
            ],
        )

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "app.services.agent_runner.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch("app.services.agent_runner.build_agent"),
        ):
            prepared = await service.prepare(ctx, agent.id, conversation_id=uuid.uuid4())

        assert await prepared.plan_store.get_items() == []

    @pytest.mark.anyio
    async def test_a_resume_starts_from_the_plan_the_run_parked_with(self):
        """Both copies exist on a resume, and the park's is the newer one: it was
        seeded from the conversation when that run began and then worked on."""
        ctx = _ctx()
        service = AgentRunnerService(_db())
        run = _parked_run(
            conversation_id=uuid.uuid4(),
            paused_state={
                "messages": [],
                "tool_call_ids": {},
                "plan": [{"id": "bb22", "content": "Ship the fix", "status": "in_progress"}],
            },
        )
        agent = MagicMock(id=run.agent_id, current_version_id=run.agent_version_id)
        spec = AgentSpec(name="Support")
        stale = MagicMock(
            overhead_tokens=None,
            reminder_state=None,
            plan_items=[{"id": "aa11", "content": "Write the fix", "status": "pending"}],
        )

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_runner.agent_run_repo.mark_running", new=AsyncMock()),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service, "_parked_spec", new=AsyncMock(return_value=(agent, spec))),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=stale),
            ),
            patch.object(service.transcript, "record", new=AsyncMock()),
            patch("app.services.agent_runner.ConversationService") as conversations,
            patch("app.services.agent_runner.build_agent") as build,
        ):
            conversations.return_value.keep_summary = AsyncMock()
            conversations.return_value.keep_overhead = AsyncMock()
            conversations.return_value.keep_reminder_state = AsyncMock()
            conversations.return_value.keep_plan = AsyncMock()
            build.return_value.agent.run = AsyncMock(return_value=MagicMock(output="done"))
            build.return_value.ledger = SpendLedger()
            await service.resume(ctx, run.id)

        store = build.call_args.kwargs["resources"][PLANNING_STORE_RESOURCE]
        assert [item.content for item in await store.get_items()] == ["Ship the fix"]


class TestRecordedConversationState:
    """The overhead, the reminder cadence and the plan a build seeds from - all
    off one read of the conversation, so a thread with none still costs one
    SELECT."""

    @pytest.mark.anyio
    async def test_no_conversation_id_reads_nothing(self):
        """A run with no thread has nothing to seed and does not touch the row."""
        with patch(
            "app.services.agent_runner.conversation_repo.get_conversation_by_id",
            new=AsyncMock(),
        ) as fetch:
            result = await AgentRunnerService(_db())._recorded_conversation_state(None)

        assert (result.overhead, result.reminder_state, result.plan) == (None, None, None)
        fetch.assert_not_called()

    @pytest.mark.anyio
    async def test_a_missing_conversation_seeds_nothing(self):
        """A conversation_id that resolves to no row seeds a fresh build."""
        with patch(
            "app.services.agent_runner.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=None),
        ):
            result = await AgentRunnerService(_db())._recorded_conversation_state(uuid.uuid4())

        assert (result.overhead, result.reminder_state, result.plan) == (None, None, None)

    @pytest.mark.anyio
    async def test_every_recorded_value_comes_from_one_read(self):
        """Overhead, cadence and the plan are returned together from a single fetch."""
        conversation = MagicMock(
            overhead_tokens=3_865,
            reminder_state={"request_count": 4},
            plan_items=[{"id": "aa11", "content": "Write the fix", "status": "in_progress"}],
        )
        with patch(
            "app.services.agent_runner.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=conversation),
        ) as fetch:
            recorded = await AgentRunnerService(_db())._recorded_conversation_state(uuid.uuid4())

        assert recorded.overhead == 3_865
        assert recorded.reminder_state == {"request_count": 4}
        assert [item["content"] for item in recorded.plan or []] == ["Write the fix"]
        assert fetch.await_count == 1


class TestReadingRunHistory:
    """The two reads behind the run-history surface, scoped in the service so
    the route never touches the repository - and so the tenant boundary has one
    home rather than two."""

    @pytest.mark.anyio
    async def test_listing_runs_scopes_to_the_callers_organization(self):
        """A listing is read for the caller's org, never for all of them, and the
        filter and page pass straight through."""
        ctx = _ctx()
        agent_id = uuid.uuid4()
        rows = ([MagicMock(), MagicMock()], 2)

        with patch(
            "app.services.agent_runner.agent_run_repo.list_runs",
            new=AsyncMock(return_value=rows),
        ) as listed:
            items, total = await AgentRunnerService(_db()).list_runs(
                ctx, agent_id=agent_id, skip=10, limit=25
            )

        assert (items, total) == rows
        assert listed.call_args.kwargs["organization_id"] == ctx.organization_id
        assert listed.call_args.kwargs["agent_id"] == agent_id
        assert listed.call_args.kwargs["skip"] == 10
        assert listed.call_args.kwargs["limit"] == 25

    @pytest.mark.anyio
    async def test_getting_a_run_reads_it_within_the_callers_organization(self):
        """The single read carries the org id so it can only ever return a row
        the caller's organization owns."""
        ctx = _ctx()
        run_id = uuid.uuid4()
        run = MagicMock(id=run_id)

        with patch(
            "app.services.agent_runner.agent_run_repo.get_run",
            new=AsyncMock(return_value=run),
        ) as fetched:
            got = await AgentRunnerService(_db()).get_run(ctx, run_id)

        assert got is run
        assert fetched.call_args.args[1] == run_id
        assert fetched.call_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_run_in_another_organization_is_not_found(self):
        """The repository filters on organization, so a foreign id returns no row
        - and a tenant cannot tell a neighbour's run from one that never was."""
        ctx = _ctx()
        run_id = uuid.uuid4()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.get_run",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await AgentRunnerService(_db()).get_run(ctx, run_id)


class TestWhatAParkedCallRecords:
    """Enough for a surface to put the decision in front of somebody.

    Before this, a run parked and `/chat` could only name a queue: the client had
    a panel for deciding inline and nothing ever gave it anything to show. The
    detail is kept where the row is created rather than read back afterwards,
    which would be a query per parked call to recover what this object had in hand.
    """

    @pytest.mark.anyio
    async def test_a_parked_call_records_the_row_the_decision_goes_against(self):
        channel = ApprovalChannel(
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
        )
        request = MagicMock(
            tool_call_id="tc-1", tool_name="write_file", tool_args={"path": "/a.txt"}
        )

        await channel(request)

        # The id is allocated here, not by the database: parking touches no session,
        # so the row is written afterwards against this id (agenticos#169).
        [parked] = channel.requested
        assert isinstance(parked.approval_id, uuid.UUID)
        assert channel.parked == {str(parked.approval_id): "tc-1"}
        # The model's own id as well as the row's: one addresses the decision, the
        # other addresses the card already on screen.
        assert parked.tool_call_id == "tc-1"
        assert parked.tool_name == "write_file"
        assert parked.tool_args == {"path": "/a.txt"}

    @pytest.mark.anyio
    async def test_a_second_call_after_a_decision_records_nothing_new(self):
        """A decision is consumed on use, so an approved call runs rather than
        parking again - and nothing is put back in front of anybody."""
        channel = ApprovalChannel(
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            decided={"tc-1": MagicMock()},
        )

        await channel(MagicMock(tool_call_id="tc-1", tool_name="write_file", tool_args={}))

        assert channel.requested == []


class TestFilesAcrossOneTurn:
    """What arrived with the message, and what the turn produced.

    Both are routed by `execute` rather than by its caller, and for the same
    reason: where an attachment goes depends on whether the agent has a workspace,
    and the workspace is closed before the call returns.
    """

    @pytest.mark.anyio
    async def test_an_attachment_is_routed_against_the_workspace_the_run_opened(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.workspace = MagicMock()
        service.prepare = AsyncMock(return_value=prepared)
        service._run = AsyncMock(
            return_value=RunSegment(output="answered", run=prepared.run, tool_calls=[], settled={})
        )
        built = AsyncMock(return_value="a prompt with a reference")

        with patch("app.services.agent_runner.AttachmentRouter") as router:
            router.return_value.build_prompt = built
            await service.execute(
                MagicMock(), uuid.uuid4(), "look at this", attachments=[MagicMock()]
            )

        # The backend, not the conversation: the router writes the file where the
        # agent can read it, and only `prepare` knows whether there is one.
        assert router.call_args.args[0] is prepared.workspace.backend
        assert service._run.await_args.kwargs["user_prompt"] == "a prompt with a reference"

    @pytest.mark.anyio
    async def test_a_turn_with_no_attachments_builds_no_prompt(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.outbound = []
        prepared.outbound_refused = []
        service.prepare = AsyncMock(return_value=prepared)
        service._run = AsyncMock(
            return_value=RunSegment(output="answered", run=prepared.run, tool_calls=[], settled={})
        )

        with patch("app.services.agent_runner.AttachmentRouter") as router:
            await service.execute(MagicMock(), uuid.uuid4(), "hello")

        router.assert_not_called()

    @pytest.mark.anyio
    async def test_what_the_turn_produced_reaches_the_caller(self):
        """Through a list it passes in, because the workspace is closed before this
        returns - a run-scoped one is released outright."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        produced = MagicMock()
        prepared.outbound = [produced]
        prepared.outbound_refused = ["/huge.csv"]
        service.prepare = AsyncMock(return_value=prepared)
        service._run = AsyncMock(
            return_value=RunSegment(output="answered", run=prepared.run, tool_calls=[], settled={})
        )

        outbound: list[Any] = []
        refused: list[str] = []
        await service.execute(
            MagicMock(),
            uuid.uuid4(),
            "make me a report",
            outbound=outbound,
            outbound_refused=refused,
        )

        assert outbound == [produced]
        assert refused == ["/huge.csv"]

    @pytest.mark.anyio
    async def test_the_tool_calls_a_turn_made_reach_the_caller(self):
        """A channel run reads a chart off what the turn called, not off the row
        - it writes no messages (#205) - so `execute` hands the calls back
        through the list it was given, the same way it hands back the files."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.outbound = []
        prepared.outbound_refused = []
        service.prepare = AsyncMock(return_value=prepared)
        drew = RecordedToolCall(tool_call_id="c-1", tool_name="create_chart", args={}, result="{}")
        service._run = AsyncMock(
            return_value=RunSegment(
                output="answered", run=prepared.run, tool_calls=[drew], settled={}
            )
        )

        called: list[RecordedToolCall] = []
        await service.execute(MagicMock(), uuid.uuid4(), "chart it", tool_calls=called)

        assert called == [drew]

    @pytest.mark.anyio
    async def test_a_caller_that_cannot_deliver_files_asks_for_none(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.outbound = [MagicMock()]
        prepared.outbound_refused = []
        service.prepare = AsyncMock(return_value=prepared)
        service._run = AsyncMock(
            return_value=RunSegment(output="answered", run=prepared.run, tool_calls=[], settled={})
        )

        answer, _run = await service.execute(MagicMock(), uuid.uuid4(), "hello")

        assert answer == "answered"

    @pytest.mark.anyio
    async def test_a_run_with_no_workspace_produces_nothing_to_send(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()

        await service._collect_outbound(prepared)

        assert prepared.outbound == []

    @pytest.mark.anyio
    async def test_what_the_workspace_gained_is_read_before_it_closes(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.workspace = MagicMock()
        prepared.workspace_at_start = {"/run.py"}

        with patch("app.services.agent_runner.files_written", new_callable=AsyncMock) as written:
            written.return_value = MagicMock(attachments=["a file"], refused=["/huge.csv"])
            await service._collect_outbound(prepared)

        assert written.await_args.args[1] == {"/run.py"}
        assert prepared.outbound == ["a file"]
        assert prepared.outbound_refused == ["/huge.csv"]


class TestSkillChangesARunProposed:
    """What an agent wrote to its skills, on the way out of the run.

    Recorded rather than applied: a skill is instructions every bound agent
    follows, so an agent editing one directly would rewrite what another agent
    does inside a conversation nobody reviewed.
    """

    @pytest.mark.anyio
    async def test_what_the_agent_changed_becomes_a_proposal(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.ctx = MagicMock(organization_id=uuid.uuid4())
        prepared.workspace = MagicMock()
        prepared.materialised_skills = MagicMock()
        change = MagicMock()
        record = AsyncMock(return_value=[MagicMock()])
        service.proposals = MagicMock(record=record)

        with (
            patch("app.services.agent_runner.collect_changes", return_value=[change]) as collected,
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        collected.assert_called_once()
        assert record.await_args.args[1] == [change]

    @pytest.mark.anyio
    async def test_a_recording_failure_does_not_replace_the_runs_own_outcome(self):
        """It runs in the same `finally` that records what the run cost, so a name
        taken since must not turn a completed run into a storage error."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.ctx = MagicMock(organization_id=uuid.uuid4())
        prepared.workspace = MagicMock()
        prepared.materialised_skills = MagicMock()
        service.proposals = MagicMock(record=AsyncMock(side_effect=RuntimeError("name taken")))

        with (
            patch("app.services.agent_runner.collect_changes", return_value=[MagicMock()]),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        assert finish.call_args.kwargs["status"] == RunStatus.COMPLETED.value

    @pytest.mark.anyio
    async def test_a_run_that_left_its_skills_alone_proposes_nothing(self):
        """The ordinary case. A proposal per run would make the queue meaningless."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.ctx = MagicMock(organization_id=uuid.uuid4())
        prepared.workspace = MagicMock()
        prepared.materialised_skills = MagicMock()
        service.proposals = MagicMock(record=AsyncMock())

        with (
            patch("app.services.agent_runner.collect_changes", return_value=[]),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
        ):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        service.proposals.record.assert_not_called()

    @pytest.mark.anyio
    async def test_a_run_with_no_workspace_proposes_nothing(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        service.proposals = MagicMock(record=AsyncMock())

        with patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()):
            await service.finish(prepared, status=RunStatus.COMPLETED)

        service.proposals.record.assert_not_called()


class TestRunAccounting:
    @pytest.mark.anyio
    async def test_a_failed_run_still_records_its_cost(self):
        """A budget that ignores failures is not a budget."""
        service = AgentRunnerService(_db())
        ledger = SpendLedger()
        ledger.record("gpt-4.1", RequestUsage(input_tokens=1_000_000), "openai")
        prepared = _prepared(ledger)

        with patch(
            "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
        ) as finish:
            await service.finish(prepared, status=RunStatus.FAILED, error="boom")

        recorded = finish.call_args.kwargs
        assert recorded["status"] == RunStatus.FAILED.value
        assert recorded["cost_usd"] == Decimal("2.00")
        assert recorded["error"] == "boom"

    @pytest.mark.anyio
    async def test_partial_pricing_is_flagged_on_the_run(self):
        service = AgentRunnerService(_db())
        ledger = SpendLedger()
        ledger.record(
            "mystery-model", RequestUsage(input_tokens=1000, output_tokens=1000), "openai"
        )
        prepared = _prepared(ledger)

        with patch(
            "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
        ) as finish:
            await service.finish(prepared, status=RunStatus.COMPLETED)

        assert finish.call_args.kwargs["cost_is_partial"] is True

    @pytest.mark.anyio
    async def test_budget_stop_is_not_recorded_as_a_failure(self):
        """It is the platform working; an operator filtering for problems should not see it."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(
            side_effect=BudgetExceeded(
                limit_usd=Decimal("1"), spent_usd=Decimal("1.2"), scope=BudgetScope.AGENT
            )
        )

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            patch.object(service, "_notify", new=AsyncMock()) as notify,
        ):
            output, _ = await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert output == ""
        assert finish.call_args.kwargs["status"] == RunStatus.BUDGET_EXCEEDED.value
        # The stop is also reported: a run started from Slack or a schedule
        # ends silently otherwise, and the first anybody hears of the limit is
        # somebody asking why the agent went quiet.
        assert notify.call_args.kwargs["status"] is RunStatus.BUDGET_EXCEEDED

    @pytest.mark.anyio
    async def test_a_guardrail_block_is_its_own_outcome_not_a_failure(self):
        """A refusal, recorded like `BUDGET_EXCEEDED` rather than `FAILED`.

        The clause does not re-raise, so `execute` returns the empty answer, and
        the stored `error` is the guardrail's safe message - the edge and the
        refusal, never the content that tripped it.
        """
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(
            side_effect=GuardrailBlocked(
                edge="input", message="This request was blocked by an input guardrail."
            )
        )

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            patch.object(service, "_notify", new=AsyncMock()),
        ):
            output, _ = await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert output == ""
        assert finish.call_args.kwargs["status"] == RunStatus.GUARDRAIL_BLOCKED.value
        assert finish.call_args.kwargs["error"] == "This request was blocked by an input guardrail."

    @pytest.mark.anyio
    async def test_a_successful_run_returns_its_answer(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(return_value=MagicMock(output="the answer"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        ):
            output, _ = await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert output == "the answer"
        assert finish.call_args.kwargs["status"] == RunStatus.COMPLETED.value

    @pytest.mark.anyio
    async def test_an_unexpected_error_propagates_but_is_still_accounted(self):
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(side_effect=RuntimeError("provider down"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            pytest.raises(RuntimeError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert finish.call_args.kwargs["status"] == RunStatus.FAILED.value

    @pytest.mark.anyio
    async def test_a_failed_run_records_the_refusal_and_not_the_provider(self, caplog):
        """The stored `error` is read in run history weeks later by anyone who
        can see the run, and a model client puts the failing request in its
        message - so a tenant's own endpoint, with the key still in its query
        string, was being served to every member (#676). The text stays in the
        log, where an operator already looks."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        vendor_text = "401 from https://llm.acme.internal/v1/chat?api_key=sk-live-9f2c"
        prepared.built.agent.run = AsyncMock(side_effect=RuntimeError(vendor_text))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            caplog.at_level(logging.ERROR, logger="app.services.agent_runner"),
            pytest.raises(RuntimeError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert finish.call_args.kwargs["error"] == (
            "The run did not finish (RuntimeError) - retry it, and check the agent's "
            "model profile if it keeps failing. The server log has the full error."
        )
        # The endpoint and status stay in the log; the credential in the query
        # string is redacted there by the PII filter when installed (#440), so this
        # asserts the part present either way.
        assert "401 from https://llm.acme.internal/v1/chat" in caplog.text


class TestWhatAFailedRunIsAllowedToSay:
    """`run_failure_summary` - the one sentence `agent_runs.error` may hold.

    A stored column with a longer life and a wider audience than an HTTP body:
    the row is on `AgentRunRead` and rendered in run history to every member who
    can read it. The rule is #423's, one surface over (#676).
    """

    def test_a_provider_client_reaches_the_row_as_its_class_and_nothing_else(self):
        summary = run_failure_summary(
            RuntimeError("connect to https://llm.acme.internal/v1?api_key=sk-live-9f2c failed")
        )

        assert summary == (
            "The run did not finish (RuntimeError) - retry it, and check the agent's "
            "model profile if it keeps failing. The server log has the full error."
        )

    def test_a_provider_status_survives_because_it_is_what_a_person_acts_on(self):
        """404 is a model the profile names and the provider does not have, 401 a
        credential, 429 a rate limit - all four are `ModelHTTPError`, so a bare
        class name would take away every failure a person can fix themselves.
        `ModelHTTPError.__str__` carries the response body; the status code is an
        `int` and carries nothing."""
        raised = ModelHTTPError(
            status_code=404,
            model_name="gpt-5-turbo",
            body={"error": "https://llm.acme.internal/v1?api_key=sk-live-9f2c"},
        )

        summary = run_failure_summary(raised)

        assert summary.startswith("The run did not finish (ModelHTTPError, HTTP 404) - ")
        assert "sk-live-9f2c" not in summary

    def test_a_task_group_is_unwrapped_to_the_failure_it_is_hiding(self):
        """MCP toolsets and delegated runs sit on anyio task groups, so their
        failures arrive as an `ExceptionGroup` - whose own name diagnoses
        nothing, and which would spend the status code on exactly the failures
        most likely to carry one."""
        raised = ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ModelHTTPError(status_code=401, model_name="gpt-5", body="bad key")],
        )

        assert run_failure_summary(raised).startswith(
            "The run did not finish (ModelHTTPError, HTTP 401) - "
        )

    def test_our_own_refusal_is_kept_whole_because_we_wrote_it(self):
        """A message written in this repository, and the most useful thing an
        operator can be shown - replacing "No model profile is configured for
        this agent" with a class name answers the question the row is opened to
        ask with a shrug."""
        assert (
            run_failure_summary(BadRequestError(message="No model profile is configured"))
            == "No model profile is configured"
        )


class TestWhatANonStreamingRunRecords:
    """The transcript, written by the runner rather than by each surface.

    Four surfaces reached `_run` and recorded nothing: the embedded widget, a
    channel mention, the HTTP API and every resumed run. An organization was
    billed for an answer given to a visitor on a client's site, with no row
    saying what was asked or what was said back. The channel bot did write two
    lines of text and dropped the tool calls, the model and the version.

    So the write moved to the one place a non-streaming run executes. The
    streaming chat does not come through here and keeps its own, because it has
    events to attach and a socket to answer on.
    """

    @staticmethod
    def _answered(output: object, messages: list[Any] | None = None) -> MagicMock:
        return MagicMock(output=output, new_messages=MagicMock(return_value=messages or []))

    @pytest.mark.anyio
    async def test_the_question_the_answer_and_the_tool_calls_all_reach_the_transcript(self):
        conversation_id = uuid.uuid4()
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=conversation_id)
        prepared.built.agent.run = AsyncMock(
            return_value=self._answered(
                "sent",
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="send_email",
                                args={"to": "ada@example.com"},
                                tool_call_id="c1",
                            )
                        ]
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(tool_name="send_email", content="ok", tool_call_id="c1")
                        ]
                    ),
                ],
            )
        )

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()) as record,
        ):
            await service.execute(_ctx(), uuid.uuid4(), "email ada")

        written = record.await_args.kwargs
        assert (written["prompt"], written["answer"]) == ("email ada", "sent")
        assert written["model_label"] == "gpt-4.1"
        assert [(call.tool_name, call.args, call.result) for call in written["tool_calls"]] == [
            ("send_email", {"to": "ada@example.com"}, "ok")
        ]
        assert written["parked"] == frozenset()

    @pytest.mark.anyio
    async def test_a_run_that_broke_still_records_what_was_asked(self):
        """The run that failed is the one somebody opens. Without the question
        there is nothing on the page to interpret the failure against."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        prepared.built.agent.run = AsyncMock(side_effect=RuntimeError("provider down"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()) as record,
            pytest.raises(RuntimeError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "email ada")

        written = record.await_args.kwargs
        assert (written["prompt"], written["answer"]) == ("email ada", "")

    @pytest.mark.anyio
    async def test_an_attached_file_is_not_recorded_as_a_repr_of_itself(self):
        """A prompt an attachment was folded into arrives as parts. Only the text
        is the turn; the binary part is the file, and its `repr` in the message
        body is worse than nothing."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        prepared.built.agent.run = AsyncMock(return_value=self._answered("read it"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch(
                "app.services.agent_runner.AttachmentRouter.build_prompt",
                new=AsyncMock(return_value=["summarise this", object()]),
            ),
            patch.object(service.transcript, "record", new=AsyncMock()) as record,
        ):
            await service.execute(_ctx(), uuid.uuid4(), "summarise this", attachments=[MagicMock()])

        assert record.await_args.kwargs["prompt"] == "summarise this"


class TestStoppingANonStreamingRun:
    """A cancelled run, through `execute`.

    `asyncio.CancelledError` is a `BaseException`, so neither `except` clause in
    `_run` sees it, and both halves of the accounting failed independently: the
    status stayed at its initial `FAILED` with no error text, and the terminal
    write was rolled back by a session exit that only commits on a clean one -
    leaving the row `RUNNING` for ever, and the delegations underneath it
    recorded nowhere.

    The shape is `tests/test_agent_session.py::TestStoppingATurnMidDelegation`'s:
    the ledger matters as much as the status, because a cancelled run that spent
    two dollars and records zero is the hole cancellation opens.
    """

    @pytest.mark.anyio
    async def test_a_cancelled_run_is_recorded_as_cancelled_with_what_it_spent(self):
        """Cancelled is not failed, and the tokens spent up to here were spent.

        Recorded as `FAILED` with `error=None` before the fix, which is precisely
        the confusion `BUDGET_EXCEEDED` was given its own status to avoid: an
        operator filtering run history for problems wades through runs that were
        working correctly and were stopped.
        """
        db = _db()
        service = AgentRunnerService(db)
        ledger = SpendLedger()
        ledger.record("gpt-4.1", RequestUsage(input_tokens=1_000_000), "openai")
        prepared = _prepared(ledger)
        prepared.built.agent.run = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            # Re-raised, not swallowed: whoever cancelled is entitled to see it
            # happen, and a `CancelledError` absorbed here would leave the task
            # that requested the stop waiting for one that never arrives.
            pytest.raises(asyncio.CancelledError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        recorded = finish.call_args.kwargs
        assert recorded["status"] == RunStatus.CANCELLED.value
        assert recorded["error"] is None
        assert recorded["cost_usd"] == Decimal("2.00")
        # And it survives. `get_db_session` commits on a clean exit, which a
        # propagating `BaseException` is not, so without the terminal commit the
        # row above was written and then rolled straight back. Two commits: the
        # one that made the run row visible before the model was called, and the
        # one that lands the terminal write.
        assert db.commit.await_count == 2

    @pytest.mark.anyio
    async def test_a_cancelled_run_keeps_the_delegation_rows_underneath_it(self):
        """Same rollback, one level down.

        A delegate's row is the only record of what that agent cost, so a
        delegation that spent money and recorded nothing is a bill nobody can
        explain. The rows go in after the parent's - they carry `parent_run_id` -
        so the commit has to come after both, and this asserts the order rather
        than only that each happened.
        """
        db = _db()
        service = AgentRunnerService(db)
        moment = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
        delegation = RecordedDelegation(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            agent_version_id=uuid.uuid4(),
            task_id="4f2a1b8c",
            status=RunStatus.CANCELLED,
            model_label="gpt-4.1",
            provider="openai",
            secret_id=uuid.uuid4(),
            input_tokens=7,
            output_tokens=3,
            cost_usd=Decimal("2.00"),
            cost_is_partial=False,
            started_at=moment,
            ended_at=moment,
        )
        prepared = _prepared()
        prepared.delegations = [delegation]
        prepared.built.agent.run = AsyncMock(side_effect=asyncio.CancelledError)

        order: list[str] = []

        def note(name: str) -> Callable[..., Awaitable[MagicMock]]:
            async def call(*_args: Any, **_kwargs: Any) -> MagicMock:
                order.append(name)
                return MagicMock()

            return call

        db.commit = AsyncMock(side_effect=note("commit"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch(
                "app.services.agent_runner.agent_run_repo.finish_run",
                new=AsyncMock(side_effect=note("parent")),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.record_delegated_run",
                new=AsyncMock(side_effect=note("delegation")),
            ) as write,
            pytest.raises(asyncio.CancelledError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        # The first commit is the one that opened the run to other sessions
        # before the model was called; the terminal one comes after both writes,
        # because the delegation rows carry `parent_run_id`.
        assert order == ["commit", "parent", "delegation", "commit"]
        written = write.await_args.kwargs
        assert written["run_id"] == delegation.id
        assert written["status"] == RunStatus.CANCELLED.value
        assert written["cost_usd"] == Decimal("2.00")


class TestMarkRunning:
    @pytest.mark.anyio
    async def test_leaving_the_queue_clears_the_parks_end_time(self):
        """The park's `finish_run` wrote `ended_at`, and the replay's opening
        commit publishes the row mid-run (#12) - left in place, a running run
        would read as finished to every duration query, wearing the
        pre-approval segment's span."""
        from app.repositories import agent_run as agent_run_module

        db = _db()
        run = MagicMock(status=RunStatus.AWAITING_APPROVAL.value, ended_at=datetime.now(UTC))

        await agent_run_module.mark_running(db, run=run)

        assert run.status == RunStatus.RUNNING.value
        assert run.ended_at is None


class TestTheTransactionEndsBeforeTheModelCall:
    """The run row is committed before the model is asked anything (#12).

    Two things hang on the order rather than on the commit merely happening:
    the row is visible from another session for the whole life of the run, and
    the pooled connection is returned instead of sitting `idle in transaction`
    for the minutes a model call can take - fifteen concurrent runs used to be
    the whole pool.
    """

    @pytest.mark.anyio
    async def test_the_run_row_is_committed_before_the_model_is_called(self):
        db = _db()
        service = AgentRunnerService(db)
        prepared = _prepared()
        order: list[str] = []

        async def commit() -> None:
            order.append("commit")

        async def model(*_args: Any, **_kwargs: Any) -> MagicMock:
            order.append("model")
            return MagicMock(output="hi")

        db.commit = AsyncMock(side_effect=commit)
        prepared.built.agent.run = AsyncMock(side_effect=model)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert order[:2] == ["commit", "model"]


class TestApprovals:
    @pytest.mark.anyio
    async def test_deciding_records_the_arguments_that_were_authorised(self):
        """Approving a tool name without its arguments is a rubber stamp."""
        ctx = _ctx()
        approval = MagicMock(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            tool_id="send_email",
            tool_args={"to": "customer@example.com"},
            status=ApprovalStatus.PENDING.value,
        )

        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval",
                new=AsyncMock(return_value=approval),
            ) as decide,
            patch("app.services.approvals.record_audit", new=AsyncMock()) as audit,
        ):
            await ApprovalService(_db()).decide(ctx, approval.id, approved=True)

        assert decide.call_args.kwargs["status"] == ApprovalStatus.APPROVED.value
        assert audit.call_args.kwargs["details"]["tool_args"] == {"to": "customer@example.com"}

    @pytest.mark.anyio
    async def test_an_already_decided_request_cannot_be_decided_again(self):
        """Twice-decided would make the trail ambiguous about who authorised it."""
        approval = MagicMock(status=ApprovalStatus.APPROVED.value)
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            pytest.raises(BadRequestError),
        ):
            await ApprovalService(_db()).decide(_ctx(), uuid.uuid4(), approved=False)

    @pytest.mark.anyio
    async def test_an_approval_from_another_org_is_not_found(self):
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await ApprovalService(_db()).decide(_ctx(), uuid.uuid4(), approved=True)

    @pytest.mark.anyio
    async def test_rejection_is_recorded_as_such(self):
        approval = MagicMock(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            tool_id="refund",
            tool_args={},
            status=ApprovalStatus.PENDING.value,
        )
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval",
                new=AsyncMock(return_value=approval),
            ) as decide,
            patch("app.services.approvals.record_audit", new=AsyncMock()) as audit,
        ):
            await ApprovalService(_db()).decide(
                _ctx(), approval.id, approved=False, note="wrong customer"
            )

        assert decide.call_args.kwargs["status"] == ApprovalStatus.REJECTED.value
        assert audit.call_args.kwargs["action"] == "approval.rejected"


class TestParking:
    @pytest.mark.anyio
    async def test_a_parked_run_stores_what_it_needs_to_continue(self):
        """Without the message history, "approve" has nothing to resume into."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.approvals.parked = {"approval-1": "call-1"}
        result = MagicMock(output=DeferredToolRequests())
        result.all_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        ):
            output, _ = await service.execute(_ctx(), uuid.uuid4(), "email the customer")

        assert output == ""
        recorded = finish.call_args.kwargs
        assert recorded["status"] == RunStatus.AWAITING_APPROVAL.value
        assert recorded["paused_state"] == {
            "messages": [],
            "tool_call_ids": {"approval-1": "call-1"},
            # A run that delegated nothing parks with an empty tree, which is what
            # makes the older two-key payload above still resumable: every field
            # added for delegation reads as "this run delegated nothing".
            "delegated_approvals": {},
            "delegations": [],
            # And no kept specialists, which is a run that invented none - or, as
            # here, one whose agent binds no delegation at all (agenticos#175).
            "dynamic_specialists": [],
            # And an empty checklist, which is a run that bound no planning
            # capability: the store the runner always opens held nothing to snapshot.
            "plan": [],
        }

    @pytest.mark.anyio
    async def test_a_parked_run_snapshots_its_plan(self):
        """A run that parks mid-plan resumes with the checklist it had, not an empty
        one: `finish` reads the run's store and folds it into the parked state, which
        `resume` re-seeds. Without this the plan is lost the moment an approval lands."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        await prepared.plan_store.set_items([PlanItem(content="Write the fix")])
        prepared.approvals.parked = {"approval-1": "call-1"}
        result = MagicMock(output=DeferredToolRequests())
        result.all_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        ):
            await service.execute(_ctx(), uuid.uuid4(), "email the customer")

        stored = finish.call_args.kwargs["paused_state"]["plan"]
        assert [item["content"] for item in stored] == ["Write the fix"]

    @pytest.mark.anyio
    async def test_the_plan_the_turn_ended_on_is_written_to_its_conversation(self):
        """A plan store is one run's and a chat message is a run, so the checklist
        an agent wrote was gone by the next message and the agent said it had never
        made one (#1077). The turn writes it to the conversation on the way out."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        await prepared.plan_store.set_items([PlanItem(content="Write the fix")])
        result = MagicMock(output="done")
        result.all_messages = MagicMock(return_value=[])
        result.new_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()),
            patch("app.services.agent_runner.ConversationService") as conversations,
        ):
            conversations.return_value.keep_overhead = AsyncMock()
            conversations.return_value.keep_reminder_state = AsyncMock()
            conversations.return_value.keep_plan = AsyncMock()
            await service.execute(_ctx(), uuid.uuid4(), "fix the bug")

        kept = conversations.return_value.keep_plan
        assert kept.await_args.args[0] == prepared.run.conversation_id
        assert [item["content"] for item in kept.await_args.args[1]] == ["Write the fix"]

    @pytest.mark.anyio
    async def test_a_turn_that_was_not_seeded_a_finished_plan_does_not_delete_it(self):
        """A finished checklist is not seeded, so the store is empty - and writing
        an empty store back would delete the row #1221 promises to keep, on the
        very next ordinary turn."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        prepared.finished_plan_withheld = True
        result = MagicMock(output="done")
        result.all_messages = MagicMock(return_value=[])
        result.new_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()),
            patch("app.services.agent_runner.ConversationService") as conversations,
        ):
            conversations.return_value.keep_overhead = AsyncMock()
            conversations.return_value.keep_reminder_state = AsyncMock()
            conversations.return_value.keep_plan = AsyncMock()
            await service.execute(_ctx(), uuid.uuid4(), "something else entirely")

        conversations.return_value.keep_plan.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_new_plan_written_over_a_withheld_one_still_replaces_the_row(self):
        """The withholding is only about an empty store. An agent that starts new
        work writes a plan, and that is what the conversation should hold."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        prepared.finished_plan_withheld = True
        await prepared.plan_store.set_items([PlanItem(content="Write the next fix")])
        result = MagicMock(output="done")
        result.all_messages = MagicMock(return_value=[])
        result.new_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()),
            patch("app.services.agent_runner.ConversationService") as conversations,
        ):
            conversations.return_value.keep_overhead = AsyncMock()
            conversations.return_value.keep_reminder_state = AsyncMock()
            conversations.return_value.keep_plan = AsyncMock()
            await service.execute(_ctx(), uuid.uuid4(), "start the next thing")

        kept = conversations.return_value.keep_plan
        assert [item["content"] for item in kept.await_args.args[1]] == ["Write the next fix"]

    @pytest.mark.anyio
    async def test_a_parked_runs_transcript_marks_the_call_that_is_waiting(self):
        """The transcript rows are the only account of the turn a reload has, and
        they used to say `running` for the very call somebody has to decide about -
        so a reopened conversation showed the step as ran and said nothing about
        waiting (#601)."""
        service = AgentRunnerService(_db())
        prepared = _prepared(conversation_id=uuid.uuid4())
        prepared.approvals.parked = {"approval-1": "call-1"}
        result = MagicMock(output=DeferredToolRequests())
        result.all_messages = MagicMock(return_value=[])
        result.new_messages = MagicMock(return_value=[])
        prepared.built.agent.run = AsyncMock(return_value=result)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.transcript, "record", new=AsyncMock()) as record,
        ):
            await service.execute(_ctx(), uuid.uuid4(), "email the customer")

        assert record.await_args.kwargs["parked"] == frozenset({"call-1"})

    @pytest.mark.anyio
    async def test_the_delegation_tree_is_folded_in_without_the_surface_supplying_it(self):
        """A surface reports its own position; the tree underneath is the runner's.

        Both surfaces that park a run construct the state themselves, and a
        delegation is a tool call named `task` that either answers or does not - so
        neither can see what a delegate was in the middle of. Folding it in here is
        the same reasoning as resolving the run's budget caps here: a thing every
        surface has to remember is a thing the next surface will not, and this one
        fails by answering a different question rather than by raising.
        """
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.approvals.parked = {"approval-1": "the-delegates-call"}
        prepared.approvals.requested = [
            ParkedApproval(
                approval_id=uuid.UUID(int=1),
                tool_call_id="the-delegates-call",
                tool_name="send_email",
                tool_args={},
                subagent="researcher",
                task_id="4f2a1b8c",
            )
        ]
        prepared.stash = DelegationStash(
            parked=[
                ParkedDelegation(
                    tool_call_id="the-parents-task-call",
                    task_id="4f2a1b8c",
                    parent_task_id=None,
                    subagent="researcher",
                    agent_id=None,
                    agent_version_id=None,
                    child_run_id="a-child-run",
                    messages=[{"kind": "request", "parts": []}],
                    spent=DelegationSpend(
                        cost_usd=Decimal("0.25"), input_tokens=7, output_tokens=3
                    ),
                    started_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
                )
            ]
        )

        with patch(
            "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
        ) as finish:
            await service.finish(
                prepared,
                status=RunStatus.AWAITING_APPROVAL,
                # Exactly what a streaming surface passes: its messages and its
                # channel's parked calls, and nothing about the delegation.
                paused_state=PausedRunState(messages=[], tool_call_ids={"approval-1": "x"}),
            )

        stored = finish.call_args.kwargs["paused_state"]
        assert [frame["subagent"] for frame in stored["delegations"]] == ["researcher"]
        assert stored["delegations"][0]["tool_call_id"] == "the-parents-task-call"
        # And what the delegation had already cost, because the turn that continues
        # it measures against a ledger of its own - so a frame without this leaves
        # the child's run row holding the tail of the delegation and none of the
        # work that led up to the approval.
        assert stored["delegations"][0]["cost_usd"] == "0.25"
        assert stored["delegations"][0]["input_tokens"] == 7
        # And when the delegate first began, so the row written when it ends begins
        # there rather than at the resume that settles it (agenticos#245).
        assert stored["delegations"][0]["started_at"] == "2026-08-05T09:00:00Z"
        # And which agent's replay each parked approval belongs to, which is what
        # keeps a delegate's call out of the parent's continuation - Pydantic AI
        # refuses a resume whose results name a call the replay does not contain.
        assert stored["delegated_approvals"] == {str(uuid.UUID(int=1)): "4f2a1b8c"}

    @pytest.mark.anyio
    async def test_a_finished_run_stops_being_resumable(self):
        """State left on a completed run is state somebody eventually replays."""
        service = AgentRunnerService(_db())
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(return_value=MagicMock(output="done"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert finish.call_args.kwargs["paused_state"] is None


class TestResume:
    def _built(self, output: str = "sent"):
        built = MagicMock()
        built.ledger = SpendLedger()
        # A real gauge: what a turn records against its conversation is read off
        # this, and a `MagicMock` answers "yes, summarised" to every turn.
        built.context = ContextGauge()
        built.agent.run = AsyncMock(return_value=MagicMock(output=output))
        return built

    def _version(self):
        version = MagicMock()
        version.spec = {"name": "Clerk"}
        return version

    def _approval(self, *, status: str, tool_args: dict, note: str | None = None):
        return MagicMock(id=uuid.uuid4(), status=status, tool_args=tool_args, note=note)

    @pytest.mark.anyio
    async def test_an_approved_run_continues_from_the_arguments_that_were_approved(self):
        """The whole point: a decision has to actually restart the run."""
        service = AgentRunnerService(_db())
        approval = self._approval(
            status=ApprovalStatus.APPROVED.value, tool_args={"to": "customer@example.com"}
        )
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        built = self._built()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built) as build,
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            segment = await service.resume(_ctx(), run.id)

        assert segment.output == "sent"
        assert finish.call_args.kwargs["status"] == RunStatus.COMPLETED.value

        deferred = built.agent.run.call_args.kwargs["deferred_tool_results"]
        assert deferred.approvals["call-1"].override_args == {"to": "customer@example.com"}
        channel = build.call_args.kwargs["request_approval"]
        assert channel.decided["call-1"] == ApprovalGranted(
            tool_args={"to": "customer@example.com"}
        )

    @pytest.mark.anyio
    async def test_leaving_the_queue_is_committed_before_the_call_is_replayed(self):
        """A crash mid-replay must find the run `running`, not parked.

        `mark_running` only flushed, so a process that died between replaying an
        approved call and the terminal write rolled the status back to
        `awaiting_approval` with the approval still marked approved - and the
        next resume replayed the call, re-sending whatever it had already sent
        (#3). The commit in `_run` sits between the two, so the state transition
        `claim_parked_run` guards is durable before anything side-effecting runs.
        """
        db = _db()
        service = AgentRunnerService(db)
        approval = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        built = self._built()
        order: list[str] = []

        async def note_commit() -> None:
            order.append("commit")

        async def note_mark(*_args: Any, **_kwargs: Any) -> MagicMock:
            order.append("mark_running")
            return run

        async def note_model(*_args: Any, **_kwargs: Any) -> MagicMock:
            order.append("model")
            return MagicMock(output="sent")

        db.commit = AsyncMock(side_effect=note_commit)
        built.agent.run = AsyncMock(side_effect=note_model)

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.mark_running",
                new=AsyncMock(side_effect=note_mark),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            await service.resume(_ctx(), run.id)

        assert order[:3] == ["mark_running", "commit", "model"]

    @pytest.mark.anyio
    async def test_a_resumed_run_records_its_continuation_and_invents_no_question(self):
        """A resumed run used to record nothing at all: `resume` replays through
        `_run`, and the write lived in each surface. So the decision a person made
        produced work with no transcript.

        `prompt=None` is the other half. The run picks up at the tool call it
        stopped on - there is no new question, and writing one would put words in
        somebody's mouth."""
        service = AgentRunnerService(_db())
        approval = self._approval(
            status=ApprovalStatus.APPROVED.value, tool_args={"to": "customer@example.com"}
        )
        run = _parked_run(
            conversation_id=uuid.uuid4(),
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}},
        )

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=self._built()),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch.object(service.transcript, "record", new=AsyncMock()) as record,
        ):
            await service.resume(_ctx(), run.id)

        written = record.await_args.kwargs
        assert (written["prompt"], written["answer"]) == (None, "sent")

    @pytest.mark.anyio
    async def test_a_continuation_hands_back_what_it_called(self):
        """The only account of the second half of a turn.

        A continuation runs inside the resume request, not on the socket the
        conversation streams, so no `tool_call` frame announces what it did. A
        caller handed only the answer drew the approved call finishing and nothing
        after it - so approving looked like it had done nothing, and the next
        approval request arrived for a step that had never appeared.
        """
        service = AgentRunnerService(_db())
        approval = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        built = self._built()
        built.agent.run = AsyncMock(
            return_value=MagicMock(
                output="six sheets",
                new_messages=lambda: [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="execute",
                                args={"command": "python read.py"},
                                tool_call_id="call-2",
                            )
                        ]
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="execute", content="6 sheets", tool_call_id="call-2"
                            )
                        ]
                    ),
                ],
            )
        )

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            segment = await service.resume(_ctx(), run.id)

        assert [(call.tool_name, call.args, call.result) for call in segment.tool_calls] == [
            ("execute", {"command": "python read.py"}, "6 sheets")
        ]

    @pytest.mark.anyio
    async def test_a_resumed_run_keeps_the_spend_it_had_already_booked(self):
        """Otherwise finishing it would overwrite the cost, and reset the budget."""
        service = AgentRunnerService(_db())
        approval = self._approval(status=ApprovalStatus.REJECTED.value, tool_args={}, note="no")
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        built = self._built()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built) as build,
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()) as finish,
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            await service.resume(_ctx(), run.id)

        recorded = finish.call_args.kwargs
        assert recorded["cost_usd"] == Decimal("0.25")
        assert recorded["input_tokens"] == 1000
        channel = build.call_args.kwargs["request_approval"]
        assert channel.decided["call-1"] == ApprovalRejected(note="no")

    @pytest.mark.anyio
    async def test_a_decision_from_an_earlier_park_is_not_replayed(self):
        """A run can park twice; answering the first call again would repeat it."""
        service = AgentRunnerService(_db())
        stale = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={"to": "a@b.c"})
        current = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={"to": "d@e.f"})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(current.id): "call-2"}}
        )
        built = self._built()

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[stale, current]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            await service.resume(_ctx(), run.id)

        deferred = built.agent.run.call_args.kwargs["deferred_tool_results"]
        assert list(deferred.approvals) == ["call-2"]

    @pytest.mark.anyio
    async def test_a_run_from_another_org_is_not_found(self):
        service = AgentRunnerService(_db())
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await service.resume(_ctx(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_run_still_parked_reports_what_it_is_waiting_on(self):
        """The half a resume needs to hand back, and the reason it exists.

        A continuation runs the agent, and the agent can reach a second gated call
        and park again. The response used to carry `status` alone, so a client was
        told "still awaiting approval" and given nothing to approve - and the
        continuation runs over HTTP rather than the socket a conversation streams,
        so no frame carried the new calls either. The run could only be finished
        from the approvals queue on another page.
        """
        service = AgentRunnerService(_db())
        approval_id = uuid.uuid4()
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval_id): "tc-2"}}
        )
        decided = MagicMock(id=uuid.uuid4(), status="approved", tool_id="execute", tool_args={})
        pending = MagicMock(
            id=approval_id, status="pending", tool_id="execute", tool_args={"command": "ls"}
        )
        with patch(
            "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
            new=AsyncMock(return_value=[decided, pending]),
        ):
            parked = await service.parked_calls(_ctx(), run)

        # The decided one is not still waiting, and the pending one carries the step
        # it parked - which the approval row does not hold, so it comes off the run's
        # own paused state.
        assert [(call.id, call.tool_call_id, call.tool_name) for call in parked] == [
            (approval_id, "tc-2", "execute")
        ]
        assert parked[0].tool_args == {"command": "ls"}

    @pytest.mark.anyio
    async def test_a_run_that_finished_is_waiting_on_nothing(self):
        """Asked of every resume, so the common answer has to be cheap and empty."""
        service = AgentRunnerService(_db())

        assert (
            await service.parked_calls(_ctx(), _parked_run(status=RunStatus.COMPLETED.value)) == []
        )

    @pytest.mark.anyio
    async def test_a_run_parked_before_the_map_existed_still_names_its_calls(self):
        """`tool_call_id` is a step a surface cannot mark, not a call it cannot decide."""
        service = AgentRunnerService(_db())
        run = _parked_run(paused_state={"messages": []})
        pending = MagicMock(id=uuid.uuid4(), status="pending", tool_id="execute", tool_args={})
        with patch(
            "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
            new=AsyncMock(return_value=[pending]),
        ):
            parked = await service.parked_calls(_ctx(), run)

        assert parked[0].tool_call_id is None

    @pytest.mark.anyio
    async def test_a_run_that_is_not_parked_cannot_be_resumed(self):
        """Resuming a completed run would replay tool calls it already made."""
        service = AgentRunnerService(_db())
        run = _parked_run(status=RunStatus.COMPLETED.value)
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            pytest.raises(BadRequestError, match="not waiting"),
        ):
            await service.resume(_ctx(), run.id)

    @pytest.mark.anyio
    async def test_a_parked_run_without_stored_state_fails_loudly(self):
        service = AgentRunnerService(_db())
        run = _parked_run(paused_state=None)
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            pytest.raises(BadRequestError, match="state needed"),
        ):
            await service.resume(_ctx(), run.id)

    @pytest.mark.anyio
    async def test_an_outstanding_decision_blocks_the_resume(self):
        """Continuing now would drop that call silently."""
        service = AgentRunnerService(_db())
        run = _parked_run()
        pending = self._approval(status=ApprovalStatus.PENDING.value, tool_args={})
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[pending]),
            ),
            pytest.raises(BadRequestError, match="awaiting a decision"),
        ):
            await service.resume(_ctx(), run.id)

    @pytest.mark.anyio
    async def test_a_run_whose_version_is_gone_cannot_be_resumed(self):
        """Continuing on whatever is published now answers a question nobody asked."""
        service = AgentRunnerService(_db())
        run = _parked_run()
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=None),
            ),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            pytest.raises(BadRequestError, match="no longer exists"),
        ):
            await service.resume(_ctx(), run.id)

    @pytest.mark.anyio
    async def test_a_run_with_no_recorded_version_cannot_be_resumed(self):
        service = AgentRunnerService(_db())
        run = _parked_run(agent_version_id=None)
        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            pytest.raises(BadRequestError, match="no longer exists"),
        ):
            await service.resume(_ctx(), run.id)

    @pytest.mark.anyio
    async def test_a_run_leaves_the_queue_before_anything_is_replayed(self):
        """A double-clicked Approve must not replay the side effect twice.

        The row is locked while this transaction runs; what makes the second
        request refuse afterwards is finding the run no longer parked, so the
        status has to change before the tool call is replayed, not after.
        """
        service = AgentRunnerService(_db())
        approval = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        status_when_replayed: list[str] = []

        async def record_status(*args, **kwargs):
            status_when_replayed.append(run.status)
            return MagicMock(output="sent")

        built = self._built()
        built.agent.run = AsyncMock(side_effect=record_status)

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        ):
            await service.resume(_ctx(), run.id)

        assert status_when_replayed == [RunStatus.RUNNING.value]

    @pytest.mark.anyio
    async def test_a_run_whose_spec_no_longer_builds_is_still_resumable(self):
        """A build that refuses must not spend the decision that got it there.

        `claim_parked_run` only ever hands out a run that is still
        `awaiting_approval`, so a run flipped to `running` by an attempt that then
        failed to build is a run nobody can finish - carrying an approval a person
        granted, and reporting nothing. The build therefore happens while the row
        is still parked.

        The failure here is the one that happens to real deployments: the secret a
        binding names was deleted after the run parked, so the unsealed map no
        longer holds it and the registry refuses rather than running the
        capability without its key. What proves the run survived it is the second
        attempt reaching the same refusal - not "this run is not waiting for
        approval".
        """
        service = AgentRunnerService(_db())
        approval = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        version = MagicMock()
        version.spec = AgentSpec(
            name="Researcher",
            model_profile_id=uuid.uuid4(),
            capabilities=[
                CapabilityBindingSpec(
                    id="web_research",
                    config={"method": "tavily"},
                    secret_id=uuid.uuid4(),
                )
            ],
        ).model_dump(mode="json")

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=version),
            ),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            # What a deleted secret looks like from here: the id resolves to
            # nothing, which is exactly what `resolve_for_bindings` returns for a
            # row that is gone.
            patch.object(service.secrets, "resolve_for_bindings", new=AsyncMock(return_value={})),
        ):
            for _ in range(2):
                with pytest.raises(BadRequestError, match="no longer has"):
                    await service.resume(_ctx(), run.id)

        assert run.status == RunStatus.AWAITING_APPROVAL.value

    @pytest.mark.anyio
    async def test_a_resume_whose_continuation_fails_records_the_status_and_conveys_it(self):
        """The failure reaches the caller, and the recorded status travels with it.

        The gap #262 fixes: when the continuation raises, `_run` records the run
        `failed` and commits it, then re-raises - and the resume route used to let
        that raw exception through with no status, so a web-chat surface (which
        learns a delegate's outcome only from this HTTP answer) left an
        `awaiting_approval` panel waiting on a decision already spent, on a run that
        can no longer be resumed. `resume` now re-raises `RunExecutionError` carrying
        the recorded status, while still surfacing the failure - the original
        exception is chained, not swallowed.
        """
        service = AgentRunnerService(_db())
        approval = self._approval(status=ApprovalStatus.APPROVED.value, tool_args={})
        run = _parked_run(
            paused_state={"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
        )
        built = self._built()
        blew_up = RuntimeError("the tool the approval unblocked then failed")
        built.agent.run = AsyncMock(side_effect=blew_up)

        # The real `finish` runs; `finish_run` is the one call stubbed, and it stamps
        # the terminal status onto the row the way the repository does - which is what
        # makes `run.status` the recorded truth by the time `resume` reads it.
        async def record_terminal_status(*args: Any, **kwargs: Any) -> Any:
            run.status = kwargs["status"]
            return run

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=self._version()),
            ),
            patch("app.services.agent_runner.build_agent", return_value=built),
            patch(
                "app.services.agent_runner.agent_run_repo.finish_run",
                new=AsyncMock(side_effect=record_terminal_status),
            ),
            patch.object(service.registry, "get", new=AsyncMock(return_value=MagicMock())),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            pytest.raises(RunExecutionError) as raised,
        ):
            await service.resume(_ctx(), run.id)

        # The run was recorded terminal, and the caller is told which status.
        assert run.status == RunStatus.FAILED.value
        assert raised.value.details == {"run_id": str(run.id), "status": RunStatus.FAILED.value}
        # The failure is conveyed, not hidden: the original exception is chained.
        assert raised.value.__cause__ is blew_up


class TestWhoTheRunSaysItIs:
    """What the agent is told about the person asking.

    `AgentDeps.user_id` reaches every tool, and a tool that writes it into a
    record, a filter or a prompt cannot tell a real id from a plausible-looking
    string. That makes stringifying an absent subject worse than passing none:
    `"None"` is the one wrong answer that looks like an answer.
    """

    @staticmethod
    async def _built_with(ctx: AuthContext) -> dict[str, object]:
        """Prepare a run and hand back what the factory was called with."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(ctx, agent.id)

        return build.call_args.kwargs

    @pytest.mark.anyio
    async def test_a_run_with_a_person_behind_it_names_them(self):
        ctx = _ctx()

        assert (await self._built_with(ctx))["user_id"] == str(ctx.user_id)

    @pytest.mark.anyio
    async def test_a_run_with_nobody_behind_it_says_nobody_rather_than_the_string_None(self):
        """`str(None)` is `"None"`, and a tool would take it for an id."""
        anonymous = AuthContext.anonymous(uuid.uuid4())

        assert (await self._built_with(anonymous))["user_id"] is None

    @pytest.mark.anyio
    async def test_a_run_with_nobody_behind_it_opens_a_row_with_no_user(self):
        """`agent_runs.user_id` is nullable, and null is the honest value.

        The run is still accounted for - it has an organization, a cost and a
        surface - it simply has no person to attribute it to.
        """
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create_run,
            patch("app.services.agent_runner.build_agent"),
        ):
            await service.prepare(AuthContext.anonymous(uuid.uuid4()), agent.id)

        assert create_run.call_args.kwargs["user_id"] is None

    @pytest.mark.anyio
    async def test_a_channel_run_records_the_chat_account_that_asked(self):
        """Who asked and who it ran as are different questions in a room (#639).

        The row carries both, so a turn from a chat account nobody has linked is
        still attributable - and becomes attributable to a *person* the moment
        that account is linked, without rewriting the run.
        """
        identity_id = uuid.uuid4()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        ctx = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.VIEWER,
            channel_identity_id=identity_id,
        )

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create_run,
            patch("app.services.agent_runner.build_agent"),
        ):
            await service.prepare(ctx, agent.id, surface=RunSurface.MATTERMOST)

        assert create_run.call_args.kwargs["channel_identity_id"] == identity_id

    @pytest.mark.anyio
    async def test_a_run_from_anywhere_else_records_no_chat_account(self):
        """The dashboard, the playground and the API are reached as a person."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create_run,
            patch("app.services.agent_runner.build_agent"),
        ):
            await service.prepare(_ctx(), agent.id)

        assert create_run.call_args.kwargs["channel_identity_id"] is None


def _exposure(*, organization_id=None, environment_id=None, surface="web", prompt=None, tools=None):
    """A binding row.

    `surface`, `prompt` and `tools` are real values rather than mock attributes:
    the run appends what the surface renders, what the binding was told, and
    which channel lookups it granted. A mock for the first two is a `MagicMock`
    concatenated into the agent's instructions, and one for the third is a
    capability config the model would be offered.
    """
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        environment_id=environment_id,
        surface=surface,
        prompt=prompt,
        tools=tools or [],
    )


class TestARunThatArrivedThroughABinding:
    """Attribution: the run has to carry which binding admitted it.

    "Where did this run come from" is the first question asked about a run
    nobody recognizes, and after the binding is deleted the run's own row is
    the only record of the answer.
    """

    @staticmethod
    async def _prepare(exposure, *, run=None):
        """Prepare a run and hand back the row that was opened and the caps built."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        opened = run or MagicMock(id=uuid.uuid4(), exposure_id=exposure.id if exposure else None)

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=opened),
            ) as create_run,
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(_ctx(), agent.id, exposure=exposure)

        return create_run.call_args.kwargs, build.call_args.kwargs

    @pytest.mark.anyio
    async def test_the_bindings_environment_decides_the_version_and_is_recorded(self):
        """A bot bound to `dev` serves dev without the channel router knowing
        environments exist - the binding carries it, the run records it."""
        environment_id = uuid.uuid4()
        exposure = _exposure(environment_id=environment_id)
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        pinned_version_id = uuid.uuid4()

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, AgentSpec(name="Support"), pinned_version_id)),
            ) as resolve,
            patch(
                "app.services.agent_runner.agent_environment_repo.get",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create_run,
            patch("app.services.agent_runner.build_agent"),
        ):
            await service.prepare(_ctx(), agent.id, exposure=exposure)

        assert resolve.call_args.kwargs["environment_id"] == environment_id
        opened = create_run.call_args.kwargs
        assert opened["environment_id"] == environment_id
        # The run records the version the environment resolved, not the
        # default of the moment - or history would lie about what answered.
        assert opened["agent_version_id"] == pinned_version_id

    @pytest.mark.anyio
    async def test_the_run_records_the_binding_that_admitted_it(self):
        """Without it, "what has this binding spent" has no answer at all."""
        exposure = _exposure()

        opened, _ = await self._prepare(exposure)

        assert opened["exposure_id"] == exposure.id

    @pytest.mark.anyio
    async def test_a_run_reached_as_a_person_records_no_binding(self):
        """The dashboard, the playground and the API are not places an agent was published to."""
        opened, _ = await self._prepare(None)

        assert opened["exposure_id"] is None


class TestEnvironmentObservability:
    """An environment aims its runs' traces; the tag is always its name."""

    @pytest.mark.anyio
    async def test_the_environments_token_and_name_win(self):
        """The tag comes from the row's name, never from configuration - so the
        tag and the environment cannot disagree."""
        env_secret = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(
                token_secret_id=uuid.uuid4(), service_name="from-spec", environment="free-text"
            ),
        )
        environment = MagicMock(logfire_token_secret_id=env_secret, service_name="from-env")
        environment.name = "client-prod"
        service = AgentRunnerService(_db())

        with patch(
            "app.services.agent_runner.agent_environment_repo.get",
            new=AsyncMock(return_value=environment),
        ):
            merged = await service._with_environment_observability(
                _ctx(), spec, environment_id=uuid.uuid4()
            )

        assert merged.observability is not None
        assert merged.observability.token_secret_id == env_secret
        assert merged.observability.service_name == "from-env"
        assert merged.observability.environment == "client-prod"

    @pytest.mark.anyio
    async def test_an_environment_without_a_token_falls_through_to_the_specs(self):
        spec_secret = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(token_secret_id=spec_secret, environment="free-text"),
        )
        environment = MagicMock(logfire_token_secret_id=None, service_name=None)
        environment.name = "dev"
        service = AgentRunnerService(_db())

        with patch(
            "app.services.agent_runner.agent_environment_repo.get",
            new=AsyncMock(return_value=environment),
        ):
            merged = await service._with_environment_observability(
                _ctx(), spec, environment_id=uuid.uuid4()
            )

        assert merged.observability is not None
        assert merged.observability.token_secret_id == spec_secret
        # The one thing the environment always decides.
        assert merged.observability.environment == "dev"

    @pytest.mark.anyio
    async def test_no_token_from_either_source_stays_untraced(self):
        """A tag into nowhere is not observability - the spec is left alone."""
        spec = AgentSpec(name="Support")
        environment = MagicMock(logfire_token_secret_id=None, service_name=None)
        environment.name = "dev"
        service = AgentRunnerService(_db())

        with patch(
            "app.services.agent_runner.agent_environment_repo.get",
            new=AsyncMock(return_value=environment),
        ):
            merged = await service._with_environment_observability(
                _ctx(), spec, environment_id=uuid.uuid4()
            )

        assert merged is spec

    @pytest.mark.anyio
    async def test_no_environment_means_the_spec_as_written(self):
        spec = AgentSpec(name="Support")
        service = AgentRunnerService(_db())

        merged = await service._with_environment_observability(_ctx(), spec, environment_id=None)

        assert merged is spec


class TestTracingSecret:
    @pytest.mark.anyio
    async def test_the_tracing_token_is_unsealed_with_the_capability_secrets(self):
        """One pass over the vault, not two.

        The agent's own Logfire token is the same kind of reference a capability
        secret is, resolved at the same moment - a second unsealing path would
        be a second place for a tenant check to be missed.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        token_secret = uuid.uuid4()
        spec = AgentSpec(
            name="Traced",
            model_profile_id=uuid.uuid4(),
            observability=ObservabilitySpec(token_secret_id=token_secret),
        )

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch.object(
                service.secrets, "resolve_for_bindings", new=AsyncMock(return_value={})
            ) as resolve_secrets,
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent", return_value=MagicMock()),
        ):
            await service.prepare(ctx, agent.id)

        assert resolve_secrets.call_args.args[1] == [token_secret]


class TestTheWorkspaceReachesTheAgent:
    """The capability cannot open its own workspace, so the runner hands it one.

    Opening reads the database - a stored document, the row saying which session
    belongs to which conversation - and capabilities are built inside
    `build_agent`, which holds no session. So the seam is `resources`, the same
    way collection names travel, and if it breaks the agent silently gets a
    scratch workspace that evaporates instead of the one holding its files.
    """

    @staticmethod
    async def _prepare(spec):
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        opened = MagicMock(id=uuid.uuid4(), exposure_id=None)

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=opened),
            ),
            # The workspace row is the only database access `prepare` gained;
            # everything else about the workspace is in-process.
            patch(
                "app.services.sandbox_workspace.workspace_repo.get_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.sandbox_workspace.workspace_repo.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            prepared = await service.prepare(_ctx(), agent.id, conversation_id=uuid.uuid4())

        return prepared, build.call_args.kwargs["resources"]

    @pytest.mark.anyio
    async def test_a_workspace_backend_is_handed_to_the_capability(self):
        spec = AgentSpec(name="Analyst", capabilities=[{"id": "sandbox", "config": {}}])

        prepared, resources = await self._prepare(spec)

        assert prepared.workspace is not None
        assert resources["workspace_backend"] is prepared.workspace.backend

    @pytest.mark.anyio
    async def test_an_agent_without_one_is_handed_nothing(self):
        """A resource key present-but-empty would make the capability build a
        workspace it thinks is real."""
        prepared, resources = await self._prepare(AgentSpec(name="Plain"))

        assert prepared.workspace is None
        assert "workspace_backend" not in resources


class TestWhatTheChannelLetsTheAgentLookUp:
    """The binding decides, and only a channel run gets a directory at all.

    Both halves are here rather than in the capability's own tests, because both
    are wiring: a directory that never reached `resources` and a grant that never
    reached the spec look identical from inside `channel_tools` - it builds
    nothing, and the agent answers without ever mentioning it.
    """

    @staticmethod
    async def _built(*, exposure, directory):
        """Prepare a run and hand back what `build_agent` was given."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(
                    return_value=(agent, AgentSpec(name="Support"), agent.current_version_id)
                ),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(_ctx(), agent.id, exposure=exposure, channel_directory=directory)

        # The spec is positional; everything else the factory takes is a keyword.
        return build.call_args.args[0], build.call_args.kwargs

    @pytest.mark.anyio
    async def test_a_channel_run_hands_the_capability_its_channel(self):
        directory = MagicMock()
        spec, built = await self._built(
            exposure=_exposure(surface="mattermost", tools=["get_channel_info"]),
            directory=directory,
        )

        assert built["resources"][CHANNEL_DIRECTORY_RESOURCE] is directory
        assert [binding.id for binding in spec.capabilities] == ["channel_tools"]

    @pytest.mark.anyio
    async def test_a_run_outside_a_channel_carries_no_directory(self):
        """The dashboard, the API, a schedule. A resource nobody set is the
        capability's own signal that there is nothing here to ask about."""
        spec, built = await self._built(exposure=None, directory=None)

        assert CHANNEL_DIRECTORY_RESOURCE not in built["resources"]
        assert spec.capabilities == []


class TestTheDownRatedMarker:
    """The set run history draws its 👎 from.

    The service adds only its tenant bound - the caller's organization - over
    the repository query, so a wrong argument here is a marker that reaches past
    the organization the reader belongs to. The query itself is proven against a
    real database in `tests/integration/test_run_history_filters.py`.
    """

    @pytest.mark.anyio
    async def test_it_asks_the_repository_within_the_callers_organization(self):
        ctx = _ctx()
        run_ids = [uuid.uuid4(), uuid.uuid4()]
        marked = {run_ids[0]}
        repo = AsyncMock(return_value=marked)
        with patch("app.services.agent_runner.agent_run_repo.down_rated_run_ids", repo):
            result = await AgentRunnerService(_db()).down_rated_run_ids(ctx, run_ids)

        assert result == marked
        assert repo.await_args.kwargs["organization_id"] == ctx.organization_id
        assert repo.await_args.kwargs["run_ids"] == run_ids


class TestTranscriptRatings:
    """The per-turn rating detail the run-detail feedback panel reads.

    The service batches three lookups and assembles one entry per message; the
    queries themselves are proven against a real database in the integration
    suite. What matters here is the assembly - that every id gets an entry, that
    the caller's own thumb is asked for only when a person is behind the request,
    and that a turn nobody rated maps to three empty answers rather than being
    left out of the map.
    """

    @staticmethod
    def _patches(user_ratings, counts, comments):
        return (
            patch(
                "app.services.agent_runner.message_rating_repo.get_user_ratings_for_messages",
                user_ratings,
            ),
            patch(
                "app.services.agent_runner.message_rating_repo.get_rating_counts_for_messages",
                counts,
            ),
            patch(
                "app.services.agent_runner.message_rating_repo.get_down_rating_comments_for_messages",
                comments,
            ),
        )

    @pytest.mark.anyio
    async def test_it_gives_every_message_an_entry_rated_or_not(self):
        ctx = _ctx()
        rated, unrated = uuid.uuid4(), uuid.uuid4()
        user_ratings = AsyncMock(return_value={rated: -1})
        counts = AsyncMock(return_value={rated: {"likes": 0, "dislikes": 2}})
        comments = AsyncMock(return_value={rated: "it invented a policy"})
        p1, p2, p3 = self._patches(user_ratings, counts, comments)
        with p1, p2, p3:
            result = await AgentRunnerService(_db()).transcript_ratings(ctx, [rated, unrated])

        assert result[rated] == {
            "user_rating": -1,
            "rating_count": {"likes": 0, "dislikes": 2},
            "rating_comment": "it invented a policy",
        }
        assert result[unrated] == {
            "user_rating": None,
            "rating_count": None,
            "rating_comment": None,
        }
        assert user_ratings.await_args.kwargs["user_id"] == ctx.user_id

    @pytest.mark.anyio
    async def test_an_empty_page_asks_the_database_nothing(self):
        # A page with no turns must not fan out to three empty-`IN` queries.
        user_ratings, counts, comments = AsyncMock(), AsyncMock(), AsyncMock()
        p1, p2, p3 = self._patches(user_ratings, counts, comments)
        with p1, p2, p3:
            result = await AgentRunnerService(_db()).transcript_ratings(_ctx(), [])

        assert result == {}
        user_ratings.assert_not_awaited()
        counts.assert_not_awaited()
        comments.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_caller_with_no_user_is_not_asked_for_its_own_thumb(self):
        # A service-to-service key reads the transcript but has no thumb of its
        # own, so that lookup is skipped rather than asked with a null user id.
        ctx = AuthContext.anonymous(uuid.uuid4())
        message_id = uuid.uuid4()
        user_ratings = AsyncMock()
        counts = AsyncMock(return_value={message_id: {"likes": 1, "dislikes": 0}})
        comments = AsyncMock(return_value={})
        p1, p2, p3 = self._patches(user_ratings, counts, comments)
        with p1, p2, p3:
            result = await AgentRunnerService(_db()).transcript_ratings(ctx, [message_id])

        assert result[message_id]["user_rating"] is None
        assert result[message_id]["rating_count"] == {"likes": 1, "dislikes": 0}
        user_ratings.assert_not_awaited()


class TestACommitThatCannotLandRunner:
    """The terminal commit must not replace the exception that ended the run (#235)."""

    @pytest.mark.anyio
    async def test_a_failing_commit_does_not_mask_the_cancellation(self):
        """A stop cancels the run; a commit that then cannot land must not turn
        that into a failed run by replacing the `CancelledError`."""
        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not serialize access")])
        service = AgentRunnerService(db)
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            pytest.raises(asyncio.CancelledError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        assert db.commit.await_count == 2

    @pytest.mark.anyio
    async def test_a_failing_commit_on_a_clean_run_still_surfaces(self):
        """When nothing else ended the run, a commit that cannot land is the one
        thing wrong and does surface."""
        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not commit")])
        service = AgentRunnerService(db)
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(return_value=MagicMock(output="the answer"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
            pytest.raises(RuntimeError, match="could not commit"),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

    @pytest.mark.anyio
    async def test_a_failing_finish_does_not_mask_the_cancellation(self):
        """The masking window is the whole terminal write, not only the commit:
        `finish` and `transcript.record` hit the same connection first and must
        not replace the `CancelledError` either (#235)."""
        db = _db()
        service = AgentRunnerService(db)
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch.object(service, "finish", new=AsyncMock(side_effect=RuntimeError("dropped"))),
            pytest.raises(asyncio.CancelledError),
        ):
            await service.execute(_ctx(), uuid.uuid4(), "hello")

        # Only the opening commit; the terminal one is never reached.
        db.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_commit_failure_surfaces_even_inside_a_callers_except(self):
        """#235 review: `sys.exc_info()` would report a *caller's* handled
        exception and wrongly swallow a real commit failure on a run that itself
        completed. The run's own terminal state is tracked instead, so the
        failure surfaces."""
        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not commit")])
        service = AgentRunnerService(db)
        prepared = _prepared()
        prepared.built.agent.run = AsyncMock(return_value=MagicMock(output="ok"))

        with (
            patch.object(service, "prepare", new=AsyncMock(return_value=prepared)),
            patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
        ):
            try:
                raise ValueError("boom")  # noqa: TRY301 - a caller already mid-except
            except ValueError:
                with pytest.raises(RuntimeError, match="could not commit"):
                    await service.execute(_ctx(), uuid.uuid4(), "hello")
