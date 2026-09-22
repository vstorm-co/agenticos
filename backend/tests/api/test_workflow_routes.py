"""The workflow registry routes, through the app: the wire contract.

`tests/api/test_platform_routes.py` proves the collection routes are gated
and the per-workflow routes delegate; `tests/test_workflow_registry_service.py`
proves what the service does against a mocked repository. What is left is the
handler itself: status codes, the error envelope a client branches on, and
the shapes `RevisionConflictError`/`GraphValidationError` put on the wire.

The real service runs with the repository stubbed at the database edge, the
same bargain `test_agent_metadata_routes.py` makes for agents.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.workflow import WorkflowStatus
from app.main import app
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

REGISTRY_PATH = "app.services.workflow_registry"


def _graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={"message": "hi"},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


def _workflow(**overrides: object):
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.organization_id = _ORGANIZATION_ID
    workflow.owner_user_id = uuid.uuid4()
    workflow.visibility = Visibility.PRIVATE.value
    workflow.status = WorkflowStatus.DRAFT.value
    workflow.slug = "import-orders"
    workflow.name = "Import orders"
    workflow.description = None
    workflow.draft_revision = 0
    workflow.draft_graph = _graph().model_dump(mode="json")
    workflow.current_version_id = None
    workflow.created_at = None
    workflow.updated_at = None
    for field, value in overrides.items():
        setattr(workflow, field, value)
    return workflow


def _db() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # `record_audit` (via `create`/`publish`) reads the chain head and takes the
    # per-org lock, both through `execute`; answer the head read with an empty
    # chain so the mount does not have to model a real one.
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def _client_for(role: str) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_registry_service] = lambda: WorkflowRegistryService(
        _db()
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


@pytest.fixture
def viewer_client() -> Iterator[OpenClient]:
    yield from _client_for(OrgRoleName.VIEWER)


def _url(tail: str = "") -> str:
    return f"{settings.API_V1_STR}/workflows{tail}"


async def test_the_node_catalog_lists_debug_echo(owner_client: OpenClient):
    async with owner_client() as http:
        response = await http.get(_url("/node-catalog"))
    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == "debug.echo" for item in body["items"])
    assert body["total"] == len(body["items"])


async def test_creating_a_workflow_answers_201_with_the_derived_slug(owner_client: OpenClient):
    created = _workflow()
    with (
        patch(f"{REGISTRY_PATH}.workflow_repo.get_by_slug", new=AsyncMock(return_value=None)),
        patch(f"{REGISTRY_PATH}.workflow_repo.create", new=AsyncMock(return_value=created)),
    ):
        async with owner_client() as http:
            response = await http.post(_url(), json={"name": "Import orders"})
    assert response.status_code == 201
    assert response.json()["slug"] == "import-orders"


async def test_creating_with_a_taken_slug_is_a_409(owner_client: OpenClient):
    existing = _workflow()
    with patch(f"{REGISTRY_PATH}.workflow_repo.get_by_slug", new=AsyncMock(return_value=existing)):
        async with owner_client() as http:
            response = await http.post(_url(), json={"name": "Import orders"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_EXISTS"


async def test_creating_without_the_permission_is_a_403(viewer_client: OpenClient):
    async with viewer_client() as http:
        response = await http.post(_url(), json={"name": "Import orders"})
    assert response.status_code == 403


async def test_getting_one_workflow_answers_its_draft_graph(owner_client: OpenClient):
    workflow = _workflow(owner_user_id=uuid.UUID(int=0))
    with patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)):
        async with owner_client() as http:
            response = await http.get(_url(f"/{workflow.id}"))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(workflow.id)
    assert body["draft_graph"]["entry_node_id"]


@pytest.mark.security
async def test_a_cross_tenant_workflow_is_a_not_found(owner_client: OpenClient):
    with patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)):
        async with owner_client() as http:
            response = await http.get(_url(f"/{uuid.uuid4()}"))
    assert response.status_code == 404


async def test_a_viewer_with_an_edit_grant_can_still_update_the_draft(viewer_client: OpenClient):
    """No role gate on the draft route, so the grant-aware service decides."""
    workflow = _workflow()
    graph = _graph()

    async def _update(db, *, workflow, update_data):
        for field, value in update_data.items():
            setattr(workflow, field, value)
        return workflow

    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
        ),
        patch(
            "app.services.access.resource_grant_repo.get_level",
            new=AsyncMock(return_value=GrantLevel.EDIT),
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(side_effect=_update)),
    ):
        async with viewer_client() as http:
            response = await http.patch(
                _url(f"/{workflow.id}/draft"),
                json={"graph": graph.model_dump(mode="json"), "expected_revision": 0},
            )
    assert response.status_code == 200
    assert response.json()["draft_revision"] == 1


async def test_a_stale_revision_answers_409_naming_both_revisions(owner_client: OpenClient):
    workflow = _workflow(draft_revision=5)
    graph = _graph()
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(f"/{workflow.id}/draft"),
                json={"graph": graph.model_dump(mode="json"), "expected_revision": 0},
            )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "REVISION_CONFLICT"
    assert body["error"]["details"]["expected_revision"] == 0
    assert body["error"]["details"]["current_revision"] == 5


async def test_an_archived_workflow_refuses_the_draft_write_with_409(owner_client: OpenClient):
    workflow = _workflow(status=WorkflowStatus.ARCHIVED.value)
    graph = _graph()
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(f"/{workflow.id}/draft"),
                json={"graph": graph.model_dump(mode="json"), "expected_revision": 0},
            )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKFLOW_ARCHIVED"


async def test_publishing_an_invalid_graph_answers_422_naming_every_problem(
    owner_client: OpenClient,
):
    # entry_node_id does not name any node in `nodes` - rule 1.
    bad_graph = WorkflowGraph(
        entry_node_id=uuid.uuid4(),
        nodes=(
            NodeInstance(
                id=uuid.uuid4(),
                definition_id="debug.echo",
                definition_version=1,
                config={"message": "hi"},
                layout=NodePosition(x=0, y=0),
            ),
        ),
    )
    workflow = _workflow(draft_graph=bad_graph.model_dump(mode="json"))
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/publish"), json={"expected_revision": 0}
            )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "GRAPH_INVALID"
    assert body["error"]["details"]["fields"]


async def test_publishing_a_valid_graph_answers_201_shaped_version(owner_client: OpenClient):
    workflow = _workflow()
    version = MagicMock()
    version.id = uuid.uuid4()
    version.version = 1
    version.note = "first cut"
    version.published_by_user_id = workflow.owner_user_id
    version.budget_limit = None
    version.created_at = None

    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.next_version_number", new=AsyncMock(return_value=1)),
        patch(f"{REGISTRY_PATH}.workflow_repo.create_version", new=AsyncMock(return_value=version)),
        patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(return_value=workflow)),
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/publish"), json={"note": "first cut", "expected_revision": 0}
            )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["note"] == "first cut"


async def test_listing_versions_returns_every_published_version(owner_client: OpenClient):
    workflow = _workflow()
    version = MagicMock()
    version.id = uuid.uuid4()
    version.version = 1
    version.note = None
    version.published_by_user_id = workflow.owner_user_id
    version.budget_limit = None
    version.created_at = None

    with (
        patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
        patch(
            f"{REGISTRY_PATH}.workflow_repo.list_versions", new=AsyncMock(return_value=[version])
        ),
    ):
        async with owner_client() as http:
            response = await http.get(_url(f"/{workflow.id}/versions"))
    assert response.status_code == 200
    assert [item["version"] for item in response.json()["items"]] == [1]


async def test_listing_workflows_answers_the_paginated_envelope(owner_client: OpenClient):
    with (
        patch(
            f"{REGISTRY_PATH}.visible_resource_ids",
            new=AsyncMock(return_value=None),
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.list_visible", new=AsyncMock(return_value=([], 0))),
    ):
        async with owner_client() as http:
            response = await http.get(_url())
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
