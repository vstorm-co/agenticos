"""Table trigger routes through the app, with the service mocked (#1785).

`tests/integration/test_table_triggers.py` drives the real service over HTTP;
this is the wire contract - status codes and what each handler hands the service.
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
from app.schemas.virtual_table_trigger import (
    TableTriggerAdmissionList,
    TableTriggerList,
    TableTriggerRead,
)

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
_TABLE = uuid.uuid4()
_BASE = f"{settings.API_V1_STR}/tables/{_TABLE}/triggers"


def _read() -> TableTriggerRead:
    now = datetime.now(UTC)
    return TableTriggerRead(
        id=uuid.uuid4(),
        table_id=_TABLE,
        workflow_id=uuid.uuid4(),
        workflow_name="Follow up",
        workflow_version_id=uuid.uuid4(),
        version_number=1,
        name=None,
        revision=1,
        filters=[],
        input_mapping={},
        execution_principal_user_id=_CTX.user_id,
        is_active=True,
        activated_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    service = MagicMock()
    app.dependency_overrides[deps.get_table_trigger_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: _CTX
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service
    app.dependency_overrides.clear()


async def test_each_route_hands_the_service_the_table_and_trigger_in_its_path(wired) -> None:
    client, service = wired
    made = _read()
    service.list_for_table = AsyncMock(return_value=TableTriggerList(items=[made]))
    service.create = AsyncMock(return_value=made)
    service.update = AsyncMock(return_value=made)
    service.delete = AsyncMock(return_value=None)
    service.admissions = AsyncMock(return_value=TableTriggerAdmissionList(items=[], total=0))

    assert (await client.get(_BASE)).json()["items"][0]["id"] == str(made.id)
    created = await client.post(_BASE, json={"workflow_id": str(made.workflow_id)})
    assert created.status_code == 201
    patched = await client.patch(f"{_BASE}/{made.id}", json={"is_active": False})
    assert patched.status_code == 200
    history = await client.get(f"{_BASE}/{made.id}/admissions?skip=2&limit=5")
    assert history.json() == {"items": [], "total": 0}
    removed = await client.delete(f"{_BASE}/{made.id}")
    assert removed.status_code == 204

    service.list_for_table.assert_awaited_once_with(_CTX, _TABLE)
    assert service.update.await_args.args[:3] == (_CTX, _TABLE, made.id)
    service.admissions.assert_awaited_once_with(_CTX, _TABLE, made.id, skip=2, limit=5)
    service.delete.assert_awaited_once_with(_CTX, _TABLE, made.id)


async def test_a_mapping_or_filter_list_over_its_limit_is_a_422(wired) -> None:
    client, service = wired
    service.create = AsyncMock()

    answer = await client.post(
        _BASE,
        json={
            "workflow_id": str(uuid.uuid4()),
            "input_mapping": {f"k{index}": "@author" for index in range(51)},
        },
    )

    assert answer.status_code == 422
    service.create.assert_not_awaited()
