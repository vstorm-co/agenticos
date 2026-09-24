"""`WorkflowExecutionService` against a real Postgres, and its routes over HTTP.

The facade unit tests mock the repository and the route tests mock the
service, so neither can see what the database does to a row between two
statements - and a start that answered 500 on every call shipped past both.
Everything here runs on a real session: the facade directly, and the routes
through the app with the real service behind them and a session that commits
the way `DBSession` does.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.main import app
from app.services.workflow_execution import WorkflowExecutionService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    """The direct trigger runs after a real commit here, and would otherwise
    reach for a Prefect deployment that does not exist in a test."""
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()) as submitted:
        yield submitted


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    await _member(db, org=org, user=owner, role="owner")
    return org


async def _member(db: AsyncSession, *, org: Organization, user: User, role: str) -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()


def _ctx(user: User, org: Organization, role: str = "owner") -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


def _echo_graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={"message": "hi"},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


async def _workflow(
    db: AsyncSession,
    *,
    org: Organization,
    owner: User,
    visibility: Visibility = Visibility.PRIVATE,
    published: bool = True,
) -> Workflow:
    graph = _echo_graph().model_dump(mode="json")
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Echo once",
        status=WorkflowStatus.PUBLISHED.value,
        visibility=visibility.value,
        draft_graph=graph,
    )
    db.add(workflow)
    await db.flush()
    if published:
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            organization_id=org.id,
            version=1,
            graph=graph,
        )
        db.add(version)
        await db.flush()
        workflow.current_version_id = version.id
        await db.flush()
    return workflow


class TestStartAndCancelOnARealSession:
    async def test_starting_a_run_answers_with_the_run_it_admitted(self, db: AsyncSession):
        """`_read` reads `updated_at` after the start's last event was
        appended - on a real session that attribute is expired by the flush,
        and reading it without a refresh raised `MissingGreenlet`."""
        owner = await _user(db)
        org = await _org(db, owner=owner)
        workflow = await _workflow(db, org=org, owner=owner)

        started = await WorkflowExecutionService(db).start(_ctx(owner, org), workflow.id)

        assert started.status == WorkflowRunStatus.RUNNING.value
        assert started.workflow_id == workflow.id
        assert started.updated_at is not None

    async def test_a_test_mode_start_answers_with_the_run_it_admitted(self, db: AsyncSession):
        owner = await _user(db)
        org = await _org(db, owner=owner)
        workflow = await _workflow(db, org=org, owner=owner, published=False)

        started = await WorkflowExecutionService(db).start(
            _ctx(owner, org), workflow.id, mode=WorkflowRunMode.TEST
        )

        assert started.mode == WorkflowRunMode.TEST.value
        assert started.workflow_version_id is None

    async def test_cancelling_a_run_answers_cancelled_and_closes_its_outbox(self, db: AsyncSession):
        owner = await _user(db)
        org = await _org(db, owner=owner)
        workflow = await _workflow(db, org=org, owner=owner)
        service = WorkflowExecutionService(db)
        started = await service.start(_ctx(owner, org), workflow.id)

        cancelled = await service.cancel(_ctx(owner, org), started.id)

        assert cancelled.status == WorkflowRunStatus.CANCELLED.value
        assert cancelled.ended_at is not None
        rows = (
            (
                await db.execute(
                    select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == started.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.status for row in rows] == [DispatchOutboxStatus.CANCELLED.value]


@pytest.fixture
async def http(engine: AsyncEngine, mock_redis: MagicMock):
    """The app with the real service behind it and a session that commits, as
    `DBSession` does. Yields the client, a one-item list holding whose context
    the next request uses, the org's owner and org, and a session factory for
    reading back what was committed."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await _user(setup)
        org = await _org(setup, owner=owner)
        await setup.commit()
    caller: list[AuthContext] = [_ctx(owner, org)]

    async def session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: caller[0]
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    async with open_client() as client:
        yield client, caller, owner, org, factory
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/workflow-runs{suffix}"


class TestRoutesWithTheRealService:
    async def test_start_then_cancel_over_http_commits_both(self, http):
        client, _caller, owner, org, factory = http
        async with factory() as setup:
            workflow = await _workflow(setup, org=org, owner=owner)
            await setup.commit()

        started = await client.post(_url(), json={"workflow_id": str(workflow.id)})
        assert started.status_code == 201, started.text
        run_id = started.json()["id"]

        cancelled = await client.post(_url(f"/{run_id}/cancel"))
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == WorkflowRunStatus.CANCELLED.value

        async with factory() as reader:
            run = (
                await reader.execute(select(WorkflowRun).where(WorkflowRun.id == uuid.UUID(run_id)))
            ).scalar_one()
        assert run.status == WorkflowRunStatus.CANCELLED.value
