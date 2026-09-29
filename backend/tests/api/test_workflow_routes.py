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
from app.schemas.workflow import WorkflowDetail
from app.services.workflow_registry import WorkflowRegistryService
from app.services.workflow_triggers import SwitchedOn
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_live_triggers():
    """The session here is a mock with no triggers to read: none of these workflows has one."""
    with patch(
        "app.services.workflow_registry.WorkflowTriggerSync.states",
        new=AsyncMock(return_value={}),
    ):
        yield


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
    workflow.live_trigger = None
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
        patch(
            f"{REGISTRY_PATH}.workflow_repo.slugs_with_prefix",
            new=AsyncMock(return_value=set()),
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.create", new=AsyncMock(return_value=created)),
    ):
        async with owner_client() as http:
            response = await http.post(_url(), json={"name": "Import orders"})
    assert response.status_code == 201
    assert response.json()["slug"] == "import-orders"


async def test_a_taken_handle_is_numbered_rather_than_refused(owner_client: OpenClient):
    async def _create(db, *, slug, name, **kwargs):
        return _workflow(slug=slug, name=name)

    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.slugs_with_prefix",
            new=AsyncMock(return_value={"import-orders"}),
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.create", new=AsyncMock(side_effect=_create)),
    ):
        async with owner_client() as http:
            response = await http.post(_url(), json={"name": "Import orders"})
    assert response.status_code == 201
    assert response.json()["slug"] == "import-orders-2"
    assert response.json()["name"] == "Import orders 2"


@pytest.mark.security
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


async def test_a_malformed_graph_with_a_stale_revision_still_answers_409(owner_client: OpenClient):
    """`WorkflowDraftUpdate.graph` is a raw dict precisely so FastAPI cannot
    validate its shape while parsing the request, ahead of the revision
    compare-and-set: a malformed graph on a stale write must still answer
    the 409 that write's staleness deserves, not a 422 about the graph it
    was never going to be allowed to save anyway."""
    workflow = _workflow(draft_revision=5)
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(f"/{workflow.id}/draft"),
                json={"graph": {}, "expected_revision": 0},
            )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"


async def test_a_malformed_graph_with_a_current_revision_answers_422_from_the_service(
    owner_client: OpenClient,
):
    workflow = _workflow()
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(f"/{workflow.id}/draft"),
                json={"graph": {}, "expected_revision": 0},
            )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "GRAPH_INVALID"
    assert body["error"]["details"]["fields"]


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
        patch(f"{REGISTRY_PATH}.WorkflowTriggerSync") as sync,
    ):
        sync.return_value.switch_on = AsyncMock(
            return_value=SwitchedOn(trigger="core.input", exposure=None, webhook_secret=None)
        )
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/publish"), json={"note": "first cut", "expected_revision": 0}
            )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["note"] == "first cut"
    assert body["trigger"] == "core.input"
    assert body["exposure"] is None
    assert body["webhook_secret"] is None


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
    # The list stays lean - a version's frozen graph is only on the detail route.
    assert "graph" not in response.json()["items"][0]


async def test_getting_one_version_answers_its_frozen_graph(owner_client: OpenClient):
    workflow = _workflow()
    version = MagicMock()
    version.id = uuid.uuid4()
    version.workflow_id = workflow.id
    version.version = 1
    version.note = "cut"
    version.published_by_user_id = workflow.owner_user_id
    version.budget_limit = None
    version.created_at = None
    version.graph = _graph().model_dump(mode="json")

    with (
        patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
        patch(f"{REGISTRY_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)),
    ):
        async with owner_client() as http:
            response = await http.get(_url(f"/{workflow.id}/versions/{version.id}"))
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["graph"]["entry_node_id"]


async def test_getting_a_missing_version_is_a_404(owner_client: OpenClient):
    workflow = _workflow()
    with (
        patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
        patch(f"{REGISTRY_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=None)),
    ):
        async with owner_client() as http:
            response = await http.get(_url(f"/{workflow.id}/versions/{uuid.uuid4()}"))
    assert response.status_code == 404


@pytest.mark.security
async def test_getting_a_version_of_a_cross_tenant_workflow_is_a_404(owner_client: OpenClient):
    with patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)):
        async with owner_client() as http:
            response = await http.get(_url(f"/{uuid.uuid4()}/versions/{uuid.uuid4()}"))
    assert response.status_code == 404


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


def _version_of(workflow, *, number: int = 1):
    version = MagicMock()
    version.id = uuid.uuid4()
    version.workflow_id = workflow.id
    version.version = number
    version.graph = _graph().model_dump(mode="json")
    return version


async def test_restoring_a_version_answers_the_draft_at_its_new_revision(owner_client: OpenClient):
    workflow = _workflow(draft_revision=2)
    version = _version_of(workflow, number=1)

    async def _update(db, *, workflow, update_data):
        for field, value in update_data.items():
            setattr(workflow, field, value)
        return workflow

    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)),
        patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(side_effect=_update)),
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/versions/{version.id}/restore"),
                json={"expected_revision": 2},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["draft_revision"] == 3
    assert body["draft_graph"]["entry_node_id"] == version.graph["entry_node_id"]


async def test_restoring_over_a_changed_draft_answers_409(owner_client: OpenClient):
    workflow = _workflow(draft_revision=3)
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/versions/{uuid.uuid4()}/restore"),
                json={"expected_revision": 2},
            )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"
    assert response.json()["error"]["details"]["current_revision"] == 3


async def test_restoring_an_archived_workflow_answers_409(owner_client: OpenClient):
    workflow = _workflow(status=WorkflowStatus.ARCHIVED.value)
    with patch(
        f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/versions/{uuid.uuid4()}/restore"),
                json={"expected_revision": 0},
            )
    assert response.status_code == 409


async def test_restoring_another_workflows_version_is_a_404(owner_client: OpenClient):
    workflow = _workflow()
    foreign = _version_of(_workflow())
    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=foreign)),
    ):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/versions/{foreign.id}/restore"),
                json={"expected_revision": 0},
            )
    assert response.status_code == 404


@pytest.mark.security
async def test_restoring_a_version_of_a_cross_tenant_workflow_is_a_404(owner_client: OpenClient):
    with patch(f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=None)):
        async with owner_client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}/versions/{uuid.uuid4()}/restore"),
                json={"expected_revision": 0},
            )
    assert response.status_code == 404


@pytest.mark.security
async def test_a_viewer_without_an_edit_grant_cannot_restore(viewer_client: OpenClient):
    workflow = _workflow()
    with (
        patch(
            f"{REGISTRY_PATH}.workflow_repo.get_for_update", new=AsyncMock(return_value=workflow)
        ),
        patch(
            "app.services.access.resource_grant_repo.get_level",
            new=AsyncMock(return_value=GrantLevel.READ),
        ),
        patch(f"{REGISTRY_PATH}.workflow_repo.update") as update,
    ):
        async with viewer_client() as http:
            response = await http.post(
                _url(f"/{workflow.id}/versions/{uuid.uuid4()}/restore"),
                json={"expected_revision": 0},
            )
    assert response.status_code == 404
    update.assert_not_called()


@pytest.fixture
def stubbed() -> Iterator[tuple[MagicMock, OpenClient]]:
    """The routes over a stand-in service: what they hand it and how they answer."""
    detail = WorkflowDetail(
        id=uuid.uuid4(),
        slug="import-orders",
        name="Import orders",
        status="published",
        visibility="org",
        trigger_active=False,
        draft_revision=1,
        draft_graph=None,
    )
    service = MagicMock()
    for method in ("update", "set_active", "archive", "unarchive"):
        setattr(service, method, AsyncMock(return_value=detail))
    service.delete = AsyncMock(return_value=None)
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_registry_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield service, open_client
    app.dependency_overrides.clear()


async def test_managing_a_workflow_hands_the_service_each_change(stubbed):
    service, client = stubbed
    workflow_id = uuid.uuid4()
    async with client() as http:
        renamed = await http.patch(_url(f"/{workflow_id}"), json={"name": "Leads", "tags": ["a"]})
        switched = await http.put(_url(f"/{workflow_id}/active"), json={"is_active": True})
        archived = await http.post(_url(f"/{workflow_id}/archive"))
        restored = await http.post(_url(f"/{workflow_id}/unarchive"))
        deleted = await http.delete(_url(f"/{workflow_id}"))
        unknown = await http.patch(_url(f"/{workflow_id}"), json={"slug": "no"})

    assert [r.status_code for r in (renamed, switched, archived, restored)] == [200] * 4
    assert renamed.json()["trigger_active"] is False
    assert deleted.status_code == 204
    assert unknown.status_code == 422
    assert service.update.await_args.args[2].tags == ["a"]
    assert service.set_active.await_args.args[1:] == (workflow_id, True)
