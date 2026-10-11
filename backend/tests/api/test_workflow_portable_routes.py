"""The export and import routes' wire contract, with the service mocked (#1953).

`tests/integration/test_workflow_portable.py` drives the real service.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.workflow import WorkflowRead
from app.schemas.workflow_portable import UnresolvedResource, WorkflowExport, WorkflowImported

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    service = MagicMock()
    app.dependency_overrides[deps.get_workflow_portable_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: _CTX
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service
    app.dependency_overrides.clear()


async def test_an_export_is_the_file_and_an_import_answers_with_its_pins(wired):
    client, service = wired
    workflow_id, node_id = uuid.uuid4(), uuid.uuid4()
    pin = UnresolvedResource(node_id=node_id, step="Summarise", field="agent", kind="agent")
    service.export = AsyncMock(return_value=WorkflowExport(name="Leads", unresolved=[pin]))
    read = WorkflowRead(
        id=workflow_id,
        slug="leads",
        name="Leads",
        status="draft",
        visibility="org",
        draft_revision=1,
        created_at=datetime.now(UTC),
    )
    service.import_ = AsyncMock(return_value=WorkflowImported(workflow=read, unresolved=[pin]))

    exported = await client.get(f"{settings.API_V1_STR}/workflows/{workflow_id}/export")
    imported = await client.post(f"{settings.API_V1_STR}/workflows/import", json=exported.json())

    assert exported.status_code == 200
    assert exported.json()["format"] == "agenticos.workflow"
    assert imported.status_code == 201, imported.text
    assert imported.json()["unresolved"] == [
        {"node_id": str(node_id), "step": "Summarise", "field": "agent", "kind": "agent"}
    ]
    service.export.assert_awaited_once_with(_CTX, workflow_id)
    assert service.import_.await_args.args[1].name == "Leads"


async def test_a_file_of_another_format_is_refused_before_the_service(wired):
    client, service = wired
    service.import_ = AsyncMock()
    refused = await client.post(
        f"{settings.API_V1_STR}/workflows/import", json={"format": "n8n", "name": "x"}
    )
    assert refused.status_code == 422
    service.import_.assert_not_awaited()
