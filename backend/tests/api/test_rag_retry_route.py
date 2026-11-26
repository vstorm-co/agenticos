"""What the retry route hands the service: the pending upload departures, if any."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.ingestion_config import IngestionOverride

pytestmark = pytest.mark.anyio

_DOC = uuid.uuid4()
_URL = f"{settings.API_V1_STR}/rag/documents/{_DOC}/retry"


@pytest.fixture
def service() -> MagicMock:
    retried = SimpleNamespace(id=_DOC)
    svc = MagicMock(retry_ingestion=AsyncMock(return_value=retried))
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_collection_access_service] = lambda: MagicMock(
        writable_document=AsyncMock(return_value=SimpleNamespace(id=_DOC))
    )
    app.dependency_overrides[deps.get_rag_document_service] = lambda: svc
    return svc


async def test_a_retry_with_no_body_keeps_the_files_own_settings(
    client: AsyncClient, service: MagicMock
) -> None:
    response = await client.post(_URL)

    assert response.status_code == 200
    service.retry_ingestion.assert_awaited_once_with(str(_DOC), override=None)


async def test_a_retry_carries_the_pending_upload_departures(
    client: AsyncClient, service: MagicMock
) -> None:
    response = await client.post(_URL, json={"ingestion_override": {"ocr": True}})

    assert response.status_code == 200
    service.retry_ingestion.assert_awaited_once_with(
        str(_DOC), override=IngestionOverride(ocr=True)
    )


async def test_a_retry_refuses_a_departure_it_does_not_know(
    client: AsyncClient, service: MagicMock
) -> None:
    response = await client.post(_URL, json={"ingestion_override": {"embedding_model": "x"}})

    assert response.status_code == 422
    service.retry_ingestion.assert_not_awaited()


@pytest.mark.parametrize("body", [{}, {"ingestion_override": None}, {"ingestion_override": {}}])
async def test_a_retry_with_a_body_but_nothing_pending_uses_the_collections_settings(
    client: AsyncClient, service: MagicMock, body: dict[str, object]
) -> None:
    response = await client.post(_URL, json=body)

    assert response.status_code == 200
    service.retry_ingestion.assert_awaited_once_with(str(_DOC), override=IngestionOverride())
