"""A connector's refusal of one config field, through the app.

The connectors decide what is wrong; what is asserted here is how the answer
*arrives*. `validate_config` used to answer `tuple[bool, str | None]`, so a
refusal that knew which field it was about lost that on the way out and the
sync-source wizard - which draws one input per `CONFIG_SCHEMA` entry - marked
none of them (#897).

The sync-source service is the real one; only the session, Redis and the
knowledge-base lookup are mocked. The config is refused before any row is
written, so nothing here reaches the database.
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
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.rag.connectors import CONNECTOR_REGISTRY, BaseSyncConnector, ConfigRefusal

pytestmark = pytest.mark.anyio

_KB_ID = uuid.uuid4()

# Well-formed enough to reach the allowlist, and refused by it: the Drive query
# language wraps a parent id in single quotes.
_HOSTILE_FOLDER_ID = "x' in parents"


class _OpinionatedConnector(BaseSyncConnector):
    """A connector that refuses without blaming a field, as one is entitled to."""

    CONNECTOR_TYPE = "opinionated"
    DISPLAY_NAME = "Opinionated"

    async def list_files(self, config: dict) -> list:  # pragma: no cover - never reached
        return []

    async def _fetch(self, file: Any, dest_path: Any, config: dict) -> None:
        """Never reached: every request in this file is refused at validation."""

    async def validate_config(self, config: dict) -> ConfigRefusal | None:
        return ConfigRefusal(message="These two credentials are not for the same account.")


class _PickyConnector(BaseSyncConnector):
    """A connector that blames a field, to pin what the service does with one."""

    CONNECTOR_TYPE = "picky"
    DISPLAY_NAME = "Picky"

    async def list_files(self, config: dict) -> list:  # pragma: no cover - never reached
        return []

    async def _fetch(self, file: Any, dest_path: Any, config: dict) -> None:
        """Never reached: every request in this file is refused at validation."""

    async def validate_config(self, config: dict) -> ConfigRefusal | None:
        return ConfigRefusal(message="That region does not exist.", field="region")


@pytest.fixture
def client(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[Any]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    kb_service = MagicMock()
    kb_service.get_for_write = AsyncMock(return_value=MagicMock(collection_name="handbook"))

    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: kb_service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


async def _create(opened: AsyncClient, connector_type: str, config: dict) -> Any:
    return await opened.post(
        f"{settings.API_V1_STR}/kb/{_KB_ID}/sync-sources",
        json={"name": "Engineering docs", "connector_type": connector_type, "config": config},
    )


class TestTheRefusalNamesTheInput:
    async def test_a_hostile_folder_id_is_blamed_on_the_field_it_was_typed_into(
        self, client
    ) -> None:
        async with client() as opened:
            response = await _create(opened, "gdrive", {"folder_id": _HOSTILE_FOLDER_ID})

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["details"]["connector_type"] == "gdrive"
        assert error["details"]["fields"] == [
            {
                "field": "config.folder_id",
                "message": (
                    "Invalid connector config: A Google Drive folder ID may contain "
                    "only letters, digits, '-' and '_'."
                ),
            }
        ]
        # One sentence, in both places - a shorter one written for the field is
        # the copy that goes stale (`app/core/field_errors.py`).
        assert error["details"]["fields"][0]["message"] == error["message"]

    async def test_the_field_is_rooted_where_the_wizard_posted_it(
        self, client, monkeypatch
    ) -> None:
        """`config` is the key the payload carries; the connector names only its own field."""
        monkeypatch.setitem(CONNECTOR_REGISTRY, "picky", _PickyConnector)

        async with client() as opened:
            response = await _create(opened, "picky", {})

        assert response.status_code == 400
        fields = response.json()["error"]["details"]["fields"]
        assert [problem["field"] for problem in fields] == ["config.region"]

    async def test_a_missing_required_field_is_blamed_on_that_field(self, client) -> None:
        async with client() as opened:
            response = await _create(opened, "s3", {})

        assert response.status_code == 400
        fields = response.json()["error"]["details"]["fields"]
        assert [problem["field"] for problem in fields] == ["config.bucket"]

    async def test_a_credential_in_the_config_is_refused_by_its_own_name(self, client) -> None:
        """The credential is a vault secret the source references, so the field
        names it used to carry are refused rather than dropped - a stripped
        credential is a source that stores and then cannot authenticate (#937)."""
        async with client() as opened:
            response = await _create(
                opened, "gdrive", {"folder_id": "1AbC", "service_account_json": "{}"}
            )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["details"]["fields"] == ["service_account_json"]
        assert "does not go in a source's configuration" in error["message"]

    async def test_a_connector_naming_no_field_still_refuses_in_words(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not every refusal is about one input, and inventing a field name for one lies."""
        monkeypatch.setitem(CONNECTOR_REGISTRY, "opinionated", _OpinionatedConnector)

        async with client() as opened:
            response = await _create(opened, "opinionated", {})

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["message"] == (
            "Invalid connector config: These two credentials are not for the same account."
        )
        assert error["details"] == {"connector_type": "opinionated"}
