"""Workflow run routes, through the app: the wire contract.

`tests/test_workflow_execution_facade.py` proves what the service does
against a mocked repository; what is left is the handler itself - status
codes, the error envelope, and which routes carry a `require(...)` gate
versus delegate to the service (the `permissions-rbac` skill).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import WorkflowStatus
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus
from app.main import app
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

FACADE_PATH = "app.services.workflow_execution.facade"


def _graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


def _workflow(**overrides: object):
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.organization_id = _ORGANIZATION_ID
    workflow.owner_user_id = uuid.uuid4()
    workflow.visibility = Visibility.PRIVATE.value
    workflow.status = WorkflowStatus.PUBLISHED.value
    workflow.current_version_id = uuid.uuid4()
    workflow.draft_graph = _graph().model_dump(mode="json")
    for field, value in overrides.items():
        setattr(workflow, field, value)
    return workflow


def _run_row(**overrides: object):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.workflow_id = uuid.uuid4()
    run.workflow_version_id = uuid.uuid4()
    run.mode = WorkflowRunMode.REAL.value
    run.status = WorkflowRunStatus.RUNNING.value
    run.triggered_by = "api"
    run.budget_limit = None
    run.spent_cost = Decimal("0")
    run.cost_is_partial = False
    run.deadline_at = None
    run.paused_reason = None
    run.error = None
    run.root_run_id = run.id
    run.causation_run_id = None
    run.depth = 0
    run.started_at = datetime.now(UTC)
    run.ended_at = None
    run.created_at = datetime.now(UTC)
    run.updated_at = None
    run.organization_id = _ORGANIZATION_ID
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


def _db() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def _client_for(role: str) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_execution_service] = lambda: (
        WorkflowExecutionService(_db())
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture
def owner_client() -> Iterator[OpenClient]:
    yield from _client_for(OrgRoleName.OWNER)


def _url(tail: str = "") -> str:
    return f"{settings.API_V1_STR}/workflow-runs{tail}"


@pytest.fixture(autouse=True)
def _no_dispatch_trigger():
    with patch.object(WorkflowExecutionService, "_trigger_dispatch", MagicMock()):
        yield


class TestStartRoute:
    async def test_starting_a_run_answers_201(self, owner_client: OpenClient):
        workflow = _workflow()
        created = _run_row(workflow_id=workflow.id)
        entry_node_run = MagicMock(id=uuid.uuid4())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_repo.get_version",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=workflow.current_version_id,
                        graph=_graph().model_dump(mode="json"),
                        budget_limit=None,
                    )
                ),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_outbox", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(workflow.id)})
        assert response.status_code == 201
        assert response.json()["id"] == str(created.id)

    @pytest.mark.security
    async def test_starting_a_run_of_an_unreachable_workflow_is_not_found(
        self, owner_client: OpenClient
    ):
        with patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(uuid.uuid4())})
        assert response.status_code == 404

    async def test_starting_a_run_with_no_published_version_is_a_409(
        self, owner_client: OpenClient
    ):
        workflow = _workflow(current_version_id=None, status=WorkflowStatus.DRAFT.value)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(workflow.id)})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "WORKFLOW_NOT_RUNNABLE"


class TestListRoute:
    """The `workflows:view` gate itself is proven generically by
    `tests/api/test_platform_routes.py`'s `CALLS`-driven sweep, which now
    carries a `GET /workflow-runs` entry - not re-proven here."""

    async def test_listing_answers_the_page(self, owner_client: OpenClient):
        run = _run_row()
        with (
            patch(f"{FACADE_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_runs", new=AsyncMock(return_value=([run], 1))
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(run.id)


class TestGetRoute:
    async def test_getting_one_run(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}"))
        assert response.status_code == 200
        assert response.json()["id"] == str(run.id)

    @pytest.mark.security
    async def test_a_cross_tenant_run_is_not_found(self, owner_client: OpenClient):
        with patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)):
            async with owner_client() as http:
                response = await http.get(_url(f"/{uuid.uuid4()}"))
        assert response.status_code == 404


class TestCancelRoute:
    async def test_cancelling_a_live_run(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        cancelled = _run_row(id=run.id, status=WorkflowRunStatus.CANCELLED.value)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.cancel_live_outbox_for_run", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=cancelled)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            async with owner_client() as http:
                response = await http.post(_url(f"/{run.id}/cancel"))
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    async def test_cancelling_an_already_terminal_run_is_a_409(self, owner_client: OpenClient):
        run = _run_row(status=WorkflowRunStatus.SUCCEEDED.value)
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.post(_url(f"/{run.id}/cancel"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "WORKFLOW_RUN_TERMINAL"


class TestEventsRoute:
    async def test_listing_events_since_a_cursor(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        event_row = MagicMock(
            id=uuid.uuid4(),
            seq=9,
            kind="node_completed",
            node_run_id=None,
            payload={},
            created_at=datetime.now(UTC),
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_events_since",
                new=AsyncMock(return_value=[event_row]),
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/events"), params={"after": "3"})
        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["seq"] == 9
        assert body["next_cursor"] == "9"

    async def test_an_invalid_cursor_is_a_400(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.get(
                    _url(f"/{run.id}/events"), params={"after": "not-a-number"}
                )
        assert response.status_code == 400
