"""The agent metadata command route, through the app.

`tests/api/test_platform_routes.py` proves this per-resource PATCH carries no
role gate and that `GET /agents` keeps its `agents:view` one;
`tests/test_agent_registry.py` proves the service checks `agents:edit` and
persists. What is left is the handler itself: it parses the body, answers an
`AgentRead`, refuses an invalid body at the edge with a 422, and reports a
cross-tenant target as a 404 - and a Viewer holding an explicit edit grant
reaches it, since the route delegates to the grant-aware service.

The real service runs with the repository stubbed at the database edge.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.spec import AgentSpec
from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentKind, AgentStatus, AgentVersion
from app.db.models.authoring import BatchStatus
from app.db.models.resource_grant import GrantLevel, Visibility
from app.main import app
from app.schemas.agent import agent_draft_revision
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

REGISTRY_PATH = "app.services.agent_registry"


def _agent(*, categories: list[str] | None = None, tags: list[str] | None = None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
        slug="support",
        name="Support",
        description=None,
        status=AgentStatus.DRAFT.value,
        kind=AgentKind.AGENT.value,
        draft_spec={},
        categories=categories or [],
        tags=tags or [],
        # What the column's default gives every stored row.
        a2a_enabled=False,
    )


def _client_for(role: str) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: AgentRegistryService(
        MagicMock()
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


def _url(agent_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/agents/{agent_id}/metadata"


def _discard_url(agent_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/agents/{agent_id}/draft/discard"


async def test_setting_metadata_answers_the_normalized_agent_read(owner_client: OpenClient):
    agent = _agent()
    saved = _agent(categories=["sales"], tags=["eu"])
    saved.id = agent.id
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=saved)) as update,
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(agent.id),
                json={"categories": ["Sales", "sales"], "tags": ["  EU  "]},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["categories"] == ["sales"]
    assert body["tags"] == ["eu"]
    # The body reached the service already folded, so duplicates never hit the row.
    assert update.call_args.kwargs["update_data"] == {"categories": ["sales"], "tags": ["eu"]}


async def test_an_over_length_label_is_refused_at_the_edge(owner_client: OpenClient):
    async with owner_client() as http:
        response = await http.patch(_url(uuid.uuid4()), json={"tags": ["x" * 33]})
    assert response.status_code == 422


async def test_too_many_categories_are_refused_at_the_edge(owner_client: OpenClient):
    async with owner_client() as http:
        response = await http.patch(
            _url(uuid.uuid4()), json={"categories": [f"c{i}" for i in range(11)]}
        )
    assert response.status_code == 422


@pytest.mark.security
async def test_a_cross_tenant_target_is_a_not_found(owner_client: OpenClient):
    """The org filter in the repo read means another tenant's agent is missing."""
    with patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)):
        async with owner_client() as http:
            response = await http.patch(_url(uuid.uuid4()), json={"tags": ["x"]})
    assert response.status_code == 404


async def test_a_viewer_with_an_edit_grant_reaches_the_route(viewer_client: OpenClient):
    """No role gate on the route, so the grant-aware service is what decides."""
    agent = _agent()
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(
            "app.services.access.resource_grant_repo.get_level",
            new=AsyncMock(return_value=GrantLevel.EDIT),
        ),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)),
        patch(
            f"{REGISTRY_PATH}.organization_assistant_repo.for_agent",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with viewer_client() as http:
            response = await http.patch(_url(agent.id), json={"tags": ["ops"]})
    assert response.status_code == 200


async def test_saving_a_draft_answers_the_canonical_spec(owner_client: OpenClient) -> None:
    saved = _agent()
    spec = AgentSpec(name="Canonical", variables=[{"name": "customer"}])
    saved.name = spec.name
    saved.draft_spec = spec.model_dump(mode="json")
    with patch.object(
        AgentRegistryService, "save_draft", new=AsyncMock(return_value=saved)
    ) as save:
        async with owner_client() as http:
            response = await http.put(
                f"{settings.API_V1_STR}/agents/{saved.id}/draft",
                json={
                    "spec": {"name": "Canonical", "variables": [{"name": "customer"}]},
                    "expected_revision": "0" * 64,
                },
            )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(saved.id)
    assert body["draft_spec"] == spec.model_dump(mode="json")
    assert body["draft_spec"]["variables"][0]["description"] is None
    save.assert_awaited_once()
    assert save.await_args.kwargs["expected_revision"] == "0" * 64
    assert len(body["draft_revision"]) == 64


@pytest.mark.parametrize("revision", [None, "invalid", 7])
async def test_draft_replacement_requires_a_valid_base_revision(
    owner_client: OpenClient, revision: object
) -> None:
    payload: dict[str, object] = {"spec": {"name": "Support"}}
    if revision is not None:
        payload["expected_revision"] = revision
    with patch.object(AgentRegistryService, "save_draft", new=AsyncMock()) as save:
        async with owner_client() as http:
            response = await http.put(
                f"{settings.API_V1_STR}/agents/{uuid.uuid4()}/draft", json=payload
            )
    assert response.status_code == 422
    save.assert_not_awaited()


async def test_a_stale_draft_is_a_write_free_conflict(owner_client: OpenClient) -> None:
    agent = _agent()
    agent.draft_spec = AgentSpec(name="Updated elsewhere").model_dump(mode="json")
    with (
        patch.object(AgentRegistryService, "get", new=AsyncMock(return_value=agent)),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as write,
    ):
        async with owner_client() as http:
            response = await http.put(
                f"{settings.API_V1_STR}/agents/{agent.id}/draft",
                json={"spec": {"name": "Stale"}, "expected_revision": "0" * 64},
            )
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"reason": "draft_changed"}
    write.assert_not_awaited()


@pytest.mark.security
async def test_an_edit_only_key_can_obtain_a_revision_without_reading_the_draft(
    owner_client: OpenClient,
) -> None:
    agent = _agent()
    spec = AgentSpec(name="Private instructions", instructions="Do not disclose this")
    agent.draft_spec = spec.model_dump(mode="json")
    ctx = AuthContext(
        user_id=agent.owner_user_id,
        organization_id=_ORGANIZATION_ID,
        role=OrgRoleName.OWNER,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.AGENTS_EDIT}),
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(
            f"{REGISTRY_PATH}.organization_assistant_repo.for_agent",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with owner_client() as http:
            token = await http.get(f"{settings.API_V1_STR}/agents/{agent.id}/draft-revision")
            detail = await http.get(f"{settings.API_V1_STR}/agents/{agent.id}")
    assert token.status_code == 200
    assert token.json() == {"draft_revision": agent_draft_revision(spec)}
    assert detail.status_code == 404


async def test_a_stale_yaml_import_cannot_replace_a_newer_draft(owner_client: OpenClient) -> None:
    agent = _agent()
    agent.draft_spec = AgentSpec(name="Newer").model_dump(mode="json")
    with (
        patch.object(AgentRegistryService, "get", new=AsyncMock(return_value=agent)),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as write,
    ):
        async with owner_client() as http:
            response = await http.post(
                f"{settings.API_V1_STR}/agents/{agent.id}/spec.yaml",
                json={"yaml": "name: Stale", "expected_revision": "0" * 64},
            )
    assert response.status_code == 409
    write.assert_not_awaited()


async def test_a_yaml_import_requires_its_base_revision(owner_client: OpenClient) -> None:
    with patch.object(AgentRegistryService, "import_spec", new=AsyncMock()) as save:
        async with owner_client() as http:
            response = await http.post(
                f"{settings.API_V1_STR}/agents/{uuid.uuid4()}/spec.yaml",
                json={"yaml": "name: Stale"},
            )
    assert response.status_code == 422
    save.assert_not_awaited()


@pytest.mark.parametrize("open_batch", [False, True])
async def test_edit_grant_can_discard_to_the_latest_version_without_publishing(
    viewer_client: OpenClient, open_batch: bool
) -> None:
    agent = _agent(tags=["retained"])
    draft = AgentSpec(name="Draft name", instructions="Unpublished")
    published = AgentSpec(name="Published name", description="Published description")
    agent.draft_spec = draft.model_dump(mode="json")
    agent.status = AgentStatus.PUBLISHED.value
    # Production is pinned elsewhere; the highest-numbered publication is the draft base.
    agent.current_version_id = uuid.uuid4()
    latest = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version=12, spec=published.model_dump(mode="json")
    )
    saved = _agent(tags=["retained"])
    saved.id = agent.id
    saved.status = agent.status
    saved.current_version_id = agent.current_version_id
    saved.name = published.name
    saved.description = published.description
    saved.draft_spec = latest.spec
    batch = MagicMock() if open_batch else None
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)) as read,
        patch(
            "app.services.access.resource_grant_repo.get_level",
            new=AsyncMock(return_value=GrantLevel.EDIT),
        ),
        patch(
            f"{REGISTRY_PATH}.organization_assistant_repo.for_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            f"{REGISTRY_PATH}.agent_repo.newest_version", new=AsyncMock(return_value=latest)
        ) as newest,
        patch(f"{REGISTRY_PATH}.skill_repo.hold", new=AsyncMock()),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=saved)) as write,
        patch(f"{REGISTRY_PATH}.agent_repo.create_version", new=AsyncMock()) as publish,
        patch(f"{REGISTRY_PATH}.authoring_repo.get_open_batch", new=AsyncMock(return_value=batch)),
        patch(f"{REGISTRY_PATH}.authoring_repo.close_batch", new=AsyncMock()) as close,
        patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
    ):
        async with viewer_client() as http:
            response = await http.post(
                _discard_url(agent.id),
                json={
                    "expected_revision": agent_draft_revision(draft),
                    "expected_version_id": str(latest.id),
                },
            )
    assert response.status_code == 200
    body = response.json()
    assert body["draft_spec"] == latest.spec
    assert body["draft_revision"] == agent_draft_revision(published)
    assert body["current_version_id"] == str(agent.current_version_id)
    assert body["tags"] == ["retained"]
    assert body["can_edit"] is True
    assert body["can_run"] is True
    assert body["can_publish"] is True
    assert read.await_args.kwargs["for_update"] is True
    assert newest.await_args.kwargs == {"agent_id": agent.id, "organization_id": _ORGANIZATION_ID}
    assert write.await_args.kwargs["update_data"] == {
        "draft_spec": latest.spec,
        "name": published.name,
        "description": published.description,
    }
    publish.assert_not_awaited()
    if open_batch:
        assert close.await_args.kwargs == {"batch": batch, "status": BatchStatus.SUPERSEDED}
    else:
        close.assert_not_awaited()
    assert audit.await_args.kwargs["action"] == "agent.draft_discarded"
    assert audit.await_args.kwargs["details"] == {"version": 12}


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("stale_draft", 409, "draft_changed"),
        ("stale_version", 409, "published_version_changed"),
        ("archived", 400, None),
        ("never_published", 400, None),
        ("already_reset", 200, None),
        ("outside_org", 404, None),
    ],
)
async def test_discard_does_not_write_when_it_cannot_replace_the_confirmed_draft(
    owner_client: OpenClient, case: str, status: int, reason: str | None
) -> None:
    agent = _agent()
    agent.status = AgentStatus.ARCHIVED.value if case == "archived" else AgentStatus.PUBLISHED.value
    draft = AgentSpec(name="Draft")
    agent.draft_spec = draft.model_dump(mode="json")
    published = draft if case == "already_reset" else AgentSpec(name="Published")
    latest = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version=3, spec=published.model_dump(mode="json")
    )
    with (
        patch(
            f"{REGISTRY_PATH}.agent_repo.get",
            new=AsyncMock(return_value=None if case == "outside_org" else agent),
        ),
        patch(
            f"{REGISTRY_PATH}.agent_repo.newest_version",
            new=AsyncMock(return_value=None if case == "never_published" else latest),
        ),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as write,
        patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
    ):
        async with owner_client() as http:
            response = await http.post(
                _discard_url(agent.id),
                json={
                    "expected_revision": "0" * 64
                    if case == "stale_draft"
                    else agent_draft_revision(draft),
                    "expected_version_id": str(
                        uuid.uuid4() if case == "stale_version" else latest.id
                    ),
                },
            )
    assert response.status_code == status
    if reason:
        assert response.json()["error"]["details"] == {"reason": reason}
    write.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.security
async def test_discard_cannot_expose_the_published_spec_to_an_edit_only_key(
    owner_client: OpenClient,
) -> None:
    agent = _agent()
    ctx = AuthContext(
        user_id=agent.owner_user_id,
        organization_id=_ORGANIZATION_ID,
        role=OrgRoleName.OWNER,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.AGENTS_EDIT}),
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(
            f"{REGISTRY_PATH}.organization_assistant_repo.for_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(f"{REGISTRY_PATH}.agent_repo.newest_version", new=AsyncMock()) as newest,
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as write,
    ):
        async with owner_client() as http:
            response = await http.post(
                _discard_url(agent.id),
                json={
                    "expected_revision": "0" * 64,
                    "expected_version_id": str(uuid.uuid4()),
                },
            )
    assert response.status_code == 404
    newest.assert_not_awaited()
    write.assert_not_awaited()
