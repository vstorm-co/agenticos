"""The two Python steps, driven through the dispatcher (#1791).

`code.python.simple` runs in the real Monty sandbox. `code.python.sandbox`
runs against an in-memory stand-in for a `sandboxd` session, so what is proved
is the job protocol: launch once, check on every later dispatch, reconnect to
the same session after a worker died, finish a half-done launch, and import
what the job left behind.
"""

import itertools
import json
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.workspaces import FileEntry, WorkspaceError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.background import discard_deferred
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.db.models.mcp_connection import McpConnection
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.db.models.workflow_approval import WorkflowApproval
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeRun,
    ResourceRef,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.sandbox_connection import SandboxConnectionCreate
from app.services.file_storage import LocalFileStorage
from app.services.workflow_execution import dispatcher
from app.services.workflow_execution.approvals import WorkflowApprovalService, wake_approval_step
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.services.workflow_execution.resume import WorkflowResumeService
from app.services.workflow_execution.resume_link import resume_token
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef
from app.workflows.contracts.payload import json_byte_size
from app.workflows.contracts.policy import NodePolicy, RetryPolicy
from app.workflows.contracts.results import Completed, Failed, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes import _sandbox_job as job
from app.workflows.nodes.code_javascript_sandbox import _handler as js_node
from app.workflows.nodes.code_python_sandbox import _handler as sandbox_node
from app.workflows.nodes.mcp_call import _handler as mcp_node
from tests.integration.workflow_run_support import (
    SeededRun,
    begin,
    drive,
    run_row,
    seed_member,
    seed_run,
    settle,
    tick,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.workflows.files.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
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


def _chain(step: NodeInstance, *bindings: Binding) -> WorkflowGraph:
    entry, output = _node("core.input"), _node("core.output")
    nodes = (entry, step, output)
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=nodes,
        edges=tuple(_edge(a, b) for a, b in itertools.pairwise(nodes)),
        bindings=(
            *bindings,
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=step.id, port="out"),
            ),
        ),
    )


def _literal(node: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=node.id, target_field=field, source=LiteralValue(value=value))


async def _failed_code(seeded: SeededRun) -> str:
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.FAILED.value, run.status
    assert run.error is not None
    return run.error["code"]


class TestTheMontyScript:
    async def test_the_last_expression_over_the_bound_args_is_the_result(self, engine):
        step = _node(
            "code.python.simple", {"code": "print('scored')\nsum(args['s']) / len(args['s'])"}
        )
        run = await drive(
            await seed_run(engine, _chain(step, _literal(step, "args", {"s": [2, 4]})))
        )
        assert run.output["structured"] == {"result": 3.0, "stdout": "scored\n"}

    async def test_a_script_with_nothing_bound_reads_empty_args(self, engine):
        step = _node("code.python.simple", {"code": "len(args)"})
        run = await drive(await seed_run(engine, _chain(step)))
        assert run.output["structured"]["result"] == 0

    @pytest.mark.parametrize(
        ("code", "error"),
        [
            ("{1, 2}", "PYTHON_OUTPUT_NOT_JSON"),
            ("undefined_name", "PYTHON_ERROR"),
            ("def (", "PYTHON_ERROR"),
        ],
        ids=["a-set", "a-name-error", "a-syntax-error"],
    )
    async def test_a_script_that_fails_or_answers_no_json_fails_the_step(self, engine, code, error):
        seeded = await seed_run(engine, _chain(_node("code.python.simple", {"code": code})))
        assert await _failed_code(seeded) == error

    async def test_a_step_with_no_script_says_so(self):
        from app.workflows.nodes.code_python_simple import _handler

        result = await _handler.handle(None, None)
        assert result.error.code == "PYTHON_NOT_CONFIGURED"


class TestPythonWithActions:
    async def test_numeric_action_identity_survives_the_jsonb_round_trip(self, engine: AsyncEngine):
        step = _node(
            "code.python.actions",
            {
                "actions": {"store": {"type": "data.value"}},
                "code": "store(value={'samples': [1.2345678901234568e20, -0.0, 1e-8]})['value']",
            },
        )
        run = await drive(await seed_run(engine, _chain(step)))
        assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
        # int(float) gives 123456789012345683968, not the decimal sent to PostgreSQL.
        assert run.output["structured"]["result"]["samples"] == [123456789012345680000, 0.0, 1e-8]

    async def test_a_required_action_field_can_come_entirely_from_the_script(
        self, engine: AsyncEngine
    ):
        step = _node(
            "code.python.actions",
            {
                "actions": {
                    "make_table": {
                        "type": "table.create",
                        "config": {
                            "columns": [{"label": "Title", "type": "text"}],
                        },
                    }
                },
                "code": "make_table(name=args['name'])['table_id']",
            },
        )
        graph = _chain(step, _literal(step, "args", {"name": "Service Requests"}))
        seeded = await seed_run(engine, graph)
        async with seeded.factory() as db:
            await validate_graph(db, seeded.ctx, graph)
        finished = await drive(seeded)
        assert finished.status == WorkflowRunStatus.SUCCEEDED.value, finished.error
        async with seeded.factory() as db:
            created = await db.get(VirtualTable, uuid.UUID(finished.output["structured"]["result"]))
            assert created is not None and created.name == "Service Requests"

    async def test_a_script_can_compute_the_filename_for_each_native_file_action(
        self, engine: AsyncEngine
    ):
        step = _node(
            "code.python.actions",
            {
                "actions": {"write_note": {"type": "convert.text_to_file"}},
                "code": "for case in args['cases']:\n write_note(filename=case + '.txt', text=case)\nlen(args['cases'])",
            },
        )
        seeded = await seed_run(
            engine, _chain(step, _literal(step, "args", {"cases": ["case-1", "case-2"]}))
        )
        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
        assert run.output["structured"]["result"] == 2
        async with seeded.factory() as db:
            names = await db.scalars(
                select(WorkflowFile.filename).where(WorkflowFile.workflow_run_id == run.id)
            )
            assert sorted(names) == ["case-1.txt", "case-2.txt"]

    async def test_an_action_result_can_drive_the_next_call(self, engine: AsyncEngine):
        step = _node(
            "code.python.actions",
            {
                "actions": {"echo": {"type": "debug.echo"}},
                "code": "value = args['text']\nfor i in range(4):\n value = echo(message=value + str(i))['echoed']\nvalue",
            },
        )
        seeded = await seed_run(engine, _chain(step, _literal(step, "args", {"text": "start"})))
        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
        assert run.output["structured"] == {"result": "start0123", "stdout": ""}
        async with seeded.factory() as db:
            rows = (
                await db.scalars(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == run.id, NodeRun.node_instance_id == step.id
                    )
                )
            ).all()
        children = sorted(
            (row for row in rows if row.scope_path), key=lambda r: r.scope_path[-1]["index"]
        )
        assert [row.scope_path[-1]["action"] for row in children] == ["echo"] * 4
        assert [row.scope_path[-1]["index"] for row in children] == [0, 1, 2, 3]
        assert all(row.status == "succeeded" for row in children)

    async def test_each_iteration_waits_for_its_own_decision(self, engine: AsyncEngine):
        step = _node(
            "code.python.actions",
            {
                "actions": {
                    "review": {"type": "human.approval", "config": {"title": "Review this item?"}}
                },
                "code": "[review(details=item)['decision'] for item in args['items']]",
            },
        )
        seeded = await seed_run(
            engine, _chain(step, _literal(step, "args", {"items": ["first", "second"]}))
        )
        ids = set()
        for item, approved in [("first", True), ("second", False)]:
            run = await drive(seeded)
            assert run.status == WorkflowRunStatus.WAITING_APPROVAL.value, run.error
            async with seeded.factory() as db:
                request = (
                    await db.scalars(
                        select(WorkflowApproval).where(
                            WorkflowApproval.workflow_run_id == run.id,
                            WorkflowApproval.status == "pending",
                        )
                    )
                ).one()
                assert request.details == item
                assert request.node_run_id not in ids
                ids.add(request.node_run_id)
                await WorkflowApprovalService(db).decide(seeded.ctx, request.id, approved=approved)
                await db.commit()
                discard_deferred(db)
            # As in a reconciler wake after a worker restart.
            await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
        assert run.output["structured"]["result"] == ["approved", "rejected"]

    async def test_retry_reuses_an_approved_action_instead_of_repeating_it(
        self, engine: AsyncEngine
    ):
        step = _node(
            "code.python.actions",
            {
                "actions": {"review": {"type": "human.approval", "config": {"title": "Check?"}}},
                "code": "review(details='item')\n1 / 0",
            },
        )
        seeded = await seed_run(engine, _chain(step))
        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value
        async with seeded.factory() as db:
            request = (
                await db.scalars(
                    select(WorkflowApproval).where(
                        WorkflowApproval.workflow_run_id == seeded.run.id
                    )
                )
            ).one()
            await WorkflowApprovalService(db).decide(seeded.ctx, request.id, approved=True)
            await db.commit()
            discard_deferred(db)
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        assert await _failed_code(seeded) == "PYTHON_ERROR"
        async with seeded.factory() as db:
            retry = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            retry_row = await db.get(WorkflowRun, retry.id)
            assert retry_row is not None
        assert await _failed_code(replace(seeded, run=retry_row)) == "PYTHON_ERROR"
        async with seeded.factory() as db:
            assert not (
                await db.scalars(
                    select(WorkflowApproval).where(WorkflowApproval.workflow_run_id == retry.id)
                )
            ).all()

        # Failed retries are retryable again. Removing their source before
        # the retry itself expires would silently turn old writes into new ones.
        async with seeded.factory() as db:
            workflow = await db.get(Workflow, seeded.run.workflow_id)
            assert workflow is not None
            workflow.settings = {"run_retention_days": 1}
            now = datetime.now(UTC)
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == seeded.run.id)
                .values(ended_at=now - timedelta(days=3))
            )
            await db.commit()
            assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []

    @pytest.mark.parametrize("approved", [True, False])
    async def test_a_rejected_mcp_write_can_reask_but_a_sent_write_needs_attention(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, approved: bool
    ):
        connection_id = uuid.uuid4()
        step = _node(
            "code.python.actions",
            {
                "actions": {
                    "create_ticket": {
                        "type": "mcp.call",
                        "config": {
                            "connection_id": str(connection_id),
                            "tool": "create",
                            "approval": "all",
                        },
                    }
                },
                "code": "create_ticket(arguments={'title': 'Investigate'})",
            },
        )
        seeded = await seed_run(engine, _chain(step))
        async with seeded.factory() as db:
            db.add(
                McpConnection(
                    id=connection_id,
                    organization_id=seeded.org.id,
                    scope="org",
                    name="tickets",
                    url="https://tickets.example.test/mcp",
                    last_tools=[{"name": "create"}],
                    allowed_tools=["create"],
                )
            )
            await db.commit()
        # Only the external transport is simulated. The connection, request,
        # approval decision, attempt and needs-attention state are real DB rows.
        session = AsyncMock()
        session.call_tool.side_effect = TimeoutError()
        transport = MagicMock()
        transport.return_value.__aenter__.return_value = session
        monkeypatch.setattr(mcp_node, "mcp_session", transport)
        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value
        session.call_tool.assert_not_awaited()
        async with seeded.factory() as db:
            request = (
                await db.scalars(
                    select(WorkflowApproval).where(
                        WorkflowApproval.workflow_run_id == seeded.run.id
                    )
                )
            ).one()
            await WorkflowApprovalService(db).decide(seeded.ctx, request.id, approved=approved)
            await db.commit()
            discard_deferred(db)
        await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
        if not approved:
            original = await drive(seeded)
            assert original.status == WorkflowRunStatus.FAILED.value
            assert original.error["code"] == "MCP_CALL_REJECTED"
            # An old, unmarked approval wait must not count as a no-send proof;
            # an unrelated timer is not the MCP gate even if it carries the flag.
            async with seeded.factory() as db:
                parked = await db.scalar(
                    select(NodeAttempt).where(
                        NodeAttempt.node_run_id == request.node_run_id,
                        NodeAttempt.attempt_no == 1,
                    )
                )
                assert parked is not None and parked.result is not None
                envelope = parked.result
                assert not await workflow_run_repo.may_have_dispatched(
                    db, node_run_id=request.node_run_id
                )
                for unproven in (
                    {key: value for key, value in envelope.items() if key != "effect_not_started"},
                    {**envelope, "reason": "timer"},
                ):
                    parked.result = unproven
                    await db.flush()
                    assert await workflow_run_repo.may_have_dispatched(
                        db, node_run_id=request.node_run_id
                    )
                await db.rollback()
            async with seeded.factory() as db:
                retried = await WorkflowExecutionService(db).retry(seeded.ctx, original.id)
                await db.commit()
                row = await db.get(WorkflowRun, retried.id)
                assert row is not None
            assert (
                await drive(replace(seeded, run=row))
            ).status == WorkflowRunStatus.WAITING_APPROVAL.value
            session.call_tool.assert_not_awaited()
            async with seeded.factory() as db:
                fresh = await db.scalar(
                    select(WorkflowApproval).where(WorkflowApproval.workflow_run_id == retried.id)
                )
                assert fresh is not None and fresh.id != request.id and fresh.status == "pending"
            return
        assert (await drive(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value
        assert (await drive(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value
        session.call_tool.assert_awaited_once_with("create", {"title": "Investigate"})

    async def test_a_failed_child_fails_the_parent_with_the_native_error(self, engine: AsyncEngine):
        step = _node(
            "code.python.actions",
            {
                "actions": {
                    "reject": {
                        "type": "error.raise",
                        "config": {"code": "CASE_CLOSED", "message": "Already closed"},
                    }
                },
                "code": "reject()",
            },
        )
        seeded = await seed_run(engine, _chain(step))
        assert await _failed_code(seeded) == "CASE_CLOSED"
        async with seeded.factory() as db:
            rows = (
                await db.scalars(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == seeded.run.id,
                        NodeRun.node_instance_id == step.id,
                    )
                )
            ).all()
            assert len(rows) == 2 and all(row.status == "failed" for row in rows)

    @pytest.mark.parametrize(
        "bad_args", [False, True], ids=["exhausted-transient", "invalid-kwargs"]
    )
    async def test_error_handler_routes_the_original_child_failure(
        self, engine: AsyncEngine, bad_args: bool
    ):
        code = "INVALID_BINDING" if bad_args else "TRANSIENT"
        action = (
            {"type": "text.compare"}
            if bad_args
            else {
                "type": "error.raise",
                "config": {"code": code, "message": "Try again", "retryable": True},
            }
        )
        step = _node(
            "code.python.actions",
            {
                "actions": {"do_work": action},
                "code": "do_work(a='missing b')" if bad_args else "do_work()",
            },
        ).model_copy(
            update={"policy": NodePolicy(retry=RetryPolicy(max_attempts=2), on_error="route")}
        )
        entry, normal, matched, fallback = (
            _node("core.input"),
            _node("debug.echo"),
            _node("debug.echo"),
            _node("debug.echo"),
        )
        handler = _node(
            "error.handle",
            {"branches": [{"name": "matched", "code": code, "retryable": not bad_args}]},
        )
        graph = WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, step, normal, handler, matched, fallback),
            edges=(
                _edge(entry, step),
                _edge(step, normal),
                _edge(step, handler, "error"),
                _edge(handler, matched, "matched"),
                _edge(handler, fallback, "default"),
            ),
        )
        seeded = await seed_run(engine, graph)
        finished = await drive(seeded)
        if not bad_args:
            assert finished.status == WorkflowRunStatus.WAITING_RETRY.value
            await _due_now(seeded)
            finished = await drive(seeded)
        assert finished.status == WorkflowRunStatus.SUCCEEDED.value, finished.error
        async with seeded.factory() as db:
            rows = await workflow_run_repo.list_node_runs_at(
                db, workflow_run_id=finished.id, scope_path=[]
            )
            by_id = {row.node_instance_id: row for row in rows}
            assert by_id[matched.id].status == "succeeded"
            assert by_id[fallback.id].status == by_id[normal.id].status == "skipped"
            attempts = await workflow_run_repo.list_attempts_of(
                db, node_run_ids=[by_id[step.id].id]
            )
            assert len(attempts) == 2  # One pause, one forwarded failure, no parent retry.
            error = attempts[-1].result["error"]
            assert error["code"] == code and error["retryable"] is (not bad_args)

    @pytest.mark.parametrize("limit", [5, 7])
    async def test_graph_rows_and_script_calls_share_the_run_ceiling(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, limit: int
    ) -> None:
        monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_NODE_RUNS", limit)
        entry, loop, out = _node("core.input"), _node("control.foreach"), _node("core.output")
        item, script, yielded = (
            node.model_copy(update={"scope_id": loop.id})
            for node in (
                _node("loop.item"),
                _node(
                    "code.python.actions",
                    {"code": "echo(message='hello')", "actions": {"echo": {"type": "debug.echo"}}},
                ),
                _node("loop.yield"),
            )
        )
        graph = WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, loop, item, script, yielded, out),
            edges=(
                _edge(entry, loop),
                _edge(loop, out, "done"),
                _edge(item, script),
                _edge(script, yielded),
            ),
            bindings=(
                _literal(loop, "items", ["one"]),
                _literal(yielded, "value", "done"),
                Binding(
                    target_node_id=out.id,
                    target_field="structured",
                    source=NodeOutputRef(node_id=loop.id, port="done"),
                ),
            ),
        )
        seeded = await seed_run(engine, graph)

        finished = await drive(seeded)

        async with seeded.factory() as db:
            assert await workflow_run_repo.count_node_runs(db, workflow_run_id=finished.id) == limit
            script_rows = await workflow_run_repo.list_node_runs_of(
                db, workflow_run_id=finished.id, node_instance_ids=[script.id]
            )
        assert len(script_rows) == 2  # The Python step and its action both completed.
        assert all(row.status == "succeeded" for row in script_rows)
        if limit == 5:
            assert finished.status == WorkflowRunStatus.FAILED.value
            assert finished.error is not None and finished.error["code"] == "NODE_RUN_LIMIT"
        else:
            assert finished.status == WorkflowRunStatus.SUCCEEDED.value

    async def test_foreach_collects_bad_action_arguments_and_continues(self, engine: AsyncEngine):
        entry, loop, out = (
            _node("core.input"),
            _node("control.foreach", {"item_error_policy": "collect"}),
            _node("core.output"),
        )
        item, script, yielded = (
            node.model_copy(update={"scope_id": loop.id})
            for node in (
                _node("loop.item"),
                _node(
                    "code.python.actions",
                    {
                        "code": "echo(message=args['message'])['echoed']",
                        "actions": {"echo": {"type": "debug.echo"}},
                    },
                ),
                _node("loop.yield"),
            )
        )
        graph = WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, loop, item, script, yielded, out),
            edges=(
                _edge(entry, loop),
                _edge(loop, out, "done"),
                _edge(item, script),
                _edge(script, yielded),
            ),
            bindings=(
                _literal(loop, "items", [{"message": {}}, {"message": "next"}]),
                Binding(
                    target_node_id=script.id,
                    target_field="args",
                    source=NodeOutputRef(node_id=item.id, port="out", field_path=("item",)),
                ),
                Binding(
                    target_node_id=yielded.id,
                    target_field="value",
                    source=NodeOutputRef(node_id=script.id, port="out", field_path=("result",)),
                ),
                Binding(
                    target_node_id=out.id,
                    target_field="structured",
                    source=NodeOutputRef(node_id=loop.id, port="done"),
                ),
            ),
        )
        finished = await drive(await seed_run(engine, graph))
        assert finished.status == WorkflowRunStatus.SUCCEEDED.value, finished.error
        output = finished.output["structured"]
        assert output["results"] == [None, "next"]
        assert [(err["index"], err["code"]) for err in output["errors"]] == [(0, "INVALID_BINDING")]


class TestScriptCursorStorage:
    async def _checkpoint(
        self, engine: AsyncEngine, *, retries: int = 3, sibling: NodeInstance | None = None
    ) -> tuple[SeededRun, NodeRun, NodeRun]:
        """Leave the script parked; its first child is ready but hasn't executed."""
        script = _node(
            "code.python.actions",
            {
                "actions": {"echo": {"type": "debug.echo"}},
                "code": "pad = 'x' * 16000\necho(message='ready')\nlen(pad)",
            },
        ).model_copy(update={"policy": NodePolicy(retry=RetryPolicy(max_attempts=retries))})
        graph = _chain(script)
        if sibling is not None:
            graph = graph.model_copy(
                update={
                    "nodes": (*graph.nodes, sibling),
                    "edges": (*graph.edges, _edge(graph.node_by_id[graph.entry_node_id], sibling)),
                }
            )
        seeded = await seed_run(engine, graph)
        async with seeded.factory() as db:
            entry = await workflow_run_repo.get_node_run_by_identity(
                db,
                workflow_run_id=seeded.run.id,
                node_instance_id=graph.entry_node_id,
                scope_path=[],
            )
        assert entry is not None
        await tick(seeded, entry.id)
        async with seeded.factory() as db:
            parent = await workflow_run_repo.get_node_run_by_identity(
                db, workflow_run_id=seeded.run.id, node_instance_id=script.id, scope_path=[]
            )
        assert parent is not None
        await tick(seeded, parent.id)
        async with seeded.factory() as db:
            rows = await workflow_run_repo.list_node_runs_of(
                db, workflow_run_id=seeded.run.id, node_instance_ids=[script.id]
            )
        parent, child = sorted(rows, key=lambda row: len(row.scope_path))
        assert parent.resume_payload is not None and child.scope_path[-1]["action"] == "echo"
        return seeded, parent, child

    @pytest.mark.parametrize("scope", ["run", "organization"])
    @pytest.mark.parametrize("result_kind", ["success", "last_failure"])
    async def test_final_result_uses_the_space_freed_by_its_cursor(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, scope: str, result_kind: str
    ):
        seeded, parent, child = await self._checkpoint(engine, retries=1)
        await tick(seeded, child.id)
        before = (await run_row(seeded)).inline_result_bytes
        cursor = json_byte_size(parent.resume_payload, limit=2**63 - 1)
        begun, outcome = await begin(seeded, parent.id)
        assert isinstance(outcome.result, Completed)
        if result_kind == "last_failure":
            outcome = dispatcher.HandlerOutcome(
                result=Failed(
                    error=WorkflowError(code="TRANSIENT", message="Exhausted", retryable=True)
                )
            )
        serialized = outcome.result.model_dump(mode="json")
        size = json_byte_size(serialized, limit=2**63 - 1)
        if isinstance(outcome.result, Failed):
            size += json_byte_size(serialized["error"], limit=2**63 - 1)
        expected = before - cursor + size
        # Every byte of headroom is in the cursor, not in the earlier attempt records.
        monkeypatch.setattr(
            settings,
            "WORKFLOW_RUN_MAX_INLINE_RESULT_BYTES"
            if scope == "run"
            else "WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES",
            max(expected, before),
        )
        await settle(seeded, begun, outcome)
        async with seeded.factory() as db:
            stored = await db.get(NodeRun, parent.id)
            assert stored is not None and stored.resume_payload is None
            assert stored.status == ("succeeded" if result_kind == "success" else "failed")
            latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=parent.id)
            assert latest.result == serialized
            assert await workflow_run_repo.inline_result_bytes(db, seeded.org.id) == expected
        assert (await run_row(seeded)).inline_result_bytes == expected

    async def test_a_final_child_failure_replaces_the_vm_before_reserving_its_error(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ):
        seeded, parent, child = await self._checkpoint(engine, retries=1)
        used = (await run_row(seeded)).inline_result_bytes
        monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_INLINE_RESULT_BYTES", used)
        begun, _ = await begin(seeded, child.id)
        failure = WorkflowError(code="REFUSED", message="Cannot perform action")
        await settle(seeded, begun, dispatcher.HandlerOutcome(result=Failed(error=failure)))
        async with seeded.factory() as db:
            waiting = await db.get(NodeRun, parent.id)
            assert waiting.resume_payload == {"child_error": failure.model_dump(mode="json")}
        assert await _failed_code(seeded) == "REFUSED"
        async with seeded.factory() as db:
            ended = await db.get(NodeRun, parent.id)
            assert ended.resume_payload is None

    async def test_a_retry_keeps_the_cursor_until_it_is_consumed(self, engine: AsyncEngine):
        seeded, parent, child = await self._checkpoint(engine, retries=2)
        await tick(seeded, child.id)
        begun, _ = await begin(seeded, parent.id)
        await settle(
            seeded,
            begun,
            dispatcher.HandlerOutcome(
                result=Failed(
                    error=WorkflowError(code="TRANSIENT", message="Try again", retryable=True)
                )
            ),
        )
        async with seeded.factory() as db:
            stored = await db.get(NodeRun, parent.id)
            assert stored.status == "waiting" and stored.resume_payload == parent.resume_payload
        await _due_now(seeded)
        ended = await drive(seeded)
        assert ended.output["structured"]["result"] == 16000
        async with seeded.factory() as db:
            stored = await db.get(NodeRun, parent.id)
            assert stored.resume_payload is None

    @pytest.mark.parametrize("finish", ["cancel", "deadline"])
    async def test_terminal_cleanup_releases_only_the_private_cursor(
        self, engine: AsyncEngine, finish: str
    ):
        wait = _node("flow.wait", {"until_called": True})
        seeded, parent, child = await self._checkpoint(engine, sibling=wait)
        # Public callback payloads may even match the script envelope exactly.
        async with seeded.factory() as db:
            other = await workflow_run_repo.get_node_run_by_identity(
                db, workflow_run_id=seeded.run.id, node_instance_id=wait.id, scope_path=[]
            )
        assert other is not None
        await tick(seeded, other.id)
        async with seeded.factory() as db:
            await WorkflowResumeService(db).resume(
                seeded.run.id,
                resume_token(seeded.run.id),
                body=json.dumps(parent.resume_payload).encode(),
            )
            await db.commit()
        cursor = json_byte_size(parent.resume_payload, limit=2**63 - 1)
        before = (await run_row(seeded)).inline_result_bytes
        if finish == "cancel":
            async with seeded.factory() as db:
                await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
                await db.commit()
        else:
            # The child is already committed but the parent cannot dispatch again.
            await tick(seeded, child.id)
            before = (await run_row(seeded)).inline_result_bytes
            async with seeded.factory() as db:
                run = await db.get(WorkflowRun, seeded.run.id)
                await workflow_run_repo.update_run(
                    db,
                    run=run,
                    update_data={"deadline_at": datetime.now(UTC) - timedelta(seconds=1)},
                )
                await db.commit()
            await tick(seeded, parent.id)
        async with seeded.factory() as db:
            run = await db.get(WorkflowRun, seeded.run.id)
            cleared = await db.get(NodeRun, parent.id)
            kept = await db.get(NodeRun, other.id)
            assert cleared.resume_payload is None and kept.resume_payload == parent.resume_payload
            assert run.inline_result_bytes == before - cursor

    async def test_a_late_completion_does_not_charge_the_cursor_twice(self, engine: AsyncEngine):
        seeded, parent, child = await self._checkpoint(engine)
        await tick(seeded, child.id)
        before = (await run_row(seeded)).inline_result_bytes
        cursor = json_byte_size(parent.resume_payload, limit=2**63 - 1)
        begun, done = await begin(seeded, parent.id)
        async with seeded.factory() as db:
            await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
            await db.commit()
        assert (await run_row(seeded)).inline_result_bytes == before - cursor
        await settle(seeded, begun, done)
        await settle(seeded, begun, done)
        size = json_byte_size(done.result.model_dump(mode="json"), limit=2**63 - 1)
        assert (await run_row(seeded)).inline_result_bytes == before - cursor + size


class _Session:
    """One `sandboxd` session, in memory: files, and a job that runs when told to."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.launches = 0
        self.stopped = False
        self.fail_write = False
        self.exec_exit = 0
        # What the job's files measure as, when a test wants them to look smaller
        # than they are - a file still growing after it was measured.
        self.measured_as: str | None = None
        self.reads: list[str] = []
        self.commands: list[str] = []

    # The `_Sandbox` surface the step uses.
    async def exists(self, path: str) -> bool:
        return path in self.files

    async def write(self, path: str, content: str | bytes) -> None:
        if self.fail_write:
            raise WorkspaceError("disk full")
        self.files[path] = content.encode() if isinstance(content, str) else content

    async def shell(self, command: str) -> tuple[int, str]:
        self.commands.append(command)
        if self.exec_exit:
            return self.exec_exit, "boom"
        if "wc -c" in command:
            return 0, self._measured()
        if f"{job.ROOT}/job.pid" not in self.files:
            self.launches += 1
            self.files[f"{job.ROOT}/job.pid"] = b"42"
        return 0, ""

    async def close(self) -> None:
        pass

    async def read_bytes(self, path: str, *, max_bytes: int = job.MAX_OUTPUT_BYTES) -> bytes:
        self.reads.append(path)
        data = self.files[path]
        if len(data) > max_bytes:
            raise job._TooLarge
        return data

    def _measured(self) -> str:
        if self.measured_as is not None:
            return self.measured_as
        root = job.ROOT
        outputs = [data for path, data in self.files.items() if path.startswith(f"{root}/outputs/")]
        size = {
            name: len(self.files.get(f"{root}/{name}", b"")) for name in ("result.json", "log.txt")
        }
        return (
            f"{len(outputs)}\n{sum(map(len, outputs))}\n{size['result.json']}\n{size['log.txt']}\n"
        )

    async def list_dir(self, path: str) -> list[FileEntry]:
        prefix = path.rstrip("/") + "/"
        found = [p for p in self.files if p.startswith(prefix)]
        entries = [
            FileEntry(name=p.rsplit("/", 1)[-1], path=p, is_dir=False, size=len(self.files[p]))
            for p in found
        ]
        return [*entries, FileEntry(name="sub", path=prefix + "sub", is_dir=True, size=None)]

    async def purge(self) -> None:
        self.stopped = True

    def finish(
        self,
        answer: dict[str, Any],
        *,
        log: bytes = b"done\n",
        outputs: dict[str, bytes] | None = None,
    ) -> None:
        """What the runner leaves behind when the script ends."""
        root = job.ROOT
        self.files[f"{root}/result.json"] = json.dumps(answer).encode()
        self.files[f"{root}/log.txt"] = log
        for name, data in (outputs or {}).items():
            self.files[f"{root}/outputs/{name}"] = data
        self.files[f"{root}/done"] = b"done"


@pytest.fixture
def host() -> Iterator[dict[str, _Session]]:
    """Sessions by key - one per step, however many dispatches open it."""
    sessions: dict[str, _Session] = {}

    def open_session(_resolved: Any, key: str, _runtime: Any, _tenant: str) -> _Session:
        return sessions.setdefault(key, _Session())

    resolved = SimpleNamespace(kind="docker")
    with (
        patch.object(job, "_open", side_effect=open_session),
        patch.object(job, "_connection", new=AsyncMock(return_value=resolved)),
    ):
        yield sessions


async def _due_now(seeded: SeededRun) -> None:
    """Bring the step's next check forward, as the backoff passing would."""
    async with seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(DispatchOutbox.workflow_run_id == seeded.run.id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


def _sandbox_step(**config: Any) -> NodeInstance:
    return _node("code.python.sandbox", {"code": "result = 1", **config})


class TestTheSandboxJob:
    async def test_it_launches_once_is_checked_on_and_imports_what_the_job_made(self, engine, host):
        step = _sandbox_step()
        seeded = await seed_run(engine, _chain(step, _literal(step, "args", {"n": 2})))

        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        (session,) = host.values()
        assert session.launches == 1
        assert json.loads(session.files[f"{job.ROOT}/args.json"]) == {"n": 2}

        await _due_now(seeded)
        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value
        assert session.launches == 1

        session.finish({"ok": True, "result": {"rows": 3}}, outputs={"report.csv": b"a,b\n1,2\n"})
        await _due_now(seeded)
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        answer = run.output["structured"]
        assert answer["result"] == {"rows": 3} and answer["stdout_tail"] == "done\n"
        (produced,) = answer["output_files"]
        async with seeded.factory() as db:
            names = sorted(
                row.filename for row in (await db.execute(select(WorkflowFile))).scalars().all()
            )
        assert names == ["log.txt", "report.csv"]
        assert produced["content_type"] == "text/plain"
        assert session.stopped is True and len(host) == 1

    async def test_a_launch_cut_short_before_it_started_is_completed_not_waited_on(
        self, engine, host
    ):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        key = job.session_key(f"{seeded.org.id}:{seeded.run.id}:{seeded.graph.nodes[1].id}:[]")
        # A worker that staged the script and died before starting it.
        half = host.setdefault(key, _Session())
        half.files[f"{job.ROOT}/main.py"] = b"result = 1"

        await drive(seeded)

        assert half.launches == 1 and len(host) == 1

    async def test_a_job_past_its_time_is_stopped(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step(timeout_seconds=60)))
        await drive(seeded)
        (session,) = host.values()
        session.files[f"{job.ROOT}/started_at"] = (
            (datetime.now(UTC) - timedelta(minutes=5)).isoformat().encode()
        )
        await _due_now(seeded)
        assert await _failed_code(seeded) == "PYTHON_SANDBOX_TIMEOUT"
        assert session.stopped is True

    @pytest.mark.parametrize(
        ("answer", "code"),
        [
            ({"ok": False, "error": "ZeroDivisionError: division by zero"}, "PYTHON_ERROR"),
            ({"ok": False, "not_json": True, "error": "set"}, "PYTHON_OUTPUT_NOT_JSON"),
        ],
        ids=["an-exception", "not-json"],
    )
    async def test_a_script_that_failed_fails_the_step_with_its_log_kept(
        self, engine, host, answer, code
    ):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish(answer)
        await _due_now(seeded)
        assert await _failed_code(seeded) == code
        async with seeded.factory() as db:
            (log,) = (await db.execute(select(WorkflowFile))).scalars().all()
        assert log.filename == "log.txt"

    async def test_a_job_that_wrote_too_much_imports_nothing(self, engine, host, monkeypatch):
        monkeypatch.setattr(job, "MAX_OUTPUT_FILES", 1)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, outputs={"a": b"1", "b": b"2"})
        await _due_now(seeded)
        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        async with seeded.factory() as db:
            assert (await db.execute(select(WorkflowFile))).scalars().all() == []

    async def test_leftovers_over_the_bounds_are_refused_before_any_is_fetched(
        self, engine, host, monkeypatch
    ):
        monkeypatch.setattr(job, "MAX_LOG_BYTES", 4)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, log=b"far too chatty")
        await _due_now(seeded)

        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        assert session.reads == [] and session.stopped is True

    async def test_a_file_that_grew_after_it_was_measured_is_still_refused(
        self, engine, host, monkeypatch
    ):
        monkeypatch.setattr(job, "MAX_OUTPUT_BYTES", 8)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, outputs={"big.bin": b"x" * 64})
        session.measured_as = "1\n0\n0\n0\n"
        await _due_now(seeded)

        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        async with seeded.factory() as db:
            assert (await db.execute(select(WorkflowFile))).scalars().all() == []

    async def test_leftovers_that_cannot_be_measured_are_checked_again_later(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None})
        session.measured_as = "not a number"
        await _due_now(seeded)

        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        assert session.reads == [] and session.stopped is False

    async def test_a_job_with_no_log_answers_with_an_empty_one(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": 7})
        del session.files[f"{job.ROOT}/log.txt"]
        await _due_now(seeded)
        run = await drive(seeded)
        assert run.output["structured"]["stdout_tail"] == ""

    async def test_a_host_that_cannot_stage_or_start_is_retried(self, engine, host):
        for failure in ("write", "exec"):
            host.clear()
            seeded = await seed_run(engine, _chain(_sandbox_step()))
            session = host.setdefault(
                job.session_key(f"{seeded.org.id}:{seeded.run.id}:{seeded.graph.nodes[1].id}:[]"),
                _Session(),
            )
            session.fail_write = failure == "write"
            session.exec_exit = 1 if failure == "exec" else 0
            run = await drive(seeded)
            assert run.status == WorkflowRunStatus.WAITING_RETRY.value
            assert session.launches == 0

    async def test_the_run_s_input_files_are_staged_by_name(self, engine, host, storage):
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        ref = await _stored(engine, storage, earlier.run, b"a,b\n", "text/csv", "leads.csv")
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[ref.model_dump(mode="json")]),
                ),
            ),
            member=member,
        )
        await _import(seeded, ref)
        await drive(seeded)
        (session,) = host.values()
        assert session.files[f"{job.ROOT}/inputs/00-leads.csv"] == b"a,b\n"

    @pytest.mark.security
    async def test_a_file_the_run_was_not_given_is_never_staged(self, engine, host, storage):
        other = await seed_run(engine, _chain(_node("debug.echo")))
        ref = await _stored(engine, storage, other.run, b"secret", "text/plain", "x.txt")
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[ref.model_dump(mode="json")]),
                ),
            ),
        )
        assert await _failed_code(seeded) == "FILE_NOT_FOUND"
        (session,) = host.values()
        assert session.launches == 0

    async def test_inputs_over_the_limit_are_refused(self, engine, host, storage, monkeypatch):
        monkeypatch.setattr(job, "MAX_INPUT_BYTES", 5)
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        refs = [
            await _stored(engine, storage, earlier.run, b"1234", "text/plain", None)
            for _ in range(2)
        ]
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[r.model_dump(mode="json") for r in refs]),
                ),
            ),
            member=member,
        )
        for ref in refs:
            await _import(seeded, ref)
        assert await _failed_code(seeded) == "FILE_TOO_LARGE"


class TestTheSandboxHost:
    async def test_a_host_that_is_not_there_is_retried(self, engine):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        resolved = SimpleNamespace(kind="docker")

        def unreachable(*_args: Any) -> Any:
            raise RuntimeError("Could not reach the sandbox service")

        with (
            patch.object(job, "_connection", new=AsyncMock(return_value=resolved)),
            patch.object(job, "_open", side_effect=unreachable),
        ):
            run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value

    async def test_no_usable_connection_or_the_wrong_kind_fails_clearly(self, engine):
        for connection, code in [
            (
                AsyncMock(side_effect=BadRequestError(message="No sandbox connection")),
                "SANDBOX_UNAVAILABLE",
            ),
            (AsyncMock(return_value=SimpleNamespace(kind="daytona")), "SANDBOX_UNAVAILABLE"),
        ]:
            seeded = await seed_run(engine, _chain(_sandbox_step()))
            with patch.object(job, "_connection", new=connection):
                assert await _failed_code(seeded) == code

    async def test_the_real_connection_is_resolved_for_the_run_s_member(self, engine):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        assert await _failed_code(seeded) == "SANDBOX_UNAVAILABLE"

    async def test_publishing_checks_the_author_s_connection(self, engine):
        member = await _member(engine)
        seeded = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        config = sandbox_node.PythonSandboxConfig(code="result = 1")
        async with async_sessionmaker(engine)() as db:
            (problem,) = await sandbox_node.check_resources(db, seeded.ctx, config)
            assert problem[0] == "connection_id"
            assert await sandbox_node.check_resources(db, seeded.ctx, MagicMock()) == []
            with patch.object(
                job.SandboxConnectionService,
                "resolve",
                new=AsyncMock(return_value=SimpleNamespace(kind="daytona")),
            ):
                (wrong,) = await sandbox_node.check_resources(db, seeded.ctx, config)
                assert "sandboxd" in wrong[1]
            with patch.object(
                job.SandboxConnectionService,
                "resolve",
                new=AsyncMock(return_value=SimpleNamespace(kind="docker")),
            ):
                assert await sandbox_node.check_resources(db, seeded.ctx, config) == []

    async def test_a_session_is_opened_on_the_connection_s_address_and_runtime(self):
        resolved = SimpleNamespace(
            token="t",
            row=SimpleNamespace(id="c1", base_url="http://sandboxd:8080", default_runtime="py"),
        )
        with patch("pydantic_ai_backends.workspaces.SandboxdWorkspace") as sandboxd:
            opened = job._open(resolved, "wf-key", None, "org")
            await opened.close()
        assert sandboxd.call_args.kwargs["session_name"] == "wf-key"
        assert sandboxd.call_args.kwargs["runtime"] == "py"
        assert sandboxd.call_args.kwargs["provider"] == "sandboxd:c1"
        assert sandboxd.call_args.kwargs["tenant"] == "org"

    async def test_a_step_with_no_script_says_so(self):
        result = await sandbox_node.handle(None, None)
        assert result.error.code == "PYTHON_NOT_CONFIGURED"


def _js_step(**config: Any) -> NodeInstance:
    return _node("code.javascript.sandbox", {"code": "return args.n * 2;", **config})


class TestTheJavaScriptJob:
    """The same job protocol, run by Node: what differs is what is staged and started."""

    async def test_it_stages_a_node_runner_and_answers_with_what_the_script_returned(
        self, engine, host
    ):
        step = _js_step()
        seeded = await seed_run(engine, _chain(step, _literal(step, "args", {"n": 2})))

        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value
        (session,) = host.values()
        assert session.files[f"{job.ROOT}/main.js"] == b"return args.n * 2;"
        assert session.files[f"{job.ROOT}/run.js"] == js_node.RUNNER.encode()
        assert any("nohup node run.js" in command for command in session.commands)

        session.finish({"ok": True, "result": 4}, log=b"logged\n")
        await _due_now(seeded)
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        answer = run.output["structured"]
        assert answer["result"] == 4 and answer["stdout_tail"] == "logged\n"

    @pytest.mark.parametrize(
        ("answer", "code"),
        [
            ({"ok": False, "error": "TypeError: bad"}, "JAVASCRIPT_ERROR"),
            ({"ok": False, "not_json": True, "error": "bigint"}, "JAVASCRIPT_OUTPUT_NOT_JSON"),
        ],
        ids=["a-throw", "not-json"],
    )
    async def test_a_script_that_failed_fails_with_its_own_code(self, engine, host, answer, code):
        seeded = await seed_run(engine, _chain(_js_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish(answer)
        await _due_now(seeded)
        assert await _failed_code(seeded) == code

    async def test_a_job_past_its_time_says_it_was_javascript(self, engine, host):
        seeded = await seed_run(engine, _chain(_js_step(timeout_seconds=60)))
        await drive(seeded)
        (session,) = host.values()
        session.files[f"{job.ROOT}/started_at"] = (
            (datetime.now(UTC) - timedelta(minutes=5)).isoformat().encode()
        )
        await _due_now(seeded)
        assert await _failed_code(seeded) == "JAVASCRIPT_SANDBOX_TIMEOUT"

    async def test_a_job_over_its_bounds_says_it_was_javascript(self, engine, host, monkeypatch):
        monkeypatch.setattr(job, "MAX_OUTPUT_FILES", 0)
        seeded = await seed_run(engine, _chain(_js_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": 1}, outputs={"a.txt": b"a"})
        await _due_now(seeded)
        assert await _failed_code(seeded) == "JAVASCRIPT_OUTPUT_TOO_LARGE"

    async def test_publishing_checks_the_author_s_connection_and_needs_a_script(self, engine):
        member = await _member(engine)
        seeded = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        config = js_node.JavaScriptSandboxConfig(code="return 1;")
        async with async_sessionmaker(engine)() as db:
            (problem,) = await js_node.check_resources(db, seeded.ctx, config)
            assert problem[0] == "connection_id"
            assert await js_node.check_resources(db, seeded.ctx, MagicMock()) == []
        result = await js_node.handle(None, None)
        assert result.error.code == "JAVASCRIPT_NOT_CONFIGURED"


def test_a_script_runs_on_the_kind_a_sandboxd_connection_is_registered_as():
    # Regression: the steps once asked for a kind "sandboxd" that no connection
    # can be registered as, so every real host was refused as unavailable.
    kinds = get_args(SandboxConnectionCreate.model_fields["kind"].annotation)
    assert job.SANDBOXD_KIND in kinds
    assert "daytona" in kinds and job.SANDBOXD_KIND != "daytona"


async def _member(engine: AsyncEngine):
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _stored(
    engine: AsyncEngine,
    storage: LocalFileStorage,
    run: WorkflowRun,
    data: bytes,
    content_type: str,
    filename: str | None,
) -> FileRef:
    file_id = uuid.uuid4()
    path = f"workflow-files/{run.organization_id}/{run.id}/{file_id}"
    await storage.save_at(path, data)
    async with async_sessionmaker(engine)() as db:
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                storage_path=path,
                content_type=content_type,
                byte_size=len(data),
                filename=filename,
            )
        )
        await db.commit()
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))


async def _import(seeded: SeededRun, ref: FileRef) -> None:
    async with seeded.factory() as db:
        db.add(
            ResourceRef(
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                kind="file",
                ref=ref.model_dump(mode="json"),
            )
        )
        await db.commit()


@pytest.mark.security
async def test_a_sandbox_output_quota_failure_removes_the_log_and_earlier_outputs(
    engine, host, monkeypatch
):
    monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_FILE_BYTES", 10)
    seeded = await seed_run(engine, _chain(_sandbox_step()))
    await drive(seeded)
    (session,) = host.values()
    session.finish(
        {"ok": True, "result": 1},
        log=b"log",
        outputs={"first.txt": b"first", "second.txt": b"last"},
    )
    await _due_now(seeded)
    ended = await drive(seeded)
    assert ended.status == WorkflowRunStatus.FAILED.value
    assert ended.error is not None and ended.error["code"] == "FILE_QUOTA_EXCEEDED"
    async with seeded.factory() as db:
        assert (
            await db.scalars(select(WorkflowFile).where(WorkflowFile.workflow_run_id == ended.id))
        ).all() == []
