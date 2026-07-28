"""Tests for run execution, accounting and approvals.

Three invariants carry most of the weight here: a run that fails still records
what it spent, a budget stop is recorded as a budget stop rather than as a
failure, and a run parked on an approval can be picked up again - on the version
it was parked on, with the spend it had already booked.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.approval import ApprovalGranted, ApprovalRejected
from app.agents.capabilities.budget import BudgetExceeded, SpendLedger
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus, RunStatus, RunSurface
from app.services.agent_runner import AgentRunnerService, month_start
from app.services.approvals import ApprovalService


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _db(monthly_budget_usd: Decimal | None = None):
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # `db.get` is how the organization row - and with it the org-wide spending
    # cap the runner reads for every run - comes back. Uncapped by default,
    # which is what an organization that never opened the setting looks like.
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=monthly_budget_usd))
    return db


def _prepared(ledger: SpendLedger | None = None):
    prepared = MagicMock()
    prepared.run = MagicMock(id=uuid.uuid4())
    prepared.built = MagicMock()
    prepared.built.ledger = ledger or SpendLedger()
    prepared.approvals.parked = {}
    return prepared


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
                new=AsyncMock(return_value=(agent, spec)),
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

        async def get_collection(_db, collection_id):
            return collections[collection_id]

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec)),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.knowledge_base_repo.get_by_id",
                new=AsyncMock(side_effect=get_collection),
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
        """`mcp_server_ids` is part of the published contract, so it has to act.

        Resolved here, in the one place every surface goes through, and against
        the run's own organization - an agent's reach is a property of the agent,
        not of whichever session happens to run it.
        """
        ctx = _ctx()
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        connection_ids = [uuid.uuid4(), uuid.uuid4()]
        spec = AgentSpec(name="Support", mcp_server_ids=connection_ids)

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, spec)),
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
            "connection_ids": connection_ids,
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
        spec = AgentSpec(name="Support", mcp_server_ids=[uuid.uuid4()])

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

        assert toolsets.await_args.kwargs["connection_ids"] == spec.mcp_server_ids
        assert build.call_args.kwargs["extra_toolsets"] == ["linear-toolset"]

    @staticmethod
    async def _period_lookups(ctx) -> dict[str, object]:
        """The two spend lookups the runner hands the factory, by argument name."""
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, AgentSpec(name="Support"))),
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

        return {"agent_id": agent.id, **build.call_args.kwargs}

    @pytest.mark.anyio
    async def test_the_spend_the_agent_checks_its_budget_against_is_this_calendar_month(self):
        """The monthly limit is checked mid-run, against a window that matches the invoice.

        The runner hands the agent a callable rather than a number so the guard
        reads the spend at the moment it checks, not at the moment the run began.
        """
        ctx = _ctx()
        built = await self._period_lookups(ctx)

        with patch(
            "app.services.agent_runner.agent_run_repo.sum_cost_since",
            new=AsyncMock(return_value=Decimal("4.50")),
        ) as total:
            spent = await built["org_period_spend"]()

        assert spent == Decimal("4.50")
        assert total.call_args.kwargs["organization_id"] == ctx.organization_id
        assert total.call_args.kwargs["since"] == month_start()
        assert total.call_args.kwargs["agent_id"] is None

    @pytest.mark.anyio
    async def test_the_agents_own_cap_is_metered_on_the_agents_own_spend(self):
        """The defect this pair exists to keep fixed.

        ``AgentSpec.budget.monthly_usd`` used to be checked against the very
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
    async def test_the_cost_breakdown_looks_back_the_number_of_days_it_was_asked_for(self):
        """Unlike the budget, the dashboard window is rolling - "the last 7 days" means that."""
        ctx = _ctx()
        rows = [(uuid.uuid4(), "gpt-4.1", Decimal("3.00"), 12)]

        with patch(
            "app.services.agent_runner.agent_run_repo.cost_breakdown",
            new=AsyncMock(return_value=rows),
        ) as breakdown:
            reported = await AgentRunnerService(_db()).cost_breakdown(ctx, days=7)

        assert reported == rows
        assert breakdown.call_args.kwargs["organization_id"] == ctx.organization_id
        looked_back = datetime.now(UTC) - breakdown.call_args.kwargs["since"]
        assert timedelta(days=7) <= looked_back < timedelta(days=7, seconds=30)


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
                limit_usd=Decimal("1"), spent_usd=Decimal("1.2"), scope="Run"
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
        }

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
            output, _ = await service.resume(_ctx(), run.id)

        assert output == "sent"
        assert finish.call_args.kwargs["status"] == RunStatus.COMPLETED.value

        deferred = built.agent.run.call_args.kwargs["deferred_tool_results"]
        assert deferred.approvals["call-1"].override_args == {"to": "customer@example.com"}
        channel = build.call_args.kwargs["request_approval"]
        assert channel.decided["call-1"] == ApprovalGranted(
            tool_args={"to": "customer@example.com"}
        )

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


class TestWhoTheRunSaysItIs:
    """What the agent is told about the person asking.

    ``AgentDeps.user_id`` reaches every tool, and a tool that writes it into a
    record, a filter or a prompt cannot tell a real id from a plausible-looking
    string. That makes stringifying an absent subject worse than passing none:
    ``"None"`` is the one wrong answer that looks like an answer.
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
                new=AsyncMock(return_value=(agent, AgentSpec(name="Support"))),
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
        """``str(None)`` is `"None"`, and a tool would take it for an id."""
        anonymous = AuthContext.anonymous(uuid.uuid4())

        assert (await self._built_with(anonymous))["user_id"] is None

    @pytest.mark.anyio
    async def test_a_run_with_nobody_behind_it_opens_a_row_with_no_user(self):
        """``agent_runs.user_id`` is nullable, and null is the honest value.

        The run is still accounted for - it has an organization, a cost and a
        surface - it simply has no person to attribute it to.
        """
        service = AgentRunnerService(_db())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, AgentSpec(name="Support"))),
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


def _exposure(*, max_per_run=None, monthly=None, organization_id=None):
    """A binding row, with whatever caps the test is about."""
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        max_per_run_usd=max_per_run,
        monthly_usd=monthly,
    )


class TestARunThatArrivedThroughABinding:
    """Attribution and the ceilings that depend on it.

    An exposure's budget is the only thing between a place an agent was
    published to and somebody's card, and it is not a budget unless it is
    metered against that binding's own runs. Both halves are here: the run has
    to carry which binding admitted it, and the cap has to read that.
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
                new=AsyncMock(return_value=(agent, AgentSpec(name="Support"))),
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

    @pytest.mark.anyio
    async def test_a_binding_with_no_caps_imposes_none(self):
        """Binding an agent to a bot is not the same act as budgeting it."""
        _, built = await self._prepare(_exposure())

        assert built["extra_limits"] == []

    @pytest.mark.anyio
    async def test_both_caps_travel_as_their_own_named_limits(self):
        """Not one composed number: they measure different things.

        The tighter of "this conversation" and "this month" is not a meaningful
        quantity, and collapsing them would leave the refusal unable to say
        which one stopped the run.
        """
        _, built = await self._prepare(_exposure(max_per_run=Decimal("0.5"), monthly=Decimal("25")))

        assert [(limit.scope, limit.limit_usd) for limit in built["extra_limits"]] == [
            ("Exposure run", Decimal("0.5")),
            ("Exposure monthly", Decimal("25")),
        ]

    @pytest.mark.anyio
    async def test_the_per_run_cap_reads_the_ledger_rather_than_the_database(self):
        _, built = await self._prepare(_exposure(max_per_run=Decimal("0.5")))

        assert built["extra_limits"][0].period_spend is None

    @pytest.mark.anyio
    async def test_the_monthly_cap_meters_this_bindings_runs_and_nobody_elses(self):
        """The whole point. Measured against the organization's total it would be
        exhausted by unrelated internal traffic, while this binding's own spend
        stayed invisible in it - which is not a cap on the binding at all.
        """
        organization_id = uuid.uuid4()
        exposure = _exposure(monthly=Decimal("25"), organization_id=organization_id)
        _, built = await self._prepare(exposure)

        with patch(
            "app.services.agent_runner.agent_run_repo.sum_cost_since",
            new=AsyncMock(return_value=Decimal("3")),
        ) as summed:
            assert await built["extra_limits"][0].period_spend() == Decimal("3")

        assert summed.call_args.kwargs["exposure_id"] == exposure.id
        assert summed.call_args.kwargs["organization_id"] == organization_id


class TestAResumedRunKeepsItsCeilings:
    @pytest.mark.anyio
    async def test_a_continuation_is_metered_on_the_binding_the_run_arrived_through(self):
        """Otherwise one approval reopens a budget the run had already spent.

        The argument is not available on the resume path - nobody re-supplies
        the binding when an approver clicks yes - so it is read back off the row,
        which is the only thing that still knows.
        """
        service = AgentRunnerService(_db())
        exposure = _exposure(monthly=Decimal("25"))
        run = _parked_run(exposure_id=exposure.id)

        with patch(
            "app.services.agent_runner.agent_exposure_repo.get",
            new=AsyncMock(return_value=exposure),
        ) as lookup:
            found = await service._exposure_for(run)

        assert found is exposure
        assert lookup.call_args.kwargs["organization_id"] == run.organization_id

    @pytest.mark.anyio
    async def test_a_run_that_arrived_through_no_binding_looks_nothing_up(self):
        service = AgentRunnerService(_db())

        with patch("app.services.agent_runner.agent_exposure_repo.get") as lookup:
            assert await service._exposure_for(_parked_run(exposure_id=None)) is None

        lookup.assert_not_called()

    @pytest.mark.anyio
    async def test_a_binding_deleted_while_the_run_waited_stops_capping_it(self):
        """The honest outcome: the ceiling belonged to a place that is gone.

        The alternative - refusing to continue - would strand a run somebody had
        already approved, over a limit nobody can raise any more.
        """
        service = AgentRunnerService(_db())
        run = _parked_run(exposure_id=uuid.uuid4())

        with patch(
            "app.services.agent_runner.agent_exposure_repo.get", new=AsyncMock(return_value=None)
        ):
            assert await service._exposure_for(run) is None

    @pytest.mark.anyio
    async def test_caps_are_dropped_when_the_row_carries_no_binding(self):
        """Guards the pairing itself: a cap metered on ``None`` sums every run
        that ever arrived through no binding at all, which is most of them."""
        service = AgentRunnerService(_db())

        limits = service._exposure_limits(_exposure(monthly=Decimal("25")), run_exposure_id=None)

        assert limits == []


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
                new=AsyncMock(return_value=(agent, spec)),
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
