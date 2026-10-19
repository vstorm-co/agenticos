"""`PATCH /kb/{kb_id}/sync-sources/{source_id}`, the edit the KB page's wizard saves through.

What the route owns is asserted here: whose base it is, whether the source is
that base's, and that the source stays filed under it. What an update *does* -
merging the config, judging it, checking the credential - is the service's,
which is mocked.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.sync_source import SyncSourceRead, SyncSourceUpdate

pytestmark = pytest.mark.anyio

_KB_ID = uuid.uuid4()
_SOURCE_ID = uuid.uuid4()
_URL = f"{settings.API_V1_STR}/kb/{_KB_ID}/sync-sources/{_SOURCE_ID}"


def _read(**overrides: Any) -> SyncSourceRead:
    fields: dict[str, Any] = {
        "id": str(_SOURCE_ID),
        "organization_id": str(uuid.uuid4()),
        "name": "Engineering docs",
        "connector_type": "gdrive",
        "collection_name": "handbook",
        "config": {"folder_id": "1AbC"},
        "secret_id": None,
        "sync_mode": "full",
        "schedule_minutes": None,
        "is_active": True,
        "last_sync_at": None,
        "last_sync_status": None,
        "last_error": None,
        "created_at": None,
    }
    return SyncSourceRead(**{**fields, **overrides})


class _Fakes:
    def __init__(self) -> None:
        self.org_id = uuid.uuid4()
        self.kb_service = MagicMock()
        self.kb_service.get_for_write = AsyncMock(
            return_value=MagicMock(collection_name="handbook", organization_id=self.org_id)
        )
        self.sources = MagicMock()
        self.sources.get_source = AsyncMock(
            return_value=MagicMock(collection_name="handbook", organization_id=self.org_id)
        )
        self.sources.update_source = AsyncMock(
            return_value=_read(name="Renamed", schedule_minutes=60)
        )
        self.role = OrgRoleName.OWNER


@pytest.fixture
def fakes() -> _Fakes:
    return _Fakes()


@pytest.fixture
def client(mock_db_session: Any, mock_redis: MagicMock, fakes: _Fakes) -> Iterator[Any]:
    user = MagicMock()
    user.id = uuid.uuid4()

    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=user.id, organization_id=uuid.uuid4(), role=fakes.role
    )
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: fakes.kb_service
    app.dependency_overrides[deps.get_sync_source_service] = lambda: fakes.sources

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


class TestUpdateKbSyncSource:
    async def test_the_patch_reaches_the_service_as_sent(self, client, fakes: _Fakes) -> None:
        async with client() as opened:
            response = await opened.patch(_URL, json={"name": "Renamed", "schedule_minutes": 60})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        source_id, data = fakes.sources.update_source.await_args.args
        assert source_id == str(_SOURCE_ID)
        # Only what was sent is set, so the service leaves the credential alone.
        assert data.model_fields_set == {"name", "schedule_minutes"}

    async def test_a_source_of_another_base_is_missing(self, client, fakes: _Fakes) -> None:
        fakes.sources.get_source.return_value = MagicMock(
            collection_name="elsewhere", organization_id=fakes.org_id
        )

        async with client() as opened:
            response = await opened.patch(_URL, json={"name": "Renamed"})

        assert response.status_code == 404
        fakes.sources.update_source.assert_not_awaited()

    async def test_another_organizations_source_in_a_same_named_collection_is_missing(
        self, client, fakes: _Fakes
    ) -> None:
        """Collection names are not unique across tenants, so the name alone would
        let a caller who edits their own base write another organization's source."""
        fakes.sources.get_source.return_value = MagicMock(
            collection_name="handbook", organization_id=uuid.uuid4()
        )

        async with client() as opened:
            response = await opened.patch(_URL, json={"name": "Renamed"})

        assert response.status_code == 404
        fakes.sources.update_source.assert_not_awaited()

    async def test_a_caller_who_cannot_write_the_base_is_refused(
        self, client, fakes: _Fakes
    ) -> None:
        fakes.kb_service.get_for_write.side_effect = AuthorizationError(message="No write access")

        async with client() as opened:
            response = await opened.patch(_URL, json={"name": "Renamed"})

        assert response.status_code == 403
        fakes.sources.get_source.assert_not_awaited()
        fakes.sources.update_source.assert_not_awaited()

    async def test_no_role_gate_stands_in_front_of_an_edit_grant(
        self, client, fakes: _Fakes
    ) -> None:
        """A Viewer the base admits - through a grant - is not refused by role first."""
        fakes.role = OrgRoleName.VIEWER

        async with client() as opened:
            response = await opened.patch(_URL, json={"name": "Renamed"})

        assert response.status_code == 200

    async def test_moving_the_source_to_another_base_is_refused(
        self, client, fakes: _Fakes
    ) -> None:
        async with client() as opened:
            response = await opened.patch(_URL, json={"collection_name": "elsewhere"})

        assert response.status_code == 400
        fields = response.json()["error"]["details"]["fields"]
        assert [problem["field"] for problem in fields] == ["collection_name"]
        fakes.sources.update_source.assert_not_awaited()

    async def test_a_null_collection_is_refused_rather_than_detaching_the_source(
        self, client, fakes: _Fakes
    ) -> None:
        async with client() as opened:
            response = await opened.patch(_URL, json={"collection_name": None})

        assert response.status_code == 400
        fields = response.json()["error"]["details"]["fields"]
        assert [problem["field"] for problem in fields] == ["collection_name"]
        fakes.sources.update_source.assert_not_awaited()

    async def test_naming_its_own_base_is_not_a_move(self, client, fakes: _Fakes) -> None:
        async with client() as opened:
            response = await opened.patch(_URL, json={"collection_name": "handbook"})

        assert response.status_code == 200
        _, data = fakes.sources.update_source.await_args.args
        assert isinstance(data, SyncSourceUpdate)
