"""The console and API share file preview, reviewed import and download contracts."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.spec import AgentSpec
from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.resource_bundle import BundleImportRead, BundlePreview
from app.services.portability import PortabilityService
from app.services.portability.snapshots import agent_snapshot

pytestmark = pytest.mark.anyio


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock, AuthContext]]:
    service = MagicMock(spec=PortabilityService)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_portability_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, service, ctx
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("file_format", ["yaml", "json"])
async def test_preview_download_and_import_are_one_typed_contract(
    wired: tuple[AsyncClient, MagicMock, AuthContext], file_format: str
) -> None:
    client, service, ctx = wired
    source, created = uuid4(), uuid4()
    bundle = agent_snapshot(AgentSpec(name="Agent"), source_id=source)
    preview = BundlePreview(bundle=bundle, options=())
    service.export_agent = AsyncMock(return_value=preview)
    service.download_agent = AsyncMock(return_value=b"portable file")
    service.preview_document = AsyncMock(return_value=preview)
    service.import_bundle = AsyncMock(
        return_value=BundleImportRead(
            roots={bundle.roots[0]: created},
            created={bundle.roots[0]: created},
            reused={},
            skipped=(),
        )
    )
    exported = await client.get(f"/api/v1/agents/{source}/export-preview")
    assert exported.status_code == 200
    assert exported.json()["bundle"]["format"] == "agenticos.bundle"
    download = await client.post(
        f"/api/v1/agents/{source}/export",
        json={"file_format": file_format, "resources": {bundle.roots[0]: ["definition"]}},
    )
    assert download.status_code == 200
    assert download.content == b"portable file"
    assert (
        download.headers["content-disposition"]
        == f'attachment; filename="agent-{source}.{file_format}"'
    )
    review = await client.post("/api/v1/agents/import-preview", json={"text": "name: Agent"})
    assert review.status_code == 200
    service.preview_document.assert_awaited_once_with(ctx, "name: Agent")
    imported = await client.post(
        "/api/v1/agents/import",
        json={
            "operation_id": str(uuid4()),
            "bundle": bundle.model_dump(mode="json"),
            "choices": {bundle.roots[0]: {"action": "create"}},
        },
    )
    assert imported.status_code == 201
    assert imported.json()["roots"][bundle.roots[0]] == str(created)
    assert service.import_bundle.await_args.args[0] == ctx


async def test_collection_import_permission_is_checked_before_the_service(
    wired: tuple[AsyncClient, MagicMock, AuthContext],
) -> None:
    client, service, _ = wired
    viewer = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    app.dependency_overrides[deps.get_auth_context] = lambda: viewer
    response = await client.post("/api/v1/agents/import-preview", json={"text": "name: Agent"})
    assert response.status_code == 403
    service.preview_document.assert_not_awaited()


async def test_invalid_file_format_is_refused_at_the_http_boundary(
    wired: tuple[AsyncClient, MagicMock, AuthContext],
) -> None:
    client, service, _ = wired
    response = await client.post(
        f"/api/v1/agents/{uuid4()}/export", json={"file_format": "shell", "resources": {}}
    )
    assert response.status_code == 422
    service.download_agent.assert_not_awaited()


async def test_destination_picker_is_typed_and_scoped_to_import_permission(
    wired: tuple[AsyncClient, MagicMock, AuthContext],
) -> None:
    from app.schemas.resource_bundle import BundleDestinationList, BundleDestinationOption

    client, service, ctx = wired
    identity = uuid4()
    service.destinations = AsyncMock(
        return_value=BundleDestinationList(
            items=[BundleDestinationOption(id=identity, name="Policy")], total=1
        )
    )
    response = await client.get(
        "/api/v1/agents/import-destinations?kind=context&search=Policy&limit=25"
    )
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": str(identity), "name": "Policy"}]
    assert service.destinations.await_args.args[0] == ctx
    assert service.destinations.await_args.args[1].search == "Policy"
    assert (await client.get("/api/v1/agents/import-destinations?kind=invalid")).status_code == 422
    assert (
        await client.get("/api/v1/agents/import-destinations?kind=context&limit=101")
    ).status_code == 422
    viewer = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    app.dependency_overrides[deps.get_auth_context] = lambda: viewer
    assert (await client.get("/api/v1/agents/import-destinations?kind=context")).status_code == 403
    service.destinations.assert_awaited_once()
