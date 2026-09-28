"""What a dispatch tick does to a run, against a real Postgres.

Each test drives `claim` / `begin_attempt` / `call_handler` / `settle` the way
`workflow_dispatch_node_flow` sequences them, one committed transaction per
phase, with a node definition registered for the test so the handler can do
what no shipped node does yet: spend money, raise, wait.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import drain, start_deferred
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.approvals import ApprovalService
from app.services.workflow_execution import WorkflowExecutionService, budget, context, dispatcher
from app.services.workflow_execution.approval_wake import wake_after_approval_decision
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.worker.tasks.workflow_tasks import workflow_dispatch_node_flow
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

Handler = Callable[[object, object], Awaitable[NodeResult]]


class _Config(BaseModel):
    message: str = ""


class _Output(BaseModel):
    echoed: str


@dataclass
class Seeded:
    run: WorkflowRun
    entry: NodeRun
    graph: WorkflowGraph
    principal: User
    org: Organization
    factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def node_kind() -> Iterator[Callable[..., str]]:
    """Registers a node definition whose handler the test supplies, and removes
    every one it registered afterwards."""
    registered: list[str] = []

    def _register(handler: Handler, *, retry_guarantee: str = "idempotent") -> str:
        node_id = f"test.dispatch-{uuid.uuid4().hex[:8]}"
        register(
            NodeDefinition(
                id=node_id,
                version=1,
                name="Test node",
                category="test",
                description="Registered only for dispatch integration tests.",
                kind="action",
                config_schema=_Config,
                input_schema=_Config,
                output_schema=_Output,
                ports=(
                    Port(id="in", label="In", kind="input", schema=_Config),
                    Port(id="out", label="Out", kind="output", schema=_Output),
                ),
                effect_kind="pure",
                retry_guarantee=retry_guarantee,
                handler=handler,
            )
        )
        registered.append(node_id)
        return node_id

    yield _register
    for node_id in registered:
        REGISTRY.pop(node_id, None)


def _chain(node_id: str, length: int) -> WorkflowGraph:
    nodes = tuple(
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=node_id,
            definition_version=1,
            config={"message": "hi"},
            layout=NodePosition(x=index * 100, y=0),
        )
        for index in range(length)
    )
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        for source, target in pairwise(nodes)
    )
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=nodes, edges=edges)


async def _seed(
    engine: AsyncEngine,
    graph: WorkflowGraph,
    *,
    budget_limit: Decimal | None = None,
    role: str = "owner",
) -> Seeded:
    """A `running` test-mode run of `graph`, started by an active member holding
    `role`, with the entry node's outbox row ready to claim - what
    `WorkflowExecutionService.start` leaves behind."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        principal = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(principal)
        await db.flush()
        org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            created_by_user_id=principal.id,
        )
        db.add(org)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=principal.id, role=role
            )
        )
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=principal.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Chain",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=graph.model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        run = await workflow_run_repo.create_run(
            db,
            organization_id=org.id,
            workflow_id=workflow.id,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
            mode=WorkflowRunMode.TEST.value,
            triggered_by="api",
            execution_principal_user_id=principal.id,
            budget_limit=budget_limit,
            deadline_at=None,
            root_run_id=None,
            causation_run_id=None,
            visited_trigger_ids=[],
            depth=0,
            started_at=datetime.now(UTC),
        )
        entry = await workflow_run_repo.create_node_run(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=entry.id,
        )
        run = await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
        )
        await db.commit()
    return Seeded(run=run, entry=entry, graph=graph, principal=principal, org=org, factory=factory)


async def _tick(seeded: Seeded, node_run_id: uuid.UUID) -> dispatcher.BegunAttempt | None:
    """One `workflow_dispatch_node_flow` tick for `node_run_id`, phase by phase."""
    factory = seeded.factory
    async with factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    if begun is None:
        return None
    outcome = await dispatcher.call_handler(begun)
    async with factory() as db:
        await dispatcher.settle(db, begun=begun, outcome=outcome)
        await db.commit()
    return begun


async def _run_row(seeded: Seeded) -> WorkflowRun:
    async with seeded.factory() as db:
        return (
            await db.execute(select(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        ).scalar_one()


async def _node_runs(seeded: Seeded) -> list[NodeRun]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(NodeRun)
                    .where(NodeRun.workflow_run_id == seeded.run.id)
                    .order_by(NodeRun.created_at)
                )
            ).scalars()
        )


async def _outbox_rows(seeded: Seeded) -> list[DispatchOutbox]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == seeded.run.id)
                )
            ).scalars()
        )


async def _attempt_costs(seeded: Seeded) -> list[Decimal]:
    async with seeded.factory() as db:
        rows = (
            await db.execute(
                select(NodeAttempt)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.workflow_run_id == seeded.run.id)
                .order_by(NodeAttempt.created_at)
            )
        ).scalars()
        return [row.cost for row in rows]


async def _spend(amount: str) -> NodeResult:
    context.report_cost(Decimal(amount))
    return Completed[_Output](output=_Output(echoed="spent"))


class TestCostAndBudget:
    async def test_what_a_node_reports_spending_lands_on_its_attempt_and_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            return await _spend("0.015")

        seeded = await _seed(engine, _chain(node_kind(handler), 1))

        await _tick(seeded, seeded.entry.id)

        run = await _run_row(seeded)
        assert run.spent_cost == Decimal("0.015")
        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        assert await _attempt_costs(seeded) == [Decimal("0.015")]

    @pytest.mark.security
    async def test_a_spent_budget_refuses_the_next_node_and_ends_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """The first node's spend reaches the cap, so the second is refused
        before its handler runs - and the refusal ends the run in every column
        a reader checks, rather than parking it with a pending node."""
        calls: list[str] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            calls.append("called")
            return await _spend("0.02")

        seeded = await _seed(engine, _chain(node_kind(handler), 2), budget_limit=Decimal("0.02"))

        await _tick(seeded, seeded.entry.id)
        second = (await _node_runs(seeded))[1]
        assert await _tick(seeded, second.id) is None

        assert calls == ["called"]
        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.BUDGET_EXCEEDED.value
        assert run.ended_at is not None
        assert run.error is not None and run.error["code"] == "BUDGET_EXCEEDED"
        assert run.spent_cost == Decimal("0.02")
        assert [node.status for node in await _node_runs(seeded)] == [
            NodeRunStatus.SUCCEEDED.value,
            NodeRunStatus.CANCELLED.value,
        ]
        assert {row.status for row in await _outbox_rows(seeded)} == {
            DispatchOutboxStatus.DONE.value
        }


async def _echo(_config: object, _input: object) -> NodeResult:
    return Completed[_Output](output=_Output(echoed="hi"))


async def _expire_claims(seeded: Seeded) -> None:
    async with seeded.factory() as db:
        await db.execute(
            sql_update(DispatchOutbox)
            .where(DispatchOutbox.workflow_run_id == seeded.run.id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


class TestDeterministicDispatchFailures:
    async def test_a_node_whose_definition_left_the_registry_fails_the_run_once(
        self, engine: AsyncEngine, node_kind
    ):
        """Removed in a deploy after the graph was published: every attempt
        would fail identically, so the run fails with its own code instead of
        its claim rolling back and being resubmitted on every reconcile tick."""
        node_id = node_kind(_echo)
        seeded = await _seed(engine, _chain(node_id, 1))
        REGISTRY.pop(node_id)

        assert await _tick(seeded, seeded.entry.id) is None

        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "NODE_DEFINITION_MISSING"
        assert [node.status for node in await _node_runs(seeded)] == [NodeRunStatus.FAILED.value]
        await _expire_claims(seeded)
        async with seeded.factory() as db:
            assert await WorkflowReconcilerService(db).stale_claims() == []

    async def test_a_definition_registered_without_a_handler_fails_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        node_id = node_kind(_echo)
        REGISTRY[node_id][1] = replace(REGISTRY[node_id][1], handler=None)
        seeded = await _seed(engine, _chain(node_id, 1))

        assert await _tick(seeded, seeded.entry.id) is None

        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "NODE_HANDLER_MISSING"

    async def test_a_node_run_naming_a_node_absent_from_the_graph_fails_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        node_id = node_kind(_echo)
        seeded = await _seed(engine, _chain(node_id, 1))
        async with seeded.factory() as db:
            await db.execute(
                sql_update(NodeRun)
                .where(NodeRun.id == seeded.entry.id)
                .values(node_instance_id=uuid.uuid4())
            )
            await db.commit()

        assert await _tick(seeded, seeded.entry.id) is None

        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "GRAPH_UNRESOLVABLE"


class TestHandlerErrorsAndInterruptions:
    async def test_a_raising_handler_with_no_retry_guarantee_fails_the_run_once(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            raise RuntimeError("upstream said no")

        seeded = await _seed(engine, _chain(node_kind(handler, retry_guarantee="none"), 1))

        assert await _tick(seeded, seeded.entry.id) is not None

        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "HANDLER_ERROR"
        assert "upstream said no" not in str(run.error)
        async with seeded.factory() as db:
            attempts = (
                await db.execute(
                    select(NodeAttempt).where(NodeAttempt.node_run_id == seeded.entry.id)
                )
            ).scalars()
            assert [attempt.status for attempt in attempts] == [NodeAttemptStatus.FAILED.value]

    async def test_an_idempotent_node_interrupted_at_the_retry_ceiling_ends_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """A handler that kills its worker on every attempt leaves an orphan
        each time; past the ceiling the run ends rather than being requeued on
        every reconcile tick for ever."""
        seeded = await _seed(engine, _chain(node_kind(_echo), 1))
        async with seeded.factory() as db:
            await dispatcher.claim(db, node_run_id=seeded.entry.id, lease_seconds=0)
            await db.commit()
        async with seeded.factory() as db:
            # The earlier attempts, each already interrupted and resolved.
            for attempt_no in range(1, settings.WORKFLOW_RETRY_CEILING):
                earlier = await workflow_run_repo.create_attempt(
                    db,
                    organization_id=seeded.org.id,
                    node_run_id=seeded.entry.id,
                    attempt_no=attempt_no,
                    idempotency_key="k",
                    retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
                    started_at=datetime.now(UTC),
                )
                await workflow_run_repo.settle_attempt(
                    db,
                    attempt=earlier,
                    status=NodeAttemptStatus.UNCERTAIN.value,
                    result=None,
                    cost=Decimal(0),
                    cost_is_partial=False,
                    ended_at=datetime.now(UTC),
                )
            await workflow_run_repo.create_attempt(
                db,
                organization_id=seeded.org.id,
                node_run_id=seeded.entry.id,
                attempt_no=settings.WORKFLOW_RETRY_CEILING,
                idempotency_key="k",
                retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
                started_at=datetime.now(UTC),
            )
            await db.commit()

        async with seeded.factory() as db:
            assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
            await db.commit()

        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "ATTEMPTS_INTERRUPTED"
        assert DispatchOutboxStatus.PENDING.value not in {
            row.status for row in await _outbox_rows(seeded)
        }


async def _set_member_role(seeded: Seeded, role: str | None) -> None:
    """Change the principal's membership role, or remove the membership."""
    async with seeded.factory() as db:
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == seeded.org.id,
                    OrganizationMember.user_id == seeded.principal.id,
                )
            )
        ).scalar_one()
        if role is None:
            await db.delete(member)
        else:
            member.role = role
        await db.commit()


async def _set_principal(seeded: Seeded, **values: object) -> None:
    async with seeded.factory() as db:
        await db.execute(sql_update(User).where(User.id == seeded.principal.id).values(**values))
        await db.commit()


@pytest.mark.security
class TestPrincipalRecheckedAtEveryDispatch:
    """The run's first node dispatches as its principal; the second is refused
    once that principal lost what starting the run required - removed from
    the organization, deactivated, or no longer allowed to run it."""

    @pytest.fixture
    def calls(self) -> list[str]:
        return []

    @pytest.fixture
    def recording(self, node_kind, calls: list[str]) -> str:
        async def handler(_config: object, _input: object) -> NodeResult:
            auth = context.current().auth
            calls.append(f"{auth.role}|{auth.is_app_admin}")
            return Completed[_Output](output=_Output(echoed="hi"))

        return node_kind(handler)

    async def _second_dispatch_after(
        self, engine: AsyncEngine, node_id: str, revoke: Callable[[Seeded], Awaitable[None]]
    ) -> Seeded:
        seeded = await _seed(engine, _chain(node_id, 2))
        await _tick(seeded, seeded.entry.id)
        await revoke(seeded)
        second = (await _node_runs(seeded))[1]
        assert await _tick(seeded, second.id) is None
        return seeded

    @pytest.mark.parametrize(
        "revoke",
        [
            pytest.param(lambda seeded: _set_member_role(seeded, None), id="removed-member"),
            pytest.param(lambda seeded: _set_member_role(seeded, "viewer"), id="role-cannot-run"),
            pytest.param(lambda seeded: _set_principal(seeded, is_active=False), id="deactivated"),
        ],
    )
    async def test_a_revoked_principal_stops_the_next_node(
        self, engine: AsyncEngine, recording: str, calls: list[str], revoke
    ):
        seeded = await self._second_dispatch_after(engine, recording, revoke)

        assert calls == ["owner|False"]
        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "PRINCIPAL_REVOKED"
        assert [node.status for node in await _node_runs(seeded)] == [
            NodeRunStatus.SUCCEEDED.value,
            NodeRunStatus.FAILED.value,
        ]

    async def test_a_deactivated_app_admin_loses_that_authority_too(
        self, engine: AsyncEngine, recording: str, calls: list[str]
    ):
        async def revoke(seeded: Seeded) -> None:
            await _set_member_role(seeded, None)
            await _set_principal(seeded, is_app_admin=True, is_active=False)

        seeded = await self._second_dispatch_after(engine, recording, revoke)

        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "PRINCIPAL_REVOKED"

    async def test_a_deleted_principal_acts_as_nobody_and_is_refused(
        self, engine: AsyncEngine, recording: str, calls: list[str]
    ):
        async def revoke(seeded: Seeded) -> None:
            async with seeded.factory() as db:
                await db.execute(
                    sql_update(WorkflowRun)
                    .where(WorkflowRun.id == seeded.run.id)
                    .values(execution_principal_user_id=None)
                )
                await db.commit()

        seeded = await self._second_dispatch_after(engine, recording, revoke)

        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "PRINCIPAL_REVOKED"

    async def test_an_app_admin_removed_from_the_organization_stops_the_next_node(
        self, engine: AsyncEngine, recording: str, calls: list[str]
    ):
        """Every request refuses an organization the caller is not a member of,
        app admins included; the dispatcher used to let a removed app admin's
        runs carry on with full authority."""

        async def revoke(seeded: Seeded) -> None:
            await _set_principal(seeded, is_app_admin=True)
            await _set_member_role(seeded, None)

        seeded = await self._second_dispatch_after(engine, recording, revoke)

        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "PRINCIPAL_REVOKED"


class TestLeaseKeptAliveThroughTheFlow:
    """`workflow_dispatch_node_flow` itself, run in-process: the handler runs
    between the flow's own transactions while the reconciler sweeps."""

    @pytest.fixture(autouse=True)
    def _short_lease(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKFLOW_DISPATCH_LEASE_SECONDS", 0.6)
        with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
            yield

    async def test_a_handler_that_outlives_the_lease_settles_completed_exactly_once(
        self, engine: AsyncEngine, node_kind
    ):
        """Without renewal the lease ran out mid-call: the sweep marked the
        attempt `uncertain` and requeued the node, and the real result was
        discarded as stale when it finally arrived."""
        seeded_holder: list[Seeded] = []
        sweeps: list[tuple[int, int]] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            for _ in range(8):
                await asyncio.sleep(0.2)
                async with seeded_holder[0].factory() as db:
                    service = WorkflowReconcilerService(db)
                    sweeps.append(
                        (
                            await service.resolve_orphaned_attempts(),
                            len(await service.stale_claims()),
                        )
                    )
                    await db.commit()
            return Completed[_Output](output=_Output(echoed="slow"))

        seeded = await _seed(engine, _chain(node_kind(handler), 1))
        seeded_holder.append(seeded)

        status = await workflow_dispatch_node_flow.fn(str(seeded.run.id), str(seeded.entry.id))

        assert status == "settled"
        assert sweeps == [(0, 0)] * 8
        async with seeded.factory() as db:
            attempts = (
                await db.execute(
                    select(NodeAttempt).where(NodeAttempt.node_run_id == seeded.entry.id)
                )
            ).scalars()
            assert [attempt.status for attempt in attempts] == [NodeAttemptStatus.COMPLETED.value]
        assert (await _run_row(seeded)).status == WorkflowRunStatus.SUCCEEDED.value

    async def test_a_slow_begin_is_covered_by_the_lease_too(
        self, engine: AsyncEngine, node_kind, monkeypatch
    ):
        """Renewal used to start with the handler, a third of a lease after it:
        a `begin_attempt` slower than two thirds of a lease let the sweep
        resolve a healthy attempt `uncertain`."""
        # Past two thirds of the lease, where the first renewal used to land.
        monkeypatch.setattr(settings, "WORKFLOW_DISPATCH_LEASE_SECONDS", 1.5)
        real_principal = dispatcher._principal_context

        async def slow_principal(db: AsyncSession, run: WorkflowRun) -> AuthContext:
            await asyncio.sleep(1.2)
            return await real_principal(db, run)

        monkeypatch.setattr(dispatcher, "_principal_context", slow_principal)
        sweeping = asyncio.Event()
        resolved: list[int] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            await asyncio.sleep(0.3)
            return Completed[_Output](output=_Output(echoed="ok"))

        seeded = await _seed(engine, _chain(node_kind(handler, retry_guarantee="none"), 1))

        async def sweep() -> None:
            while not sweeping.is_set():
                resolved.append(await _reconcile_orphans(seeded))
                await asyncio.sleep(0.05)

        sweeper = asyncio.ensure_future(sweep())
        status = await workflow_dispatch_node_flow.fn(str(seeded.run.id), str(seeded.entry.id))
        sweeping.set()
        await sweeper

        assert status == "settled"
        assert sum(resolved) == 0
        assert await _attempt_statuses(seeded, seeded.entry.id) == [
            NodeAttemptStatus.COMPLETED.value
        ]
        assert (await _run_row(seeded)).status == WorkflowRunStatus.SUCCEEDED.value

    async def test_a_handler_is_told_when_its_claim_is_lost(self, engine: AsyncEngine, node_kind):
        seeded_holder: list[Seeded] = []
        observed: list[bool] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            async with seeded_holder[0].factory() as db:
                await db.execute(
                    sql_update(DispatchOutbox)
                    .where(DispatchOutbox.node_run_id == seeded_holder[0].entry.id)
                    .values(status=DispatchOutboxStatus.CANCELLED.value)
                )
                await db.commit()
            for _ in range(20):
                if context.current().claim.lost:
                    break
                await asyncio.sleep(0.1)
            observed.append(context.current().claim.lost)
            return Completed[_Output](output=_Output(echoed="unwanted"))

        seeded = await _seed(engine, _chain(node_kind(handler), 1))
        seeded_holder.append(seeded)

        await workflow_dispatch_node_flow.fn(str(seeded.run.id), str(seeded.entry.id))

        assert observed == [True]
        # And what it returned anyway was not accepted.
        assert [node.status for node in await _node_runs(seeded)] == [NodeRunStatus.RUNNING.value]


async def test_the_settling_flow_submits_the_next_node_itself_after_its_commit(
    engine: AsyncEngine, node_kind
):
    """The flow submits the node its settle made ready only once that settle
    has committed: the submitted flow claims the row by id from a session of
    its own, so a row still uncommitted at submission is one it cannot find.
    The row is stamped submitted, so the poll does not submit it again."""
    seeded = await _seed(engine, _chain(node_kind(_echo), 2))
    seen_at_submission: list[tuple[str, str | None]] = []

    async def submit(*, parameters: dict[str, str], **_kwargs: object) -> None:
        async with seeded.factory() as reader:
            row = (
                await reader.execute(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == uuid.UUID(parameters["node_run_id"])
                    )
                )
            ).scalar_one_or_none()
        seen_at_submission.append(
            (parameters["node_run_id"], row.status if row is not None else None)
        )

    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock(side_effect=submit)):
        status = await workflow_dispatch_node_flow.fn(str(seeded.run.id), str(seeded.entry.id))

    assert status == "settled"
    second = (await _node_runs(seeded))[1]
    assert seen_at_submission == [(str(second.id), DispatchOutboxStatus.PENDING.value)]
    pending = [
        row
        for row in await _outbox_rows(seeded)
        if row.status == DispatchOutboxStatus.PENDING.value
    ]
    assert len(pending) == 1 and pending[0].submitted_at is not None


async def _agent_run_awaiting_approval(seeded: Seeded, *, raised_at: datetime) -> AgentRun:
    async with seeded.factory() as db:
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=seeded.org.id,
            slug="clerk",
            name="Clerk",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        agent_run = AgentRun(
            id=uuid.uuid4(),
            organization_id=seeded.org.id,
            agent_id=agent.id,
            surface="api",
            status=RunStatus.AWAITING_APPROVAL.value,
            started_at=raised_at,
        )
        db.add(agent_run)
        await db.flush()
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=seeded.org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.PENDING.value,
                created_at=raised_at,
            )
        )
        await db.commit()
    return agent_run


class TestWaits:
    async def test_an_expired_approval_wakes_its_node_and_the_node_fails(
        self, engine: AsyncEngine, node_kind
    ):
        """Expiry cancels the agent run without anyone deciding. The node
        parked on it must wake - through the same wake a decision queues - so
        its handler sees the run ended and fails the node, rather than the
        workflow waiting for ever with cancel as the only way out."""
        parked_on: list[uuid.UUID] = []
        seen: list[str] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            resumed = context.current().resumed_agent_run_id
            if resumed is None:
                context.report_waiting_agent_run(parked_on[0])
                return Waiting(reason="approval", resume_token="t")
            async with seeded_holder[0].factory() as db:
                status = (
                    await db.execute(select(AgentRun.status).where(AgentRun.id == resumed))
                ).scalar_one()
            seen.append(status)
            return Failed(error=WorkflowError(code="APPROVAL_EXPIRED", message="Nobody decided"))

        seeded_holder: list[Seeded] = []
        seeded = await _seed(engine, _chain(node_kind(handler, retry_guarantee="none"), 1))
        seeded_holder.append(seeded)
        long_ago = datetime.now(UTC) - timedelta(hours=settings.APPROVAL_EXPIRY_HOURS + 1)
        parked_on.append((await _agent_run_awaiting_approval(seeded, raised_at=long_ago)).id)

        await _tick(seeded, seeded.entry.id)
        assert (await _run_row(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value

        async with seeded.factory() as db:
            assert await ApprovalService(db).expire_stale() == 1
            await db.commit()
            start_deferred(db)
        await drain()

        await _tick(seeded, seeded.entry.id)

        assert seen == [RunStatus.CANCELLED.value]
        assert [node.status for node in await _node_runs(seeded)] == [NodeRunStatus.FAILED.value]
        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "APPROVAL_EXPIRED"

    async def test_a_retry_backoff_wait_is_dispatched_again_once_the_backoff_passes(
        self, engine: AsyncEngine, node_kind
    ):
        attempts: list[int] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            attempts.append(context.current().attempt_no)
            if len(attempts) == 1:
                return Waiting(reason="retry_backoff", resume_token="t")
            return Completed[_Output](output=_Output(echoed="later"))

        seeded = await _seed(engine, _chain(node_kind(handler), 1))

        await _tick(seeded, seeded.entry.id)

        assert (await _run_row(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value
        [row] = [
            row
            for row in await _outbox_rows(seeded)
            if row.status == DispatchOutboxStatus.PENDING.value
        ]
        assert row.available_at > datetime.now(UTC)
        async with seeded.factory() as db:
            await db.execute(
                sql_update(DispatchOutbox)
                .where(DispatchOutbox.id == row.id)
                .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()

        await _tick(seeded, seeded.entry.id)

        assert attempts == [1, 2]
        assert (await _run_row(seeded)).status == WorkflowRunStatus.SUCCEEDED.value

    async def test_a_node_that_leaves_its_wait_forgets_the_agent_run_it_waited_on(
        self, engine: AsyncEngine, node_kind
    ):
        """Kept after the wait, the link handed a later retry a stale agent run
        to resume, and let two node runs match one agent run in the wake."""
        parked_on: list[uuid.UUID] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            if context.current().resumed_agent_run_id is None:
                context.report_waiting_agent_run(parked_on[0])
                return Waiting(reason="approval", resume_token="t")
            return Completed[_Output](output=_Output(echoed="resumed"))

        seeded = await _seed(engine, _chain(node_kind(handler), 1))
        parked_on.append(
            (await _agent_run_awaiting_approval(seeded, raised_at=datetime.now(UTC))).id
        )
        await _tick(seeded, seeded.entry.id)
        async with seeded.factory() as db:
            await workflow_run_repo.create_outbox(
                db,
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                node_run_id=seeded.entry.id,
            )
            await db.commit()

        await _tick(seeded, seeded.entry.id)

        [node] = await _node_runs(seeded)
        assert node.status == NodeRunStatus.SUCCEEDED.value
        assert node.waiting_agent_run_id is None
        async with seeded.factory() as db:
            assert (
                await workflow_run_repo.find_node_run_waiting_on_agent_run(
                    db, parked_on[0], organization_id=seeded.org.id
                )
            ) is None


async def _attempt_statuses(seeded: Seeded, node_run_id: uuid.UUID) -> list[str]:
    async with seeded.factory() as db:
        rows = (
            await db.execute(
                select(NodeAttempt)
                .where(NodeAttempt.node_run_id == node_run_id)
                .order_by(NodeAttempt.attempt_no)
            )
        ).scalars()
        return [row.status for row in rows]


async def _decide_all(seeded: Seeded, agent_run_id: uuid.UUID) -> None:
    async with seeded.factory() as db:
        await db.execute(
            sql_update(ToolApproval)
            .where(ToolApproval.run_id == agent_run_id)
            .values(status=ApprovalStatus.APPROVED.value)
        )
        await db.commit()


def _parks_first_then_echoes(entry: list[uuid.UUID], parked_on: list[uuid.UUID]) -> Handler:
    """The entry node parks on an approval once; every other call completes."""

    async def handler(_config: object, _input: object) -> NodeResult:
        current = context.current()
        if current.node_instance_id == entry[0] and current.resumed_agent_run_id is None:
            context.report_waiting_agent_run(parked_on[0])
            return Waiting(reason="approval", resume_token="t")
        return Completed[_Output](output=_Output(echoed="ok"))

    return handler


async def _claim_and_begin(seeded: Seeded, node_run_id: uuid.UUID) -> dispatcher.BegunAttempt:
    """Phases 1 and 2 only: the worker then dies before running the handler."""
    async with seeded.factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with seeded.factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    assert begun is not None
    return begun


async def _age_closed_rows(seeded: Seeded) -> None:
    """Move every closed outbox row's last change back past a lease's grace."""
    async with seeded.factory() as db:
        await db.execute(
            sql_update(DispatchOutbox)
            .where(
                DispatchOutbox.workflow_run_id == seeded.run.id,
                DispatchOutbox.status.in_(
                    [DispatchOutboxStatus.DONE.value, DispatchOutboxStatus.CANCELLED.value]
                ),
            )
            .values(updated_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()


async def _reconcile_orphans(seeded: Seeded) -> int:
    async with seeded.factory() as db:
        resolved = await WorkflowReconcilerService(db).resolve_orphaned_attempts()
        await db.commit()
    return resolved


class TestStrayOutboxRows:
    async def test_a_backstop_sweep_overtaken_by_the_direct_wake_never_strands_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """The sweep scans the parked node, the direct wake dispatches it to
        success meanwhile, and only then does the sweep take its locks. It used
        to insert a row for the succeeded node anyway, which kept the run
        `running` for ever after the last node settled."""
        entry: list[uuid.UUID] = []
        parked_on: list[uuid.UUID] = []
        graph = _chain(node_kind(_parks_first_then_echoes(entry, parked_on)), 2)
        entry.append(graph.entry_node_id)
        seeded = await _seed(engine, graph)
        parked_on.append(
            (await _agent_run_awaiting_approval(seeded, raised_at=datetime.now(UTC))).id
        )
        await _tick(seeded, seeded.entry.id)
        await _decide_all(seeded, parked_on[0])

        scanned, resume = asyncio.Event(), asyncio.Event()
        real_scan = workflow_run_repo.list_stale_approval_waits

        async def scan_then_pause(db: AsyncSession, *, limit: int = 100) -> list[NodeRun]:
            rows = await real_scan(db, limit=limit)
            scanned.set()
            await resume.wait()
            return rows

        async def sweep() -> int:
            async with seeded.factory() as db:
                with patch.object(workflow_run_repo, "list_stale_approval_waits", scan_then_pause):
                    woken = await WorkflowReconcilerService(db).wake_stale_approval_decisions()
                await db.commit()
            return woken

        sweeping = asyncio.ensure_future(sweep())
        await scanned.wait()
        await wake_after_approval_decision(parked_on[0], organization_id=seeded.org.id)
        await _tick(seeded, seeded.entry.id)
        resume.set()

        assert await sweeping == 0
        second = (await _node_runs(seeded))[1]
        await _tick(seeded, second.id)
        assert (await _run_row(seeded)).status == WorkflowRunStatus.SUCCEEDED.value

    async def test_closing_a_stray_row_after_the_last_node_settled_ends_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """Whatever inserts a stray row, the run cannot stay `running` once
        every node has succeeded: closing the stray row re-checks completion."""
        seeded = await _seed(engine, _chain(node_kind(_echo), 2))
        await _tick(seeded, seeded.entry.id)
        async with seeded.factory() as db:
            await workflow_run_repo.create_outbox(
                db,
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                node_run_id=seeded.entry.id,
            )
            await db.commit()
        second = (await _node_runs(seeded))[1]
        await _tick(seeded, second.id)

        assert await _tick(seeded, seeded.entry.id) is None

        assert (await _run_row(seeded)).status == WorkflowRunStatus.SUCCEEDED.value
        assert {row.status for row in await _outbox_rows(seeded)} == {
            DispatchOutboxStatus.DONE.value
        }

    async def test_the_live_row_is_the_one_a_claim_locks_whatever_its_created_at(
        self, engine: AsyncEngine, node_kind
    ):
        """`created_at` is the inserting transaction's start, so a row a long
        sweep inserted can predate a row closed meanwhile. Locking the newest
        by `created_at` locked the closed row, answered "lost claim" and left
        the live row claimed, resubmitted every lease for ever."""
        seeded = await _seed(engine, _chain(node_kind(_echo), 1))
        await _tick(seeded, seeded.entry.id)
        [done] = await _outbox_rows(seeded)
        async with seeded.factory() as db:
            stray = await workflow_run_repo.create_outbox(
                db,
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                node_run_id=seeded.entry.id,
            )
            await db.execute(
                sql_update(DispatchOutbox)
                .where(DispatchOutbox.id == stray.id)
                .values(created_at=done.created_at - timedelta(seconds=1))
            )
            await db.commit()

        assert await _tick(seeded, seeded.entry.id) is None

        statuses = {row.id: row.status for row in await _outbox_rows(seeded)}
        assert statuses[stray.id] == DispatchOutboxStatus.DONE.value
        await _expire_claims(seeded)
        async with seeded.factory() as db:
            assert await WorkflowReconcilerService(db).stale_claims() == []


class TestAttemptsBehindAClosedRow:
    """An attempt whose outbox row something else closed - a cancel while its
    worker was dead, a reclaim that failed the run - used to stay `in_flight`
    for ever: the sweep only looked behind rows still `claimed`."""

    async def test_cancelling_while_the_worker_is_dead_settles_the_attempt_after_a_grace(
        self, engine: AsyncEngine, node_kind
    ):
        seeded = await _seed(engine, _chain(node_kind(_echo), 1))
        await _claim_and_begin(seeded, seeded.entry.id)
        owner = AuthContext(
            user_id=seeded.principal.id, organization_id=seeded.org.id, role="owner"
        )
        async with seeded.factory() as db:
            await WorkflowExecutionService(db).cancel(owner, seeded.run.id)
            await db.commit()

        # Within the grace a worker still running the handler may settle it.
        assert await _reconcile_orphans(seeded) == 0
        await _age_closed_rows(seeded)
        assert await _reconcile_orphans(seeded) == 1

        assert await _attempt_statuses(seeded, seeded.entry.id) == [
            NodeAttemptStatus.UNCERTAIN.value
        ]
        [node] = await _node_runs(seeded)
        assert node.status == NodeRunStatus.CANCELLED.value
        assert {row.status for row in await _outbox_rows(seeded)} == {
            DispatchOutboxStatus.CANCELLED.value
        }

    async def test_a_reclaim_past_the_deadline_leaves_nothing_in_flight(
        self, engine: AsyncEngine, node_kind
    ):
        seeded = await _seed(engine, _chain(node_kind(_echo), 1))
        await _claim_and_begin(seeded, seeded.entry.id)
        async with seeded.factory() as db:
            await db.execute(
                sql_update(WorkflowRun)
                .where(WorkflowRun.id == seeded.run.id)
                .values(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()
        await _expire_claims(seeded)
        assert await _tick(seeded, seeded.entry.id) is None
        await _age_closed_rows(seeded)

        assert await _reconcile_orphans(seeded) == 1

        assert await _attempt_statuses(seeded, seeded.entry.id) == [
            NodeAttemptStatus.UNCERTAIN.value
        ]
        [node] = await _node_runs(seeded)
        # Failed for the deadline, and not relabelled by the late resolution.
        assert node.status == NodeRunStatus.FAILED.value
        run = await _run_row(seeded)
        assert run.error is not None and run.error["code"] == "DEADLINE_EXCEEDED"

    async def test_a_woken_node_failed_before_dispatch_forgets_its_wait_and_says_so(
        self, engine: AsyncEngine, node_kind
    ):
        """A node woken from an approval wait and failed for the deadline kept
        its link to the agent run and emitted no node event."""
        entry: list[uuid.UUID] = []
        parked_on: list[uuid.UUID] = []
        graph = _chain(node_kind(_parks_first_then_echoes(entry, parked_on)), 1)
        entry.append(graph.entry_node_id)
        seeded = await _seed(engine, graph)
        parked_on.append(
            (await _agent_run_awaiting_approval(seeded, raised_at=datetime.now(UTC))).id
        )
        await _tick(seeded, seeded.entry.id)
        async with seeded.factory() as db:
            await db.execute(
                sql_update(WorkflowRun)
                .where(WorkflowRun.id == seeded.run.id)
                .values(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()
        await _decide_all(seeded, parked_on[0])
        await wake_after_approval_decision(parked_on[0], organization_id=seeded.org.id)

        assert await _tick(seeded, seeded.entry.id) is None

        [node] = await _node_runs(seeded)
        assert node.status == NodeRunStatus.FAILED.value
        assert (node.waiting_reason, node.waiting_agent_run_id) == (None, None)
        async with seeded.factory() as db:
            kinds = [
                event.kind
                for event in await workflow_run_repo.list_events_since(
                    db, workflow_run_id=seeded.run.id, organization_id=seeded.org.id, after_seq=None
                )
            ]
        assert kinds[-2:] == ["node_failed", "run_failed"]


@pytest.mark.security
class TestCostTheColumnsCannotHold:
    async def test_a_cost_past_the_column_is_capped_and_still_stops_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """Booked as reported, the amount overflowed `NUMERIC(12, 6)` and rolled
        the settle back: nothing was recorded, the attempt was redispatched and
        the budget check never saw the spend."""
        calls: list[int] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            calls.append(context.current().attempt_no)
            return await _spend("2000000")

        seeded = await _seed(engine, _chain(node_kind(handler), 2), budget_limit=Decimal("1"))

        await _tick(seeded, seeded.entry.id)
        second = (await _node_runs(seeded))[1]
        assert await _tick(seeded, second.id) is None

        assert calls == [1]
        run = await _run_row(seeded)
        assert (run.spent_cost, run.cost_is_partial) == (budget.MAX_COST, True)
        assert run.status == WorkflowRunStatus.BUDGET_EXCEEDED.value
        assert await _attempt_costs(seeded) == [budget.MAX_COST]

    async def test_a_cost_that_is_not_a_number_fails_the_node_instead_of_the_settle(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            return await _spend("Infinity")

        seeded = await _seed(engine, _chain(node_kind(handler, retry_guarantee="none"), 1))

        assert await _tick(seeded, seeded.entry.id) is not None

        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "HANDLER_ERROR"
        assert await _attempt_statuses(seeded, seeded.entry.id) == [NodeAttemptStatus.FAILED.value]


class TestALateResultsCost:
    """A result that arrives after its attempt was reclaimed is discarded, but
    what the call spent is booked onto the attempt as well as the run, so the
    attempts still add up to the run's total."""

    async def test_a_stale_settle_books_its_cost_onto_the_resolved_attempt(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            return await _spend("1.50")

        seeded = await _seed(engine, _chain(node_kind(handler, retry_guarantee="none"), 1))
        begun = await _claim_and_begin(seeded, seeded.entry.id)
        await _expire_claims(seeded)
        assert await _reconcile_orphans(seeded) == 1
        outcome = await dispatcher.call_handler(begun)

        async with seeded.factory() as db:
            await dispatcher.settle(db, begun=begun, outcome=outcome)
            await db.commit()

        assert (await _run_row(seeded)).spent_cost == Decimal("1.50")
        assert await _attempt_costs(seeded) == [Decimal("1.50")]
        assert await _attempt_statuses(seeded, seeded.entry.id) == [
            NodeAttemptStatus.UNCERTAIN.value
        ]

    async def test_a_lost_claim_settle_keeps_its_cost_through_the_reclaimers_resolution(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            return await _spend("1.50")

        seeded = await _seed(engine, _chain(node_kind(handler), 1))
        begun = await _claim_and_begin(seeded, seeded.entry.id)
        await _expire_claims(seeded)
        async with seeded.factory() as db:
            reclaim = await dispatcher.claim(db, node_run_id=seeded.entry.id)
            await db.commit()
        assert reclaim is not None and reclaim.claimed_by is not None
        outcome = await dispatcher.call_handler(begun)
        async with seeded.factory() as db:
            await dispatcher.settle(db, begun=begun, outcome=outcome)
            await db.commit()

        async with seeded.factory() as db:
            resolved = await dispatcher.begin_attempt(
                db,
                workflow_run_id=seeded.run.id,
                node_run_id=seeded.entry.id,
                token=reclaim.claimed_by,
            )
            await db.commit()

        assert resolved is None
        assert (await _run_row(seeded)).spent_cost == Decimal("1.50")
        assert await _attempt_costs(seeded) == [Decimal("1.50")]


async def _release_backoff(seeded: Seeded) -> None:
    """Make every row a backoff scheduled due now."""
    async with seeded.factory() as db:
        await db.execute(
            sql_update(DispatchOutbox)
            .where(
                DispatchOutbox.workflow_run_id == seeded.run.id,
                DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
            )
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def test_waits_do_not_use_up_the_retries_a_later_failure_is_owed(
    engine: AsyncEngine, node_kind
):
    """Two backoff waits used to count as two of the three attempts, so the
    node's first real failure failed the run with no retry at all."""
    calls: list[int] = []

    async def handler(_config: object, _input: object) -> NodeResult:
        calls.append(context.current().attempt_no)
        if len(calls) <= 2:
            return Waiting(reason="retry_backoff", resume_token="t")
        return Failed(error=WorkflowError(code="FLAKY", message="try again", retryable=True))

    seeded = await _seed(engine, _chain(node_kind(handler), 1))
    await _tick(seeded, seeded.entry.id)
    for _ in range(2 + settings.WORKFLOW_RETRY_CEILING - 1):
        await _release_backoff(seeded)
        await _tick(seeded, seeded.entry.id)
        if calls[-1] == 3:
            # The first failure is retried, not fatal.
            assert (await _run_row(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value

    statuses = await _attempt_statuses(seeded, seeded.entry.id)
    assert statuses == ["completed", "completed"] + ["failed"] * settings.WORKFLOW_RETRY_CEILING
    assert (await _run_row(seeded)).status == WorkflowRunStatus.FAILED.value
