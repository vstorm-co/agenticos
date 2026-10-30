"""Resolving a step that needs attention in place: run it again, route its error,
fail the run, or use the result that arrived late (#1800 slice 2).

Every case drives a real run through the dispatcher against Postgres until one step is
`needs_attention` - its attempt ended `uncertain` - and then resolves it the way the
route does, through `WorkflowExecutionService.resolve_step`, on the same run.
"""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeRun,
    NodeRunStatus,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish
from app.schemas.workflow_run import WorkflowStepResolve
from app.services.workflow_execution import WorkflowExecutionService, context, dispatcher
from app.services.workflow_execution.exceptions import WorkflowStepNotResolvableError
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.contracts.policy import NodePolicy
from app.workflows.contracts.results import Completed, NodeResult, Uncertain
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import (
    SeededRun,
    begin,
    drive,
    node_statuses,
    run_row,
    seed_member,
    seed_run,
    settle,
    tick,
)

pytestmark = pytest.mark.anyio


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sent: bool = True


# What each `test.attention` step does on its next call, by step: "uncertain" or "done".
script: dict[uuid.UUID, list[str]] = {}
calls: list[uuid.UUID] = []


async def _attention(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    step = context.current().node_instance_id
    calls.append(step)
    if script.get(step, ["done"]).pop(0) == "uncertain":
        return Uncertain(detail="Cannot tell whether the write landed")
    return Completed[_Out](output=_Out())


@pytest.fixture
def attention() -> Iterator[None]:
    definition = NodeDefinition(
        id="test.attention",
        version=1,
        name="Attention",
        category="test",
        description="A test node that is sometimes unsure.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=_Out,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=_Out),
        ),
        effect_kind="write",
        retry_guarantee="none",
        handler=_attention,
    )
    register(definition)
    script.clear()
    calls.clear()
    yield
    REGISTRY.pop(definition.id, None)


def _node(
    definition_id: str, config: dict[str, Any] | None = None, *, policy: NodePolicy | None = None
) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        policy=policy,
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _map(field: str) -> dict[str, Any]:
    return {"mappings": [{"target_field": field, "source_path": "'x'"}]}


class _Line:
    """entry -> step -> after; `step` is unsure the first time it runs."""

    def __init__(self, *, routes_errors: bool = False) -> None:
        self.entry = _node("core.input")
        self.step = _node(
            "test.attention", policy=NodePolicy(on_error="route") if routes_errors else None
        )
        self.after = _node("data.map", _map("a"))
        self.rescue = _node("data.map", _map("rescued"))
        nodes = [self.entry, self.step, self.after]
        edges = [_edge(self.entry, self.step), _edge(self.step, self.after)]
        if routes_errors:
            nodes.append(self.rescue)
            edges.append(_edge(self.step, self.rescue, "error"))
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id, nodes=tuple(nodes), edges=tuple(edges)
        )
        script[self.step.id] = ["uncertain", "done"]


async def _row(seeded: SeededRun, node: NodeInstance) -> NodeRun:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id,
                    NodeRun.node_instance_id == node.id,
                    NodeRun.scope_path == [],
                )
            )
        ).scalar_one()


async def _until_unsure(seeded: SeededRun, line: _Line) -> NodeRun:
    await drive(seeded)
    step = await _row(seeded, line.step)
    assert step.status == NodeRunStatus.NEEDS_ATTENTION.value
    assert (await run_row(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value
    return step


async def _resolve(
    seeded: SeededRun, step: NodeRun, choice: str, *, ctx: AuthContext | None = None
) -> WorkflowRun:
    async with seeded.factory() as db:
        read = await WorkflowExecutionService(db).resolve_step(
            ctx or seeded.ctx,
            seeded.run.id,
            step.id,
            WorkflowStepResolve.model_validate({"choice": choice}),
        )
        await db.commit()
    assert read.id == seeded.run.id
    return await run_row(seeded)


async def _attempts(seeded: SeededRun, step: NodeRun) -> list[NodeAttempt]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(NodeAttempt)
                    .where(NodeAttempt.node_run_id == step.id)
                    .order_by(NodeAttempt.attempt_no)
                )
            )
            .scalars()
            .all()
        )


async def _events(seeded: SeededRun, kind: str) -> list[WorkflowEvent]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(WorkflowEvent).where(
                        WorkflowEvent.workflow_run_id == seeded.run.id, WorkflowEvent.kind == kind
                    )
                )
            )
            .scalars()
            .all()
        )


async def _orphan_with_late_result(
    seeded: SeededRun, step: NodeRun
) -> tuple[dispatcher.BegunAttempt, dispatcher.HandlerOutcome]:
    """The step's handler finishes, but the reconciler had resolved its attempt first."""
    begun, outcome = await begin(seeded, step.id)
    async with seeded.factory() as db:
        run = await workflow_run_repo.get_run_by_id_for_update(db, seeded.run.id)
        node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, step.id)
        attempt = await workflow_run_repo.get_attempt(db, begun.attempt_id)
        outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(db, node_run_id=step.id)
        assert run is not None and node_run is not None and attempt is not None
        await dispatcher.resolve_orphaned_attempt(
            db, run=run, node_run=node_run, attempt=attempt, outbox=outbox
        )
        await db.commit()
    return begun, outcome


async def test_running_a_step_again_dispatches_it_on_the_same_run(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    resumed = await _resolve(seeded, step, "run_again")

    assert resumed.id == seeded.run.id
    assert resumed.status == WorkflowRunStatus.RUNNING.value
    assert (await _row(seeded, line.step)).status == NodeRunStatus.PENDING.value
    finished = await drive(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert [attempt.attempt_no for attempt in await _attempts(seeded, step)] == [1, 2]
    (resolved,) = await _events(seeded, "node_resolved")
    assert resolved.payload == {"choice": "run_again", "attempt_no": 1}


async def test_a_second_click_is_refused(engine: AsyncEngine, attention: None):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)
    await _resolve(seeded, step, "run_again")

    with pytest.raises(WorkflowStepNotResolvableError) as refused:
        await _resolve(seeded, step, "run_again")

    assert refused.value.details["reason"] == "not_needing_attention"


async def test_two_clicks_at_once_apply_once(engine: AsyncEngine, attention: None):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    outcomes = await asyncio.gather(
        _resolve(seeded, step, "run_again"),
        _resolve(seeded, step, "run_again"),
        return_exceptions=True,
    )

    refused = [o for o in outcomes if isinstance(o, WorkflowStepNotResolvableError)]
    done = [o for o in outcomes if isinstance(o, WorkflowRun)]
    assert (len(done), len(refused)) == (1, 1)
    async with seeded.factory() as db:
        queued = (
            (
                await db.execute(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == step.id,
                        DispatchOutbox.status.in_(["pending", "claimed"]),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(queued) == 1
    assert len(await _events(seeded, "node_resolved")) == 1
    assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value
    assert [attempt.attempt_no for attempt in await _attempts(seeded, step)] == [1, 2]


async def test_treating_a_step_as_failed_takes_its_error_route(
    engine: AsyncEngine, attention: None
):
    line = _Line(routes_errors=True)
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    resumed = await _resolve(seeded, step, "use_error_route")

    assert resumed.status == WorkflowRunStatus.RUNNING.value
    assert (await _row(seeded, line.step)).status == NodeRunStatus.FAILED.value
    finished = await drive(seeded)
    statuses = await node_statuses(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert statuses[line.rescue.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[line.after.id] == NodeRunStatus.SKIPPED.value


async def test_the_error_route_hands_the_handler_the_marked_failure(
    engine: AsyncEngine, attention: None
):
    step = _node("test.attention", policy=NodePolicy(on_error="route"))
    entry = _node("core.input")
    handler = _node(
        "error.handle", {"branches": [{"name": "marked", "code": "STEP_MARKED_FAILED"}]}
    )
    marked, other = _node("data.map", _map("marked")), _node("data.map", _map("other"))
    after = _node("data.map", _map("a"))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, step, after, handler, marked, other),
        edges=(
            _edge(entry, step),
            _edge(step, after),
            _edge(step, handler, "error"),
            _edge(handler, marked, "marked"),
            _edge(handler, other, "default"),
        ),
    )
    script[step.id] = ["uncertain", "done"]
    seeded = await seed_run(engine, graph)
    await drive(seeded)
    row = await _row(seeded, step)
    assert row.status == NodeRunStatus.NEEDS_ATTENTION.value

    await _resolve(seeded, row, "use_error_route")
    finished = await drive(seeded)

    statuses = await node_statuses(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert statuses[handler.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[marked.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[other.id] == NodeRunStatus.SKIPPED.value
    [handled] = await _attempts(seeded, await _row(seeded, handler))
    assert handled.result is not None
    assert handled.result["output"]["code"] == "STEP_MARKED_FAILED"
    marker = (await _attempts(seeded, row))[-1]
    assert marker.result is not None and marker.result["error"]["code"] == "STEP_MARKED_FAILED"


async def test_the_error_route_inside_a_loop_is_collected_with_its_error(
    engine: AsyncEngine, attention: None
):
    entry, loop = _node("core.input"), _node("control.foreach", {"item_error_policy": "collect"})
    item, step, yield_, out = (
        _node("loop.item"),
        _node("test.attention"),
        _node("loop.yield"),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, step, yield_, out),
        edges=(
            _edge(entry, loop),
            _edge(loop, item, "body"),
            _edge(loop, out, "done"),
            _edge(item, step),
            _edge(step, yield_),
        ),
        bindings=(
            Binding(
                target_node_id=loop.id,
                target_field="items",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload", "items")),
            ),
            Binding(
                target_node_id=yield_.id,
                target_field="value",
                source=NodeOutputRef(node_id=item.id, port="out", field_path=("index",)),
            ),
            Binding(
                target_node_id=out.id,
                target_field="structured",
                source=NodeOutputRef(node_id=loop.id, port="done", field_path=()),
            ),
        ),
    )
    script[step.id] = ["uncertain", "done"]
    seeded = await seed_run(engine, graph, run_input={"items": [1]})
    await drive(seeded)
    async with seeded.factory() as db:
        row = (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id,
                    NodeRun.node_instance_id == step.id,
                )
            )
        ).scalar_one()
    assert row.status == NodeRunStatus.NEEDS_ATTENTION.value

    await _resolve(seeded, row, "use_error_route")
    finished = await drive(seeded)

    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert finished.output is not None
    assert finished.output["structured"]["errors"][0]["code"] == "STEP_MARKED_FAILED"


async def test_treating_a_step_as_failed_without_a_route_is_refused(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    with pytest.raises(WorkflowStepNotResolvableError) as refused:
        await _resolve(seeded, step, "use_error_route")

    assert refused.value.details["reason"] == "no_error_route"
    assert (await _row(seeded, line.step)).status == NodeRunStatus.NEEDS_ATTENTION.value
    assert await _events(seeded, "node_resolved") == []


async def test_failing_the_run_ends_it_with_the_step_marked_failed(
    engine: AsyncEngine, attention: None
):
    line = _Line(routes_errors=True)
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    with patch(
        "app.services.workflow_execution.dispatcher.failure.start_error_workflow",
        new=AsyncMock(),
    ) as error_workflow:
        ended = await _resolve(seeded, step, "fail_run")

    assert ended.status == WorkflowRunStatus.FAILED.value
    assert ended.error is not None and ended.error["code"] == "STEP_MARKED_FAILED"
    # Not routed, though the step routes its errors: the person asked for the run to fail.
    assert (await _row(seeded, line.step)).status == NodeRunStatus.FAILED.value
    assert line.rescue.id not in await node_statuses(seeded)
    error_workflow.assert_awaited_once()
    assert error_workflow.await_args.kwargs["error"].code == "STEP_MARKED_FAILED"
    assert error_workflow.await_args.kwargs["step_id"] == line.step.id


async def test_a_result_arriving_after_uncertain_is_kept_and_can_be_used(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    script[line.step.id] = ["done"]
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    begun, outcome = await _orphan_with_late_result(seeded, step)
    assert (await _row(seeded, line.step)).status == NodeRunStatus.NEEDS_ATTENTION.value

    await settle(seeded, begun, outcome)

    (kept,) = await _attempts(seeded, step)
    assert kept.status == "uncertain"
    assert kept.late_result is not None and kept.late_result["output"] == {"sent": True}
    async with seeded.factory() as db:
        steps = await WorkflowExecutionService(db).node_runs(seeded.ctx, seeded.run.id)
    shown = next(item for item in steps.items if item.id == step.id)
    assert shown.last_attempt_status == "uncertain" and shown.late_output == {"sent": True}

    await _resolve(seeded, step, "use_late_result")

    async with seeded.factory() as db:
        after = await WorkflowExecutionService(db).node_runs(seeded.ctx, seeded.run.id)
    used = next(item for item in after.items if item.id == step.id)
    assert used.last_attempt_status == "completed" and used.late_output is None
    assert (await _row(seeded, line.step)).status == NodeRunStatus.SUCCEEDED.value
    finished = await drive(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert calls == [line.step.id]  # never run again
    attempts = await _attempts(seeded, step)
    assert [attempt.retry_guarantee for attempt in attempts] == ["none", None]
    assert attempts[1].result == kept.late_result


async def test_using_a_late_result_that_never_came_is_refused(engine: AsyncEngine, attention: None):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    with pytest.raises(WorkflowStepNotResolvableError) as refused:
        await _resolve(seeded, step, "use_late_result")

    assert refused.value.details["reason"] == "no_late_result"


async def _forced_to_need_attention(seeded: SeededRun, step: NodeRun, *, close_dispatch: bool):
    """A step made `needs_attention` by hand: no try recorded, and its dispatch row open or not."""
    async with seeded.factory() as db:
        node = await workflow_run_repo.get_node_run_by_id_for_update(db, step.id)
        assert node is not None
        await workflow_run_repo.update_node_run(
            db, node_run=node, update_data={"status": NodeRunStatus.NEEDS_ATTENTION.value}
        )
        if close_dispatch:
            outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(
                db, node_run_id=step.id
            )
            assert outbox is not None
            await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        await db.commit()


async def test_a_step_with_no_recorded_try_can_still_be_run_again(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    await _forced_to_need_attention(seeded, step, close_dispatch=True)

    await _resolve(seeded, step, "run_again")

    (resolved,) = await _events(seeded, "node_resolved")
    assert resolved.payload["attempt_no"] == 0


async def test_a_step_that_already_has_a_dispatch_row_is_refused_not_queued_twice(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    await _forced_to_need_attention(seeded, step, close_dispatch=False)

    with pytest.raises(WorkflowStepNotResolvableError) as refused:
        await _resolve(seeded, step, "run_again")

    assert refused.value.details["reason"] == "not_needing_attention"
    assert await _events(seeded, "node_resolved") == []


@pytest.mark.parametrize("why", ["failed", "completed", "not_waiting", "too_large", "no_room"])
async def test_a_late_result_is_kept_only_for_an_uncertain_try_of_a_step_needing_attention(
    engine: AsyncEngine, attention: None, why: str
):
    line = _Line()
    script[line.step.id] = ["done"]
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    begun, outcome = await _orphan_with_late_result(seeded, step)
    if why == "failed":
        from dataclasses import replace

        from app.workflows.contracts.results import Failed, WorkflowError

        outcome = replace(outcome, result=Failed(error=WorkflowError(code="X", message="x")))
    if why == "not_waiting":
        await _resolve(seeded, step, "run_again")
    if why == "completed":
        async with seeded.factory() as db:
            attempt = await workflow_run_repo.get_attempt(db, begun.attempt_id)
            assert attempt is not None
            attempt.status = "completed"
            await db.commit()
    patches = []
    if why == "too_large":
        patches.append(
            patch(
                "app.services.workflow_execution.dispatcher._outcome_payloads_fit",
                side_effect=__import__(
                    "app.workflows.contracts.payload", fromlist=["PayloadTooLarge"]
                ).PayloadTooLarge,
            )
        )
    if why == "no_room":
        from app.services.workflow_execution.dispatcher import _inline_storage_error

        patches.append(
            patch(
                "app.services.workflow_execution.dispatcher._reserve_inline_result",
                new=AsyncMock(return_value=_inline_storage_error("run")),
            )
        )
    for item in patches:
        item.start()
    try:
        await settle(seeded, begun, outcome)
    finally:
        for item in patches:
            item.stop()

    (attempt,) = (await _attempts(seeded, step))[:1]
    assert attempt.late_result is None
    assert (await run_row(seeded)).status != WorkflowRunStatus.FAILED.value


async def test_resolving_one_step_leaves_another_needing_attention(
    engine: AsyncEngine, attention: None
):
    entry = _node("core.input")
    first, second = _node("test.attention"), _node("test.attention")
    script[first.id] = ["uncertain", "done"]
    script[second.id] = ["uncertain", "done"]
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, first, second),
        edges=(_edge(entry, first), _edge(entry, second)),
    )
    seeded = await seed_run(engine, graph)
    await drive(seeded)
    one, two = await _row(seeded, first), await _row(seeded, second)

    resumed = await _resolve(seeded, one, "run_again")

    assert (await _row(seeded, second)).status == NodeRunStatus.NEEDS_ATTENTION.value
    assert resumed.status == WorkflowRunStatus.NEEDS_ATTENTION.value
    assert (await _row(seeded, first)).status == NodeRunStatus.PENDING.value
    await _resolve(seeded, two, "run_again")
    assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value


async def test_resolving_a_step_is_audited_with_the_step_attempt_and_choice(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    seeded = await seed_run(engine, line.graph)
    step = await _until_unsure(seeded, line)

    await _resolve(seeded, step, "run_again")

    async with seeded.factory() as db:
        entry = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "workflow_run.step_resolved"
                )
            )
        ).scalar_one()
    assert entry.organization_id == seeded.org.id
    assert entry.actor_user_id == seeded.principal.id
    assert (entry.target_type, entry.target_id) == ("workflow_run", str(seeded.run.id))
    assert entry.details == {
        "node_run_id": str(step.id),
        "node_instance_id": str(line.step.id),
        "attempt_no": 1,
        "choice": "run_again",
    }


# A called run resolved in place


async def _publish(
    engine: AsyncEngine, graph: WorkflowGraph, member: tuple | None = None
) -> tuple[Workflow, tuple]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        member = member or await seed_member(db)
        ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=ctx.subject_id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Callee",
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
    return workflow, member


async def test_a_called_run_resolved_in_place_wakes_its_caller(
    engine: AsyncEngine, attention: None
):
    entry, step, out = (
        _node("trigger.workflow_call", {"fields": []}),
        _node("test.attention"),
        _node("core.output"),
    )
    script[step.id] = ["uncertain", "done"]
    callee_graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, step, out),
        edges=(_edge(entry, step), _edge(step, out)),
        bindings=(
            Binding(target_node_id=out.id, target_field="text", source=LiteralValue(value="done")),
        ),
    )
    callee, member = await _publish(engine, callee_graph)
    caller_entry = _node("core.input")
    call = _node("workflow.run", {"workflow_id": str(callee.id), "wait": True})
    caller_out = _node("core.output")
    caller_graph = WorkflowGraph(
        entry_node_id=caller_entry.id,
        nodes=(caller_entry, call, caller_out),
        edges=(_edge(caller_entry, call), _edge(call, caller_out)),
        bindings=(
            Binding(target_node_id=call.id, target_field="input", source=LiteralValue(value={})),
            Binding(
                target_node_id=caller_out.id,
                target_field="text",
                source=LiteralValue(value="caller done"),
            ),
        ),
    )
    caller = await seed_run(engine, caller_graph, member=member)
    await drive(caller)
    async with caller.factory() as db:
        call_row = await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=caller.run.id, node_instance_id=call.id, scope_path=[]
        )
        assert call_row is not None
        called = await workflow_run_repo.get_run_called_by(db, node_run_id=call_row.id)
        assert called is not None
    child = SeededRun(
        run=called,
        graph=callee_graph,
        principal=caller.principal,
        org=caller.org,
        factory=caller.factory,
    )
    await drive(child)
    assert (await run_row(child)).status == WorkflowRunStatus.NEEDS_ATTENTION.value
    stuck = await _row(child, step)

    await _resolve(child, stuck, "run_again")
    assert (await drive(child)).status == WorkflowRunStatus.SUCCEEDED.value

    assert (await drive(caller)).status == WorkflowRunStatus.SUCCEEDED.value


async def test_a_duplicate_late_delivery_keeps_the_first_and_books_nothing_again(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    script[line.step.id] = ["done"]
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    begun, outcome = await _orphan_with_late_result(seeded, step)

    await settle(seeded, begun, outcome)
    booked = (await run_row(seeded)).inline_result_bytes
    (kept,) = await _attempts(seeded, step)
    await settle(seeded, begun, outcome)

    assert (await run_row(seeded)).inline_result_bytes == booked > 0
    (again,) = await _attempts(seeded, step)
    assert again.late_result == kept.late_result


async def test_a_step_that_answers_the_run_never_offers_its_late_result(
    engine: AsyncEngine, attention: None
):
    line = _Line()
    script[line.step.id] = ["done"]
    seeded = await seed_run(engine, line.graph)
    await tick(seeded, (await _row(seeded, line.entry)).id)
    step = await _row(seeded, line.step)
    begun, outcome = await _orphan_with_late_result(seeded, step)
    await settle(seeded, begun, outcome)

    with (
        patch.dict(dispatcher._REPORTS, {"test.attention": lambda _data: None}),
        pytest.raises(WorkflowStepNotResolvableError) as refused,
    ):
        await _resolve(seeded, step, "use_late_result")

    assert refused.value.details["reason"] == "no_late_result"
