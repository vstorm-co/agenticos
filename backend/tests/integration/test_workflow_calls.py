"""One workflow running another as a step: the call, the wait, the answer, the limits."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import DispatchOutbox, NodeRunStatus, WorkflowRun
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish
from app.services.workflow_execution import delivery
from app.services.workflow_execution.exceptions import WorkflowAdmissionQuotaError
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    node_statuses,
    seed_member,
    seed_run,
)

pytestmark = pytest.mark.anyio

FIELDS = {"fields": [{"name": "name", "type": "text", "required": True}]}


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _read(target: NodeInstance, field: str, source: NodeInstance, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port="out", field_path=path),
    )


def _callee(fail: bool = False) -> WorkflowGraph:
    """Called by a workflow, declaring `name` -> an answer naming it, or a refusal."""
    entry = _node("trigger.workflow_call", FIELDS)
    if fail:
        refuse = _node("error.raise", {"code": "NO_LEAD", "message": "No such lead"})
        return WorkflowGraph(
            entry_node_id=entry.id, nodes=(entry, refuse), edges=(_edge(entry, refuse),)
        )
    out = _node("core.output")
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, out),
        edges=(_edge(entry, out),),
        bindings=(_read(out, "text", entry, "payload", "name"),),
    )


def _caller(
    callee_id: uuid.UUID, *, wait: bool = True, name: object = "Ada"
) -> tuple[WorkflowGraph, NodeInstance]:
    entry, call, out = (
        _node("core.input"),
        _node("workflow.run", {"workflow_id": str(callee_id), "wait": wait}),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, call, out),
        edges=(_edge(entry, call), _edge(call, out)),
        bindings=(
            Binding(
                target_node_id=call.id,
                target_field="input",
                source=LiteralValue(value={"name": name}),
            ),
            _read(out, "structured", call, "output"),
        ),
    )
    return graph, call


async def _published_callee(
    engine: AsyncEngine, graph: WorkflowGraph
) -> tuple[AuthContext, Workflow, tuple]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        member = await seed_member(db)
        ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=ctx.subject_id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Enrich a lead",
            status=WorkflowStatus.DRAFT.value,
            visibility=Visibility.ORG.value,
            draft_graph=graph.model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        await WorkflowRegistryService(db).publish(
            ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
        )
        await db.commit()
    return ctx, workflow, member


async def _called_run(seeded: SeededRun, step: NodeInstance) -> SeededRun:
    async with seeded.factory() as db:
        step_run = await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=seeded.run.id, node_instance_id=step.id, scope_path=[]
        )
        assert step_run is not None
        called = await workflow_run_repo.get_run_called_by(db, node_run_id=step_run.id)
        assert called is not None
        version = await db.get(WorkflowVersion, called.workflow_version_id)
        assert version is not None
    return SeededRun(
        run=called,
        graph=WorkflowGraph.model_validate(version.graph),
        principal=seeded.principal,
        org=seeded.org,
        factory=seeded.factory,
    )


class TestCallingAWorkflow:
    async def test_the_step_waits_for_the_called_run_and_hands_on_its_answer(
        self, engine: AsyncEngine
    ):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)

        parked = await drive(seeded)
        assert parked.status == "running"
        assert (await node_statuses(seeded))[step.id] == NodeRunStatus.WAITING.value

        called = await _called_run(seeded, step)
        assert called.run.triggered_by == "workflow_call"
        assert called.run.causation_run_id == seeded.run.id
        assert f"workflow:{callee.id}" in called.run.visited_trigger_ids
        assert (await drive(called)).status == "succeeded"

        finished = await drive(seeded)
        assert finished.status == "succeeded"
        assert finished.output["structured"] == {
            "text": "Ada",
            "sources": [],
            "artifacts": [],
            "structured": None,
        }

    async def test_a_call_that_does_not_wait_goes_on_at_once(self, engine: AsyncEngine):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, _step = _caller(callee.id, wait=False)
        seeded = await seed_run(engine, graph, member=member)

        finished = await drive(seeded)

        assert finished.status == "succeeded"

    async def test_a_called_run_that_fails_fails_the_step_with_its_error(self, engine: AsyncEngine):
        _ctx, callee, member = await _published_callee(engine, _callee(fail=True))
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        await drive(seeded)
        await drive(await _called_run(seeded, step))

        finished = await drive(seeded)

        assert finished.status == "failed"
        assert finished.error["code"] == "CALLED_WORKFLOW_FAILED"
        assert "No such lead" in finished.error["message"]

    async def test_an_input_the_called_workflow_refuses_fails_the_step_before_it_runs(
        self, engine: AsyncEngine
    ):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, _step = _caller(callee.id, name=7)
        seeded = await seed_run(engine, graph, member=member)

        finished = await drive(seeded)

        assert finished.error["code"] == "WORKFLOW_RUN_INPUT_INVALID"

    async def test_a_called_run_that_ended_before_the_step_parked_still_wakes_it(
        self, engine: AsyncEngine
    ):
        from app.workflows.contracts.results import Waiting
        from app.workflows.nodes.workflow_run import _handler

        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        await drive(seeded)
        called = await _called_run(seeded, step)
        async with seeded.factory() as db:
            # The called run ends with no wake reaching the step, and the step is
            # dispatched once more, still reading the run as it stood before.
            await workflow_run_repo.update_run(
                db,
                run=called.run,
                update_data={"status": "succeeded", "output": {"text": "early"}},
            )
            step_run = await workflow_run_repo.get_node_run_by_identity(
                db, workflow_run_id=seeded.run.id, node_instance_id=step.id, scope_path=[]
            )
            assert step_run is not None
            await workflow_run_repo.create_outbox(
                db,
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                node_run_id=step_run.id,
            )
            await db.commit()
        answer = _handler._answer
        stale = {"once": True}

        def still_running(run: WorkflowRun, *, wait: bool):
            if stale.pop("once", False):
                return Waiting(reason="external_event", resume_token="x")
            return answer(run, wait=wait)

        with patch.object(_handler, "_answer", new=still_running):
            finished = await drive(seeded)

        assert finished.status == "succeeded"
        assert finished.output["structured"]["text"] == "early"


class TestTheLimits:
    async def _refusal(self, engine: AsyncEngine, **run_fields: Any) -> dict[str, Any]:
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, _step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        async with seeded.factory() as db:
            visited = run_fields.pop("visited", None)
            if visited is not None:
                run_fields["visited_trigger_ids"] = [f"workflow:{callee.id}"]
            await workflow_run_repo.update_run(db, run=seeded.run, update_data=run_fields)
            await db.commit()
        return (await drive(seeded)).error

    async def test_a_call_back_into_the_chain_is_refused(self, engine: AsyncEngine):
        assert (await self._refusal(engine, visited=True))["code"] == "WORKFLOW_CALL_LOOP"

    async def test_a_chain_too_deep_is_refused(self, engine: AsyncEngine):
        assert (await self._refusal(engine, depth=5))["code"] == "WORKFLOW_CALL_TOO_DEEP"

    async def test_a_workflow_calling_itself_is_refused(self, engine: AsyncEngine):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, _step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        async with seeded.factory() as db:
            run = await db.get(WorkflowRun, seeded.run.id)
            assert run is not None
            run.workflow_id = callee.id
            await db.commit()

        assert (await drive(seeded)).error["code"] == "WORKFLOW_CALL_LOOP"

    async def test_a_workflow_no_longer_callable_or_out_of_reach_is_refused(
        self, engine: AsyncEngine
    ):
        _ctx, callee, member = await _published_callee(engine, _callee())
        for how in ("archived", "no_version", "no_access"):
            graph, _step = _caller(callee.id)
            seeded = await seed_run(engine, graph, member=member)
            patches = {
                "no_version": patch(
                    "app.workflows.nodes.workflow_run._handler.workflow_repo.get_version",
                    new=AsyncMock(return_value=None),
                ),
                "no_access": patch(
                    "app.workflows.nodes.workflow_run._handler.resolve_access",
                    new=AsyncMock(return_value=False),
                ),
            }
            if how == "archived":
                async with seeded.factory() as db:
                    row = await db.get(Workflow, callee.id)
                    assert row is not None
                    row.status = WorkflowStatus.ARCHIVED.value
                    await db.commit()
                error = (await drive(seeded)).error
                async with seeded.factory() as db:
                    row = await db.get(Workflow, callee.id)
                    assert row is not None
                    row.status = WorkflowStatus.PUBLISHED.value
                    await db.commit()
            else:
                with patches[how]:
                    error = (await drive(seeded)).error
            assert error["code"] == "CALLED_WORKFLOW_UNAVAILABLE", how

    async def test_too_much_work_in_flight_is_retried_rather_than_failed(self, engine: AsyncEngine):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        with patch(
            "app.services.workflow_execution.facade.admission.enforce_admission_quota",
            new=AsyncMock(
                side_effect=WorkflowAdmissionQuotaError(
                    scope="organization", limit=1, outstanding=1, requested=1
                )
            ),
        ):
            run = await drive(seeded)

        assert run.status == "waiting_retry"


class TestPublishing:
    async def test_the_step_names_a_workflow_published_to_be_called_that_the_author_can_run(
        self, engine: AsyncEngine
    ):
        ctx, callee, member = await _published_callee(engine, _graph_manual())
        graph, _step = _caller(callee.id)
        async with async_sessionmaker(engine)() as db:
            with pytest.raises(GraphValidationError) as refused:
                await validate_graph(db, ctx, graph)
            messages = [problem["message"] for problem in refused.value.details["fields"]]
            assert "Publish that workflow starting from Called by a workflow first" in messages

            missing, _call = _caller(uuid.uuid4())
            with pytest.raises(GraphValidationError) as unknown:
                await validate_graph(db, ctx, missing)
            assert "No workflow you can run has that id" in str(unknown.value.details)

        _ctx2, good, _member = await _published_callee(engine, _callee())
        ok, _step2 = _caller(good.id)
        other = AuthContext(
            user_id=_ctx2.subject_id, organization_id=_ctx2.organization_id, role="owner"
        )
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, other, ok)


def _graph_manual() -> WorkflowGraph:
    entry = _node("trigger.manual")
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


class TestWakingTheCaller:
    async def test_a_caller_that_ended_or_moved_on_is_left_alone(self, engine: AsyncEngine):
        _ctx, callee, member = await _published_callee(engine, _callee())
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        await drive(seeded)
        called = await _called_run(seeded, step)

        async with seeded.factory() as db:
            run = await db.get(WorkflowRun, called.run.id)
            assert run is not None
            # Woken once; a second wake finds the row already live.
            await delivery.wake_caller(db, run=run)
            await delivery.wake_caller(db, run=run)
            rows = await db.execute(
                select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == seeded.run.id)
            )
            assert len([row for row in rows.scalars() if row.status == "pending"]) == 1
            caller = await db.get(WorkflowRun, seeded.run.id)
            assert caller is not None
            caller.status = "cancelled"
            await db.flush()
            await delivery.wake_caller(db, run=run)
            # A run whose caller is gone, and one nothing called, wake nothing.
            db.expunge(run)
            run.parent_node_run_id = uuid.uuid4()
            await delivery.wake_caller(db, run=run)
            run.parent_node_run_id = None
            await delivery.wake_caller(db, run=run)


class TestAdmittingACall:
    """`admit_call` called directly: the step's own call reaches it past an await the
    coverage tracer loses."""

    async def test_the_called_run_is_linked_to_the_step_and_its_dispatch_submitted(
        self, engine: AsyncEngine
    ):
        from app.services.workflow_execution import WorkflowExecutionService
        from app.services.workflow_execution.facade import Causation

        ctx, callee, member = await _published_callee(engine, _callee())
        graph, step = _caller(callee.id)
        seeded = await seed_run(engine, graph, member=member)
        async with seeded.factory() as db:
            workflow = await db.get(Workflow, callee.id)
            assert workflow is not None
            version = await db.get(WorkflowVersion, workflow.current_version_id)
            assert version is not None
            entry = await workflow_run_repo.get_node_run_by_identity(
                db,
                workflow_run_id=seeded.run.id,
                node_instance_id=graph.entry_node_id,
                scope_path=[],
            )
            assert entry is not None
            with patch("app.worker.tasks.workflow_tasks.trigger_dispatch") as dispatched:
                called = await WorkflowExecutionService(db).admit_call(
                    ctx,
                    workflow,
                    version,
                    run_input={"name": "Ada"},
                    causation=Causation(
                        root_run_id=seeded.run.id,
                        causation_run_id=seeded.run.id,
                        visited_trigger_ids=[],
                        depth=1,
                    ),
                    parent_node_run_id=entry.id,
                )

        assert called.parent_node_run_id == entry.id
        assert called.triggered_by == "workflow_call"
        dispatched.assert_called_once()
