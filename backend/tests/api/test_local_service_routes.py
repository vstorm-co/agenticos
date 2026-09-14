"""The local-services routes, over the wire.

The permission gates are proven in `test_platform_routes.py`; what is left for a
route test is the shape - the listing envelope, the 201, the 204 - and that a
refusal the service raises reaches the client as the field problem a form marks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.local_service import LocalService
from app.main import app
from app.services.local_service import LocalServiceService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_V1 = settings.API_V1_STR
_REPO = "app.services.local_service.local_service_repo"


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORG,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_local_service_service] = lambda: LocalServiceService(
        MagicMock()
    )
    yield
    app.dependency_overrides.clear()


def _row(**overrides: object) -> LocalService:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "kind": "embedding",
        "provider": "ollama",
        "name": "GPU box",
        "base_url": "http://ollama:11434/v1",
        "is_active": True,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }
    return LocalService(**{**fields, **overrides})


async def test_the_listing_carries_the_organizations_rows_and_the_deployments(
    client: AsyncClient,
) -> None:
    rows = [_row(), _row(organization_id=None, name="Deployment Ollama")]
    with patch(f"{_REPO}.list_visible", new=AsyncMock(return_value=rows)):
        response = await client.get(f"{_V1}/local-services")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["organization_id"] for item in body["items"]] == [str(_ORG), None]


async def test_registering_answers_201_with_the_row(client: AsyncClient) -> None:
    with (
        patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
        patch(f"{_REPO}.create", new=AsyncMock(return_value=_row())),
        patch("app.services.local_service.record_audit", new=AsyncMock()),
    ):
        response = await client.post(
            f"{_V1}/local-services",
            json={
                "name": "GPU box",
                "kind": "embedding",
                "provider": "ollama",
                "base_url": "http://ollama:11434/v1",
            },
        )

    assert response.status_code == 201
    assert response.json()["provider"] == "ollama"


async def test_a_provider_that_does_not_fit_the_kind_is_a_field_problem(
    client: AsyncClient,
) -> None:
    """In the shape `fieldProblems` reads, so the select that named it is marked."""
    response = await client.post(
        f"{_V1}/local-services",
        json={
            "name": "GPU box",
            "kind": "embedding",
            "provider": "openai",
            "base_url": "http://ollama:11434/v1",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["field"] == "provider"


async def test_a_deployment_wide_row_from_an_organization_operator_is_refused(
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"{_V1}/local-services",
        json={
            "name": "GPU box",
            "kind": "embedding",
            "provider": "ollama",
            "base_url": "http://ollama:11434/v1",
            "deployment_wide": True,
        },
    )

    assert response.status_code == 403


async def test_removing_answers_204(client: AsyncClient) -> None:
    row = _row()
    with (
        patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
        patch(f"{_REPO}.delete", new=AsyncMock()),
        patch("app.services.local_service.record_audit", new=AsyncMock()),
    ):
        response = await client.delete(f"{_V1}/local-services/{row.id}")

    assert response.status_code == 204


async def test_editing_answers_with_the_row(client: AsyncClient) -> None:
    row = _row()
    with (
        patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
        patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
        patch(f"{_REPO}.update", new=AsyncMock(return_value=row)),
    ):
        response = await client.patch(f"{_V1}/local-services/{row.id}", json={"name": "Bigger box"})

    assert response.status_code == 200
    assert response.json()["id"] == str(row.id)
