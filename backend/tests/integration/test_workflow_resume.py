"""A Wait that goes on when the run's resume link is called, end to end (#1947)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.background import start_deferred
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.db.models.workflow_run import DispatchOutbox, NodeRun, NodeRunStatus
from app.services.workflow_execution.exceptions import (
    WorkflowNotWaitingError,
    WorkflowRunInputTooLargeError,
    WorkflowRunNotFoundError,
)
from app.services.workflow_execution.resume import WorkflowResumeService
from app.services.workflow_execution.resume_link import resume_token, resume_url
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import SeededRun, drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio


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


def _waiting_for_a_call(seconds: int = 3600) -> tuple[WorkflowGraph, NodeInstance, NodeInstance]:
    """The trigger, its resume link, a Wait for a call, and an output of both."""
    entry, link = _node("core.input"), _node("flow.resume_link")
    wait = _node("flow.wait", {"until_called": True, "seconds": seconds})
    out = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, link, wait, out),
        edges=(_edge(entry, link), _edge(link, wait), _edge(wait, out)),
        bindings=(
            Binding(
                target_node_id=out.id,
                target_field="structured",
                source=NodeOutputRef(node_id=wait.id, port="out"),
            ),
            Binding(
                target_node_id=out.id,
                target_field="text",
                source=NodeOutputRef(node_id=link.id, port="out", field_path=("url",)),
            ),
        ),
    )
    return graph, link, wait


async def _parked(engine: AsyncEngine, seconds: int = 3600) -> tuple[SeededRun, NodeInstance]:
    graph, _link, wait = _waiting_for_a_call(seconds)
    seeded = await seed_run(engine, graph)
    async with seeded.factory() as db:
        await validate_graph(db, seeded.ctx, graph)
    parked = await drive(seeded)
    assert parked.status == "running"
    assert (await node_statuses(seeded))[wait.id] == NodeRunStatus.WAITING.value
    return seeded, wait


async def _resume(seeded: SeededRun, body: bytes) -> int:
    async with seeded.factory() as db:
        resumed = await WorkflowResumeService(db).resume(
            seeded.run.id, resume_token(seeded.run.id), body=body
        )
        await db.commit()
        # What a request's session does after its commit: the dispatch it queued.
        start_deferred(db)
    return resumed.resumed


async def test_a_call_to_the_resume_link_hands_its_body_on_and_the_run_goes_on(
    engine: AsyncEngine,
):
    seeded, _wait = await _parked(engine)

    assert await _resume(seeded, json.dumps({"approved": True}).encode()) == 1
    finished = await drive(seeded)

    assert finished.status == "succeeded"
    assert finished.output["structured"]["called"] is True
    assert finished.output["structured"]["body"] == {"approved": True}
    # The link a Resume link step handed on is this run's.
    assert finished.output["text"] == resume_url(seeded.run.id)
    assert finished.output["text"].startswith(settings.PUBLIC_BASE_URL.rstrip("/"))


async def test_an_empty_call_resumes_with_an_empty_body(engine: AsyncEngine):
    seeded, _wait = await _parked(engine)

    await _resume(seeded, b"")
    finished = await drive(seeded)

    assert finished.output["structured"]["body"] == {}


async def test_a_wait_nobody_calls_goes_on_when_its_time_is_up(engine: AsyncEngine):
    seeded, wait = await _parked(engine, seconds=60)
    a_minute_ago = datetime.now(UTC) - timedelta(seconds=61)
    async with seeded.factory() as db:
        await db.execute(
            update(NodeRun)
            .where(NodeRun.workflow_run_id == seeded.run.id, NodeRun.node_instance_id == wait.id)
            .values(created_at=a_minute_ago)
        )
        await db.execute(
            update(DispatchOutbox)
            .where(DispatchOutbox.workflow_run_id == seeded.run.id)
            .values(available_at=a_minute_ago)
        )
        await db.commit()

    finished = await drive(seeded)

    assert finished.status == "succeeded"
    assert finished.output["structured"]["called"] is False
    assert finished.output["structured"]["body"] is None


@pytest.mark.security
async def test_a_link_that_is_not_the_runs_answers_as_if_there_were_no_run(engine: AsyncEngine):
    seeded, _wait = await _parked(engine)
    stranger = uuid.uuid4()

    for run_id, token in (
        (seeded.run.id, "0" * 64),
        (seeded.run.id, resume_token(stranger)),
        (stranger, resume_token(stranger)),
    ):
        async with seeded.factory() as db:
            with pytest.raises(WorkflowRunNotFoundError):
                await WorkflowResumeService(db).resume(run_id, token, body=b"{}")


async def test_a_run_resumed_once_waits_for_nothing_more(engine: AsyncEngine):
    seeded, _wait = await _parked(engine)
    await _resume(seeded, b"{}")

    with pytest.raises(WorkflowNotWaitingError):
        await _resume(seeded, b"{}")
    await drive(seeded)
    # Ended: nothing in it can wait again.
    with pytest.raises(WorkflowNotWaitingError):
        await _resume(seeded, b"{}")


async def test_a_body_that_is_not_one_json_object_or_is_too_large_is_refused(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    seeded, _wait = await _parked(engine)

    with pytest.raises(BadRequestError):
        await _resume(seeded, b"[1, 2]")
    monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_INPUT_BYTES", 8)
    with pytest.raises(WorkflowRunInputTooLargeError):
        await _resume(seeded, b'{"long": "enough to be over"}')
