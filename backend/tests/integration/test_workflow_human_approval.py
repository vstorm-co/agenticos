"""`human.approval`, driven through the dispatcher against a real database.

What is proved is the whole wait: the step asks once and parks, a decision wakes
it and it goes on by the answer, a lost wake and an expiry are found by the
reconciler, a cancelled run closes its requests, and who may decide is who the
step names.
"""

import json
import threading
import uuid
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.db.models.workflow_approval import WorkflowApproval, WorkflowApprovalStatus
from app.db.models.workflow_run import NodeAttempt, NodeRun, NodeRunStatus, WorkflowRunStatus
from app.repositories import workflow_approval as approval_repo
from app.schemas.workflow_approval import WorkflowApprovalRead
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
    seeded: SeededRun,
    approval_id: uuid.UUID,
    *,
    approved: bool,
    ctx: AuthContext | None = None,
    final: str | None = None,
    choice: str | None = None,
) -> WorkflowApprovalRead:
    async with seeded.factory() as db:
        decided = await WorkflowApprovalService(db).decide(
            ctx or seeded.ctx,
            approval_id,
            approved=approved,
            note="checked the order",
            final=final,
            choice=choice,
        )
        await db.commit()
    return decided


async def _audit(seeded: SeededRun) -> list[AppAdminAuditLog]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.organization_id == seeded.org.id,
                        AppAdminAuditLog.action.like("workflow_approval.%"),
                    )
                )
            ).scalars()
        )


async def _another_member(seeded: SeededRun, *, role: str = "admin") -> AuthContext:
    async with seeded.factory() as db:
        user = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.io", hashed_password="x", is_active=True
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=seeded.org.id, user_id=user.id, role=role
            )
        )
        await db.commit()
    return AuthContext(user_id=user.id, organization_id=seeded.org.id, role=role)


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


def _editable_graph(proposal: str | None, **config: Any) -> Graph:
    """The standard graph, with `proposal` bound to the step when there is one."""
    shape = Graph(**config)
    if proposal is not None:
        shape.graph = shape.graph.model_copy(
            update={
                "bindings": (
                    *shape.graph.bindings,
                    Binding(
                        target_node_id=shape.ask.id,
                        target_field="proposal",
                        source=LiteralValue(value=proposal),
                    ),
                )
            }
        )
    return shape


async def _record(seeded: SeededRun, approval_id: uuid.UUID, **values: Any) -> None:
    """Decide the row the way the service will: by writing what it records."""
    async with seeded.factory() as db:
        approval = await approval_repo.get_for_node_run_for_update(
            db, (await _request(seeded)).node_run_id
        )
        assert approval is not None and approval.id == approval_id
        await approval_repo.update(
            db,
            approval=approval,
            update_data={"decided_by_user_id": seeded.principal.id, **values},
        )
        await db.commit()


async def _step_output(seeded: SeededRun, node_run_id: uuid.UUID) -> dict[str, Any]:
    async with seeded.factory() as db:
        attempts = (
            await db.execute(
                select(NodeAttempt)
                .where(NodeAttempt.node_run_id == node_run_id, NodeAttempt.result.is_not(None))
                .order_by(NodeAttempt.attempt_no.desc())
            )
        ).scalars()
        result = next(iter(attempts)).result
    assert result is not None
    return dict(result["output"])


class TestAnEditableStep:
    async def test_an_editable_step_asks_with_its_proposal(self, engine: AsyncEngine):
        seeded = await seed_run(
            engine,
            _editable_graph(
                "Dear customer",
                editable=True,
                proposal_format="markdown",
                proposal_label="Reply",
            ).graph,
        )
        await drive(seeded)

        request = await _request(seeded)
        assert request.editable is True
        assert request.proposal == "Dear customer"
        assert request.proposal_format == "markdown"
        assert request.proposal_label == "Reply"
        assert (request.final, request.edited) == (None, False)

    async def test_an_editable_step_with_nothing_bound_asks_with_an_empty_proposal(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, _editable_graph(None, editable=True).graph)
        await drive(seeded)

        request = await _request(seeded)
        assert request.editable is True
        assert request.proposal == ""
        assert request.proposal_format == "text"
        assert request.proposal_label is None

    async def test_a_plain_step_keeps_a_bound_proposal_read_only(self, engine: AsyncEngine):
        seeded = await seed_run(engine, _editable_graph("Dear customer").graph)
        await drive(seeded)

        request = await _request(seeded)
        assert request.editable is False
        assert request.proposal == "Dear customer"

    async def test_a_plain_step_with_nothing_bound_stores_no_proposal(self, engine: AsyncEngine):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)

        assert (await _request(seeded)).proposal is None

    async def test_the_step_hands_on_what_the_row_records(self, engine: AsyncEngine):
        shape = _editable_graph("A", editable=True)
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)
        request = await _request(seeded)
        await _record(
            seeded,
            request.id,
            status=WorkflowApprovalStatus.APPROVED.value,
            decided_at=datetime.now(UTC),
            final="B",
            edited=True,
        )
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["original"], output["edited"]) == ("B", "A", True)
        assert routes(output) == frozenset({"approved"})
        statuses = await node_statuses(seeded)
        assert statuses[shape.yes.id] == NodeRunStatus.SUCCEEDED.value

    async def test_a_plain_step_hands_on_the_recorded_final(self, engine: AsyncEngine):
        seeded = await seed_run(engine, _editable_graph("A").graph)
        await drive(seeded)
        request = await _request(seeded)
        await _record(
            seeded,
            request.id,
            status=WorkflowApprovalStatus.APPROVED.value,
            decided_at=datetime.now(UTC),
            final="A",
        )
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)

        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["original"], output["edited"]) == ("A", "A", False)

    async def test_an_expired_editable_request_carries_no_final(self, engine: AsyncEngine):
        shape = _editable_graph("A", editable=True, timeout_hours=1)
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)
        request = await _request(seeded)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowApproval)
                .where(WorkflowApproval.id == request.id)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await db.commit()
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)

        output = await _step_output(seeded, request.node_run_id)
        assert output["decision"] == "expired"
        assert (output["final"], output["original"], output["edited"]) == (None, "A", False)
        assert routes(output) == frozenset({"rejected"})

    async def _decided_step(
        self,
        engine: AsyncEngine,
        wakes,
        *,
        proposal: str | None,
        approved: bool = True,
        final: str | None = None,
        **config: Any,
    ) -> tuple[SeededRun, WorkflowApproval, WorkflowApprovalRead]:
        seeded = await seed_run(engine, _editable_graph(proposal, **config).graph)
        await drive(seeded)
        request = await _request(seeded)
        decided = await _decide(seeded, request.id, approved=approved, final=final)
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)
        return seeded, request, decided

    async def test_an_edited_approval_goes_on_with_the_edit(self, engine: AsyncEngine, wakes):
        seeded, request, decided = await self._decided_step(
            engine, wakes, proposal="Dear customer", final="Dear Ann", editable=True
        )
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["original"], output["edited"]) == (
            "Dear Ann",
            "Dear customer",
            True,
        )
        assert (decided.final, decided.proposal, decided.edited) == (
            "Dear Ann",
            "Dear customer",
            True,
        )

    async def test_an_approval_without_an_edit_hands_on_the_proposal(
        self, engine: AsyncEngine, wakes
    ):
        seeded, request, decided = await self._decided_step(
            engine, wakes, proposal="Dear customer", editable=True
        )
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["edited"]) == ("Dear customer", False)
        assert (decided.final, decided.edited) == ("Dear customer", False)

    async def test_a_whitespace_only_change_is_not_an_edit(self, engine: AsyncEngine, wakes):
        seeded, request, decided = await self._decided_step(
            engine, wakes, proposal="A\r\nB  \n", final="A\nB", editable=True
        )
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["edited"]) == ("A\nB", False)
        assert decided.edited is False

    async def test_a_plain_step_hands_its_proposal_on_as_final(self, engine: AsyncEngine, wakes):
        seeded, request, decided = await self._decided_step(engine, wakes, proposal="Dear customer")
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["original"], output["edited"]) == (
            "Dear customer",
            "Dear customer",
            False,
        )
        assert (decided.final, decided.edited) == ("Dear customer", False)

    async def test_a_plain_step_refuses_a_final_naming_the_field(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, _editable_graph("A").graph)
        await drive(seeded)
        request = await _request(seeded)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=True, final="B")
        assert refused.value.details["fields"][0]["field"] == "final"
        assert (await _request(seeded)).status == WorkflowApprovalStatus.PENDING.value
        assert await _audit(seeded) == []
        assert wakes == []

    async def test_a_final_for_a_decided_plain_step_is_a_validation_error_not_a_state_error(
        self, engine: AsyncEngine, wakes
    ):
        seeded = await seed_run(engine, _editable_graph("A").graph)
        await drive(seeded)
        request = await _request(seeded)
        await _decide(seeded, request.id, approved=True)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=True, final="B")
        assert refused.value.details["fields"][0]["field"] == "final"

    async def test_a_rejection_with_a_final_is_refused(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, _editable_graph("A", editable=True).graph)
        await drive(seeded)
        request = await _request(seeded)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=False, final="B")
        assert refused.value.details["fields"][0]["field"] == "final"
        assert (await _request(seeded)).status == WorkflowApprovalStatus.PENDING.value
        assert await _audit(seeded) == []

    async def test_a_rejection_carries_no_final(self, engine: AsyncEngine, wakes):
        seeded, request, decided = await self._decided_step(
            engine, wakes, proposal="A", approved=False, editable=True
        )
        output = await _step_output(seeded, request.node_run_id)
        assert (output["final"], output["original"], output["edited"]) == (None, "A", False)
        assert (decided.final, decided.edited) == (None, False)

    async def test_the_audit_holds_lengths_and_never_the_text(self, engine: AsyncEngine, wakes):
        proposal, final = "PROPOSAL-MARKER-7f3", "FINAL-MARKER-91c plus more"
        seeded, _request_row, _decided = await self._decided_step(
            engine, wakes, proposal=proposal, final=final, editable=True
        )
        (entry,) = await _audit(seeded)
        assert entry.action == "workflow_approval.approved"
        assert entry.details is not None
        assert (
            entry.details["edited"],
            entry.details["editable"],
            entry.details["proposal_length"],
            entry.details["final_length"],
        ) == (True, True, len(proposal), len(final))
        dumped = json.dumps(entry.details)
        assert "PROPOSAL-MARKER-7f3" not in dumped and "FINAL-MARKER-91c" not in dumped

    async def test_a_request_made_before_proposals_decides_as_before(
        self, engine: AsyncEngine, wakes
    ):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        request = await _request(seeded)
        async with seeded.factory() as db:
            # The row as a deployment's older requests are: none of the new keywords.
            await db.execute(delete(WorkflowApproval).where(WorkflowApproval.id == request.id))
            legacy = await approval_repo.create(
                db,
                organization_id=request.organization_id,
                workflow_id=request.workflow_id,
                workflow_run_id=request.workflow_run_id,
                node_run_id=request.node_run_id,
                title=request.title,
                details=request.details,
                approver_user_ids=[],
                expires_at=None,
            )
            await db.commit()
        decided = await _decide(seeded, legacy.id, approved=True)
        assert (decided.final, decided.edited) == (None, False)
        assert decided.status == WorkflowApprovalStatus.APPROVED


class TestWhatADecisionRecords:
    async def _decided(
        self,
        engine: AsyncEngine,
        wakes,
        *,
        proposal: str | None,
        approved: bool = True,
        final: str | None = None,
        **config: Any,
    ) -> tuple[SeededRun, WorkflowApproval, WorkflowApprovalRead]:
        seeded = await seed_run(engine, _editable_graph(proposal, **config).graph)
        await drive(seeded)
        request = await _request(seeded)
        decided = await _decide(seeded, request.id, approved=approved, final=final)
        return seeded, await _request(seeded), decided

    async def test_an_unchanged_approval_records_no_edit(self, engine: AsyncEngine, wakes):
        seeded, row, _decided = await self._decided(
            engine, wakes, proposal="Hello Anna", editable=True
        )
        assert (row.edited, row.edit_ratio) == (False, 0.0)

    async def test_an_edited_approval_records_how_much_changed(self, engine: AsyncEngine, wakes):
        seeded, row, _decided = await self._decided(
            engine, wakes, proposal="Hello Anna", final="Hello Ann", editable=True
        )
        assert (row.edited, row.edit_ratio) == (True, round(1 / 10, 6))

    async def test_a_whitespace_only_change_records_no_edit(self, engine: AsyncEngine, wakes):
        seeded, row, _decided = await self._decided(
            engine, wakes, proposal="A\r\nB  \n", final="A\nB", editable=True
        )
        assert (row.edited, row.edit_ratio) == (False, 0.0)

    async def test_a_unicode_only_change_records_no_edit(self, engine: AsyncEngine, wakes):
        # Composed and decomposed é (Zoé): the same text, however a browser or a mail
        # client happened to write it.
        seeded, row, _decided = await self._decided(
            engine, wakes, proposal="Zo\u00e9", final="Zoe\u0301", editable=True
        )
        assert (row.edited, row.edit_ratio) == (False, 0.0)

    async def test_an_editable_step_with_nothing_to_edit_records_no_edit(
        self, engine: AsyncEngine, wakes
    ):
        seeded, row, _decided = await self._decided(engine, wakes, proposal=None, editable=True)
        assert (row.edited, row.edit_ratio) == (False, 0.0)

    async def test_a_rejection_records_no_ratio(self, engine: AsyncEngine, wakes):
        seeded, row, _decided = await self._decided(
            engine, wakes, proposal="A", approved=False, editable=True
        )
        assert row.edit_ratio is None

    async def test_a_plain_step_records_no_ratio(self, engine: AsyncEngine, wakes):
        seeded, row, _decided = await self._decided(engine, wakes, proposal="A")
        assert row.edit_ratio is None

    async def test_a_decision_is_scored_off_the_event_loop(
        self, engine: AsyncEngine, wakes, monkeypatch: pytest.MonkeyPatch
    ):
        threads: list[bool] = []
        real = approvals_service.text_similarity.compare

        def spy(*args: Any, **kwargs: Any):
            threads.append(threading.current_thread() is threading.main_thread())
            return real(*args, **kwargs)

        monkeypatch.setattr(approvals_service.text_similarity, "compare", spy)
        await self._decided(engine, wakes, proposal="Hello Anna", final="Hello Ann", editable=True)
        assert threads == [False]

    async def test_the_audit_holds_the_ratio_and_never_the_text(self, engine: AsyncEngine, wakes):
        seeded, _row, _decided = await self._decided(
            engine,
            wakes,
            proposal="PROPOSAL-MARKER-7f3",
            final="FINAL-MARKER-91c plus more",
            editable=True,
        )
        (entry,) = await _audit(seeded)
        assert entry.details is not None
        ratio = entry.details["edit_ratio"]
        assert isinstance(ratio, float) and 0 < ratio <= 1
        dumped = json.dumps(entry.details)
        assert "PROPOSAL-MARKER-7f3" not in dumped and "FINAL-MARKER-91c" not in dumped

    async def test_a_rejection_audits_no_ratio(self, engine: AsyncEngine, wakes):
        seeded, _row, _decided = await self._decided(
            engine, wakes, proposal="A", approved=False, editable=True
        )
        (entry,) = await _audit(seeded)
        assert entry.details is not None and entry.details["edit_ratio"] is None


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

    async def test_a_final_from_someone_the_step_does_not_name_is_refused(
        self, engine: AsyncEngine, wakes
    ):
        # A plain step, so the final is also a 422: the 403 provably wins.
        seeded = await seed_run(engine, _editable_graph("A").graph)
        approver = await _another_member(seeded)
        await drive(seeded)
        request = await _request(seeded)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowApproval)
                .where(WorkflowApproval.id == request.id)
                .values(approver_user_ids=[str(approver.user_id)])
            )
            await db.commit()

        with pytest.raises(AuthorizationError):
            await _decide(seeded, request.id, approved=True, final="B")
        stored = await _request(seeded)
        assert (stored.status, stored.final, stored.edited) == (
            WorkflowApprovalStatus.PENDING.value,
            None,
            False,
        )
        assert await _audit(seeded) == []

    async def test_a_final_for_another_organizations_request_is_not_found(
        self, engine: AsyncEngine, wakes
    ):
        # A plain step, so the final is also a 422: the 404 provably wins.
        seeded = await seed_run(engine, _editable_graph("A").graph)
        await drive(seeded)
        stranger = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
        with pytest.raises(NotFoundError):
            await _decide(
                seeded, (await _request(seeded)).id, approved=True, ctx=stranger, final="B"
            )
        assert (await _request(seeded)).final is None

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

    async def test_the_record_reads_newest_first_inside_its_window(
        self, engine: AsyncEngine, wakes
    ):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        async with seeded.factory() as db:
            (item,) = (await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])).items
        await _decide(seeded, item.id, approved=True)
        asked = item.created_at
        decided = [WorkflowApprovalStatus.APPROVED]

        async with seeded.factory() as db:
            service = WorkflowApprovalService(db)
            inside = await service.queue(
                seeded.ctx,
                statuses=decided,
                created_from=asked - timedelta(minutes=1),
                created_to=asked + timedelta(minutes=1),
                oldest_first=False,
            )
            before = await service.queue(
                seeded.ctx, statuses=decided, created_to=asked - timedelta(minutes=1)
            )
            after = await service.queue(
                seeded.ctx, statuses=decided, created_from=asked + timedelta(minutes=1)
            )
        assert [row.id for row in inside.items] == [item.id]
        assert before.total == 0 and after.total == 0


_CHOICES = [{"id": "draft", "label": "Keep a draft"}, {"id": "send_now", "label": "Send now"}]


class ChoiceGraph:
    """Input, an approval step with choices, then one echo on each of its ports."""

    def __init__(self, **config: Any) -> None:
        self.entry = _node("core.input")
        self.ask = _node(
            "human.approval", {"title": "Send the reply?", "choices": _CHOICES, **config}
        )
        self.draft = _node("debug.echo", {"message": "drafted"})
        self.send = _node("debug.echo", {"message": "sent"})
        self.no = _node("debug.echo", {"message": "held"})
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.ask, self.draft, self.send, self.no),
            edges=(
                _edge(self.entry, "out", self.ask),
                _edge(self.ask, "draft", self.draft),
                _edge(self.ask, "send_now", self.send),
                _edge(self.ask, "rejected", self.no),
            ),
        )


class TestChoices:
    async def test_the_row_stores_the_choices_when_the_step_asks(self, engine: AsyncEngine):
        seeded = await seed_run(engine, ChoiceGraph().graph)
        await drive(seeded)
        request = await _request(seeded)
        assert request.choices == _CHOICES
        assert request.choice is None
        async with seeded.factory() as db:
            queue = await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])
        assert [(c.id, c.label) for c in queue.items[0].choices] == [
            ("draft", "Keep a draft"),
            ("send_now", "Send now"),
        ]
        assert queue.items[0].choice is None

    async def test_a_step_without_choices_stores_none_and_reads_an_empty_list(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        assert (await _request(seeded)).choices is None
        async with seeded.factory() as db:
            queue = await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])
        assert queue.items[0].choices == []

    @pytest.mark.parametrize("chosen", ["draft", "send_now"])
    async def test_an_approval_leaves_by_the_chosen_port(
        self, engine: AsyncEngine, wakes, chosen: str
    ):
        shape = ChoiceGraph()
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)
        request = await _request(seeded)
        decided = await _decide(seeded, request.id, approved=True, choice=chosen)
        assert decided.choice == chosen
        assert (await _request(seeded)).choice == chosen
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)
        output = await _step_output(seeded, request.node_run_id)
        assert (output["decision"], output["choice"]) == ("approved", chosen)
        assert routes(output) == frozenset({chosen})
        ran = await node_statuses(seeded)
        taken, other = (shape.draft, shape.send) if chosen == "draft" else (shape.send, shape.draft)
        assert ran[taken.id] == NodeRunStatus.SUCCEEDED.value
        assert ran[other.id] == NodeRunStatus.SKIPPED.value
        assert ran[shape.no.id] == NodeRunStatus.SKIPPED.value

    async def test_a_rejection_leaves_by_rejected_with_no_choice(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, ChoiceGraph().graph)
        await drive(seeded)
        request = await _request(seeded)
        decided = await _decide(seeded, request.id, approved=False)
        assert decided.choice is None
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)
        output = await _step_output(seeded, request.node_run_id)
        assert (output["decision"], output["choice"]) == ("rejected", None)
        assert routes(output) == frozenset({"rejected"})

    async def test_an_expired_request_leaves_by_rejected(self, engine: AsyncEngine):
        seeded = await seed_run(engine, ChoiceGraph(timeout_hours=1).graph)
        await drive(seeded)
        request = await _request(seeded)
        async with seeded.factory() as db:
            await db.execute(
                update(WorkflowApproval)
                .where(WorkflowApproval.id == request.id)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await db.commit()
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)
        output = await _step_output(seeded, request.node_run_id)
        assert (output["decision"], output["choice"]) == ("expired", None)
        assert routes(output) == frozenset({"rejected"})

    @pytest.mark.parametrize("choice", [None, "", "archive", "approved", "rejected"])
    async def test_an_approval_needs_one_of_the_choices(
        self, engine: AsyncEngine, wakes, choice: str | None
    ):
        seeded = await seed_run(engine, ChoiceGraph().graph)
        await drive(seeded)
        request = await _request(seeded)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=True, choice=choice)
        assert refused.value.details["fields"][0]["field"] == "choice"
        assert (await _request(seeded)).status == WorkflowApprovalStatus.PENDING.value
        assert await _audit(seeded) == []
        assert wakes == []

    async def test_a_step_without_choices_refuses_a_choice(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, Graph().graph)
        await drive(seeded)
        request = await _request(seeded)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=True, choice="draft")
        assert refused.value.details["fields"][0]["field"] == "choice"
        assert (await _request(seeded)).status == WorkflowApprovalStatus.PENDING.value
        assert wakes == []

    async def test_a_rejection_with_a_choice_is_refused(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, ChoiceGraph().graph)
        await drive(seeded)
        request = await _request(seeded)
        with pytest.raises(ValidationError) as refused:
            await _decide(seeded, request.id, approved=False, choice="draft")
        assert refused.value.details["fields"][0]["field"] == "choice"
        assert (await _request(seeded)).status == WorkflowApprovalStatus.PENDING.value
        assert await _audit(seeded) == []

    async def test_the_audit_records_the_choice_id(self, engine: AsyncEngine, wakes):
        seeded = await seed_run(engine, ChoiceGraph().graph)
        await drive(seeded)
        request = await _request(seeded)
        await _decide(seeded, request.id, approved=True, choice="send_now")
        (entry,) = await _audit(seeded)
        assert entry.details["choice"] == "send_now"

    async def test_the_choice_goes_with_an_edit(self, engine: AsyncEngine, wakes):
        shape = ChoiceGraph(editable=True)
        shape.graph = shape.graph.model_copy(
            update={
                "bindings": (
                    Binding(
                        target_node_id=shape.ask.id,
                        target_field="proposal",
                        source=LiteralValue(value="Dear customer"),
                    ),
                )
            }
        )
        seeded = await seed_run(engine, shape.graph)
        await drive(seeded)
        request = await _request(seeded)
        decided = await _decide(
            seeded, request.id, approved=True, final="Dear Ann", choice="send_now"
        )
        assert (decided.choice, decided.final, decided.edited) == ("send_now", "Dear Ann", True)
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        await drive(seeded)
        output = await _step_output(seeded, request.node_run_id)
        assert (output["choice"], output["final"], output["edited"]) == (
            "send_now",
            "Dear Ann",
            True,
        )


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


@pytest.mark.security
@pytest.mark.parametrize("role", ["member", "builder", "viewer"])
async def test_a_named_approver_without_decision_permission_cannot_park_a_run(
    engine: AsyncEngine,
    role: str,
) -> None:
    seeded = await seed_run(engine, Graph().graph)
    approver = await _another_member(seeded, role=role)
    config = HumanApprovalConfig(title="Proceed?", approvers=(approver.user_id,))
    async with seeded.factory() as db:
        problems = await check_resources(db, seeded.ctx, config)
    assert problems == [("approvers.0", "This person cannot decide approvals in the organization")]

    named = await seed_run(
        engine,
        Graph(approvers=[str(approver.user_id)]).graph,
        member=(seeded.principal, seeded.org),
    )
    run = await drive(named)
    assert run.status == "failed"
    assert run.error is not None and run.error["code"] == "APPROVER_UNAVAILABLE"


class TestTheQueueCarriesTheProposal:
    async def test_the_queue_lists_the_proposal_and_its_mode(self, engine: AsyncEngine):
        seeded = await seed_run(
            engine,
            _editable_graph(
                "Dear customer", editable=True, proposal_format="markdown", proposal_label="Reply"
            ).graph,
        )
        await drive(seeded)
        async with seeded.factory() as db:
            (item,) = (await WorkflowApprovalService(db).queue(seeded.ctx, statuses=[])).items
        assert (item.editable, item.proposal, item.proposal_format, item.proposal_label) == (
            True,
            "Dear customer",
            "markdown",
            "Reply",
        )
