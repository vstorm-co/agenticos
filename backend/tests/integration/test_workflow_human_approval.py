"""`human.approval`, driven through the dispatcher against a real database.

What is proved is the whole wait: the step asks once and parks, a decision wakes
it and it goes on by the answer, a lost wake and an expiry are found by the
reconciler, a cancelled run closes its requests, and who may decide is who the
step names.
"""

from __future__ import annotations

import uuid
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.db.models.workflow_approval import WorkflowApproval, WorkflowApprovalStatus
from app.db.models.workflow_run import NodeRun, NodeRunStatus, WorkflowRunStatus
from app.services.workflow_execution import approvals as approvals_service
from app.services.workflow_execution.approvals import (
    WorkflowApprovalService,
    wake_approval_step,
)
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.workflows.contracts.io import Binding, LiteralValue
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes.human_approval._handler import (
    HumanApprovalConfig,
    check_resources,
    handle,
    routes,
)
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    node_statuses,
    run_row,
    seed_run,
)

# Who may decide what a run waits on is a governance control, so every test here
# is a security test.
pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, port: str, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


class Graph:
    """Input, then the approval step, then one echo on each of its answers."""

    def __init__(self, **config: Any) -> None:
        self.entry = _node("core.input")
        self.ask = _node("human.approval", {"title": "Send the refund?", **config})
        self.yes = _node("debug.echo", {"message": "sent"})
        self.no = _node("debug.echo", {"message": "held"})
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.ask, self.yes, self.no),
            edges=(
                _edge(self.entry, "out", self.ask),
                _edge(self.ask, "approved", self.yes),
                _edge(self.ask, "rejected", self.no),
            ),
            bindings=(
                Binding(
                    target_node_id=self.ask.id,
                    target_field="details",
                    source=LiteralValue(value="Refund 40 EUR to order 1182"),
                ),
            ),
        )


@pytest.fixture
def wakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Coroutine[Any, Any, None]]]:
    """The wakes a decision queues for after its commit, held for the test to run."""
    queued: list[Coroutine[Any, Any, None]] = []

    def hold(_session: object, coro: Coroutine[Any, Any, None], *, name: str) -> None:
        queued.append(coro)

    monkeypatch.setattr(approvals_service, "spawn_after_commit", hold)
    yield queued
    for coro in queued:
        coro.close()


async def _request(seeded: SeededRun) -> WorkflowApproval:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(WorkflowApproval).where(WorkflowApproval.workflow_run_id == seeded.run.id)
            )
        ).scalar_one()


async def _decide(
    seeded: SeededRun, approval_id: uuid.UUID, *, approved: bool, ctx: AuthContext | None = None
) -> None:
    async with seeded.factory() as db:
        await WorkflowApprovalService(db).decide(
            ctx or seeded.ctx, approval_id, approved=approved, note="checked the order"
        )
        await db.commit()


async def _another_member(seeded: SeededRun) -> AuthContext:
    async with seeded.factory() as db:
        user = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.io", hashed_password="x", is_active=True
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=seeded.org.id, user_id=user.id, role="admin"
            )
        )
        await db.commit()
    return AuthContext(user_id=user.id, organization_id=seeded.org.id, role="admin")


class TestTheWait:
    async def test_it_asks_once_parks_and_goes_on_by_the_approval(self, engine: AsyncEngine, wakes):
        shape = Graph()
        seeded = await seed_run(engine, shape.graph)

        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_APPROVAL.value
        request = await _request(seeded)
        assert "Send the refund?" in repr(request)
        assert (request.title, request.details) == (
            "Send the refund?",
            "Refund 40 EUR to order 1182",
        )
        assert request.status == WorkflowApprovalStatus.PENDING.value

        # A wake before anyone decides - a duplicate, or the reconciler's - finds the
        # request still pending and parks the step again.
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value

        await _decide(seeded, request.id, approved=True)
        (wake,) = wakes
        await wake
        wakes.clear()
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        statuses = await node_statuses(seeded)
        assert statuses[shape.yes.id] == NodeRunStatus.SUCCEEDED.value
        assert statuses[shape.no.id] == NodeRunStatus.SKIPPED.value
        decided = await _request(seeded)
        assert decided.decided_by_user_id == seeded.principal.id
        assert decided.note == "checked the order"

    async def test_a_rejection_goes_the_other_way(self, engine: AsyncEngine, wakes):
        shape = Graph()
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)

        await _decide(seeded, (await _request(seeded)).id, approved=False)
        await wakes.pop()
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        statuses = await node_statuses(seeded)
        assert statuses[shape.no.id] == NodeRunStatus.SUCCEEDED.value
        assert statuses[shape.yes.id] == NodeRunStatus.SKIPPED.value

    async def test_a_lost_wake_is_found_by_the_reconciler_once(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        await _decide(seeded, (await _request(seeded)).id, approved=True)
        wakes.pop().close()

        async with seeded.factory() as db:
            assert await WorkflowReconcilerService(db).wake_stale_step_approvals() == 1
            await db.commit()
        async with seeded.factory() as db:
            # The row it queued is live, so the next sweep leaves the step alone.
            assert await WorkflowReconcilerService(db).wake_stale_step_approvals() == 0
        # The direct wake arriving late finds the row already there.
        await wake_approval_step(
            (await _request(seeded)).node_run_id, organization_id=seeded.org.id
        )

        assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value

    async def test_a_request_nobody_decides_in_time_expires_and_is_refused(
        self, engine: AsyncEngine, wakes
    ):
        shape = Graph(timeout_hours=1)
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)
        request = await _request(seeded)
        assert request.expires_at is not None
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowApproval)
                .where(WorkflowApproval.id == request.id)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await db.commit()

        with pytest.raises(BadRequestError, match="expired"):
            await _decide(seeded, request.id, approved=True)
        async with seeded.factory() as db:
            assert await WorkflowReconcilerService(db).wake_stale_step_approvals() == 1
            await db.commit()
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        assert (await node_statuses(seeded))[shape.no.id] == NodeRunStatus.SUCCEEDED.value
        assert (await _request(seeded)).status == WorkflowApprovalStatus.EXPIRED.value

    async def test_cancelling_the_run_closes_what_it_asked(self, engine: AsyncEngine):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        async with seeded.factory() as db:
            await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
            await db.commit()

        assert (await _request(seeded)).status == WorkflowApprovalStatus.CANCELLED.value
        async with seeded.factory() as db:
            queue = await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])
        assert queue.total == 0


class TestWhoDecides:
    async def test_a_step_that_names_approvers_is_decided_only_by_them(
        self, engine: AsyncEngine, wakes
    ):
        seeded = await seed_run(engine, Graph().graph)
        approver = await _another_member(seeded)
        await drive(seeded)
        request = await _request(seeded)
        async with seeded.factory() as db:
            # Name the second member alone, as a step naming them would have.
            await db.execute(
                update(WorkflowApproval)
                .where(WorkflowApproval.id == request.id)
                .values(approver_user_ids=[str(approver.user_id)])
            )
            await db.commit()

        with pytest.raises(AuthorizationError):
            await _decide(seeded, request.id, approved=True)
        await _decide(seeded, request.id, approved=True, ctx=approver)

        # A decision is final.
        with pytest.raises(BadRequestError, match="already approved"):
            await _decide(seeded, request.id, approved=False, ctx=approver)

    async def test_a_request_of_another_organization_is_not_found(self, engine: AsyncEngine):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        stranger = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
        with pytest.raises(NotFoundError):
            await _decide(seeded, (await _request(seeded)).id, approved=True, ctx=stranger)

    async def test_named_approvers_are_told_and_must_be_members(self, engine: AsyncEngine):
        seeded = await seed_run(engine, Graph().graph)
        approver = await _another_member(seeded)
        shape = Graph(approvers=[str(approver.user_id)])
        named = await seed_run(engine, shape.graph, member=(seeded.principal, seeded.org))
        await drive(named)

        async with named.factory() as db:
            told = (
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.recipient_user_id == approver.user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [row.summary for row in told] == ["Approval needed: Send the refund?"]
            config = HumanApprovalConfig(title="x", approvers=(approver.user_id, uuid.uuid4()))
            problems = await check_resources(db, seeded.ctx, config)
            assert [field for field, _message in problems] == ["approvers.1"]
            assert await check_resources(db, seeded.ctx, MagicMock()) == []


class TestTheQueue:
    async def test_it_lists_pending_requests_with_their_workflow_and_the_decided_on_asking(
        self, engine: AsyncEngine, wakes
    ):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        async with seeded.factory() as db:
            pending = await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])
        (item,) = pending.items
        assert (item.workflow_name, item.title, item.approver_user_ids) == (
            "Graph",
            "Send the refund?",
            [],
        )

        await _decide(seeded, item.id, approved=False)
        async with seeded.factory() as db:
            service = WorkflowApprovalService(db)
            assert (await service.queue(seeded.ctx, statuses=[])).total == 0
            decided = await service.queue(seeded.ctx, statuses=[WorkflowApprovalStatus.REJECTED])
        assert decided.items[0].status == WorkflowApprovalStatus.REJECTED


class TestTheStep:
    async def test_a_step_with_nothing_to_ask_says_so_and_routes_nothing(self):
        result = await handle(None, None)
        assert result.error.code == "APPROVAL_NOT_CONFIGURED"
        assert routes(None) == frozenset()
        assert routes({"decision": "expired"}) == frozenset({"rejected"})

    async def test_a_wake_for_a_step_that_is_gone_or_elsewhere_does_nothing(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        request = await _request(seeded)
        await wake_approval_step(uuid.uuid4(), organization_id=seeded.org.id)
        await wake_approval_step(request.node_run_id, organization_id=uuid.uuid4())
        async with seeded.factory() as db:
            await db.execute(
                update(NodeRun)
                .where(NodeRun.id == request.node_run_id)
                .values(status=NodeRunStatus.SUCCEEDED.value)
            )
            await db.commit()
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        assert (await run_row(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value
