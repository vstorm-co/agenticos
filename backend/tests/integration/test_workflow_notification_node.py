"""`notification.send` in a real run: who is told, and only once (#1789).

The notification center is the real one, writing real rows, so the dedup is
Postgres' own unique index and the recipient checks are the membership and
workflow-access rules every other surface uses.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRunStatus
from app.services.workflow_execution import context
from app.workflows.contracts.io import Binding, LiteralValue
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.notification_send import NotificationSendConfig, NotificationSendInput
from app.workflows.nodes.notification_send._handler import handle
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _graph(recipients: list[uuid.UUID]) -> tuple[WorkflowGraph, NodeInstance]:
    entry = _node("core.input")
    notify = _node(
        "notification.send",
        {
            "recipients": [str(r) for r in recipients],
            "subject": "Lead scored",
            "channels": ["in_app"],
        },
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, notify),
        edges=(
            Edge(
                id=uuid.uuid4(),
                source_node_id=entry.id,
                source_port="out",
                target_node_id=notify.id,
                target_port="in",
            ),
        ),
        bindings=(
            Binding(
                target_node_id=notify.id,
                target_field="message",
                source=LiteralValue(value="Acme scored 87."),
            ),
        ),
    )
    return graph, notify


async def _owner(engine: AsyncEngine) -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _colleague(engine: AsyncEngine, org: Organization, *, role: str) -> User:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role)
        )
        await db.commit()
    return user


async def _notifications(engine: AsyncEngine) -> list[Notification]:
    async with async_sessionmaker(engine)() as db:
        rows = await db.execute(
            select(Notification).where(
                Notification.event_type == NotificationEventType.WORKFLOW_NOTIFICATION.value
            )
        )
        return list(rows.scalars())


async def test_a_member_who_can_see_the_workflow_is_notified_with_the_bound_message(
    engine: AsyncEngine,
):
    owner = await _owner(engine)
    admin = await _colleague(engine, owner[1], role="admin")
    graph, _notify = _graph([admin.id])
    seeded = await seed_run(engine, graph, member=owner)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (row,) = await _notifications(engine)
    assert row.recipient_user_id == admin.id
    assert row.organization_id == owner[1].id
    assert row.summary == "Lead scored\n\nAcme scored 87."


@pytest.mark.security
async def test_a_member_who_cannot_see_the_workflow_is_dropped(engine: AsyncEngine):
    """A viewer cannot reach another member's private workflow, so it may not tell them."""
    owner = await _owner(engine)
    admin = await _colleague(engine, owner[1], role="admin")
    viewer = await _colleague(engine, owner[1], role="viewer")
    graph, _notify = _graph([viewer.id, admin.id])
    seeded = await seed_run(engine, graph, member=owner)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert [row.recipient_user_id for row in await _notifications(engine)] == [admin.id]


@pytest.mark.security
async def test_nobody_left_to_tell_fails_the_step_rather_than_claiming_success(
    engine: AsyncEngine,
):
    owner = await _owner(engine)
    viewer = await _colleague(engine, owner[1], role="viewer")
    graph, _notify = _graph([viewer.id])

    run = await drive(await seed_run(engine, graph, member=owner))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "NO_PERMITTED_RECIPIENTS"
    assert await _notifications(engine) == []


@pytest.mark.security
async def test_someone_outside_the_organization_cannot_be_named_at_publish(engine: AsyncEngine):
    owner = await _owner(engine)
    outsider, _their_org = await _owner(engine)
    graph, notify = _graph([outsider.id])
    seeded = await seed_run(engine, graph, member=owner)

    with pytest.raises(GraphValidationError) as refused:
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, seeded.ctx, graph)

    fields = {problem["field"] for problem in refused.value.details["fields"]}
    assert f"nodes.{notify.id}.config.recipients.0" in fields


async def test_a_retried_attempt_writes_no_second_notification(engine: AsyncEngine):
    """The same operation key twice: the notification center's own index makes it a no-op."""
    owner = await _owner(engine)
    admin = await _colleague(engine, owner[1], role="admin")
    graph, _notify = _graph([admin.id])
    seeded: SeededRun = await seed_run(engine, graph, member=owner)
    dispatch = context.DispatchContext(
        organization_id=owner[1].id,
        workflow_run_id=seeded.run.id,
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=owner[0].id, organization_id=owner[1].id, role="owner"),
        resumed_agent_run_id=None,
        workflow_id=seeded.run.workflow_id,
        idempotency_key=f"{owner[1].id}:{seeded.run.id}:step:[]",
    )
    config = NotificationSendConfig(recipients=(admin.id,), subject="Once")

    for _ in range(2):
        with context.dispatching_as(dispatch):
            await handle(config, NotificationSendInput())

    async with async_sessionmaker(engine)() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_user_id == admin.id)
        )
    assert count == 1
