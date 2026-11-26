"""The service-connections routes, over the wire.

The permission gates are proven in `test_platform_routes.py`; what is left for a
route test is the shape - the listing envelope, the 201, the 204 - and that a
refusal the service raises reaches the client as the field problem a form marks.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.service_connection import ServiceConnection
from app.main import app
from app.services.service_connection import ServiceConnectionService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_V1 = settings.API_V1_STR
_REPO = "app.services.service_connection.service_connection_repo"


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORG,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_service_connection_service] = lambda: (
        ServiceConnectionService(MagicMock())
    )
    yield
    app.dependency_overrides.clear()


def _row(**overrides: object) -> ServiceConnection:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "kind": "embedding",
        "provider": "ollama",
        "name": "GPU box",
        "base_url": "http://ollama:11434/v1",
        "is_active": True,
        "secret_id": None,
        "requires_key": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }
    return ServiceConnection(**{**fields, **overrides})


async def test_the_listing_carries_the_organizations_rows_and_the_deployments(
    client: AsyncClient,
) -> None:
    rows = [_row(), _row(organization_id=None, name="Deployment Ollama")]
    with patch(f"{_REPO}.list_visible", new=AsyncMock(return_value=rows)):
        response = await client.get(f"{_V1}/service-connections")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["organization_id"] for item in body["items"]] == [str(_ORG), None]


async def test_registering_answers_201_with_the_row(client: AsyncClient) -> None:
    with (
        patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
        patch(f"{_REPO}.create", new=AsyncMock(return_value=_row())),
        patch("app.services.service_connection.record_audit", new=AsyncMock()),
    ):
        response = await client.post(
            f"{_V1}/service-connections",
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
        f"{_V1}/service-connections",
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
        f"{_V1}/service-connections",
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
        patch("app.services.service_connection.record_audit", new=AsyncMock()),
    ):
        response = await client.delete(f"{_V1}/service-connections/{row.id}")

    assert response.status_code == 204


async def test_editing_answers_with_the_row(client: AsyncClient) -> None:
    row = _row()
    with (
        patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
        patch(f"{_REPO}.get_by_name", new=AsyncMock(return_value=None)),
        patch(f"{_REPO}.update", new=AsyncMock(return_value=row)),
        patch("app.services.service_connection.record_audit", new=AsyncMock()),
    ):
        response = await client.patch(
            f"{_V1}/service-connections/{row.id}", json={"name": "Bigger box"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(row.id)


async def test_the_old_path_is_gone(client: AsyncClient) -> None:
    response = await client.get(f"{_V1}/local-services")

    assert response.status_code == 404


async def test_a_style_in_an_edit_is_a_422(client: AsyncClient) -> None:
    response = await client.patch(
        f"{_V1}/service-connections/{uuid.uuid4()}", json={"provider": "openai_compatible"}
    )

    assert response.status_code == 422


async def test_a_keyed_connection_is_read_back_by_the_key_id_alone(client: AsyncClient) -> None:
    key = uuid.uuid4()
    row = _row(provider="openai_compatible", secret_id=key, requires_key=True)
    with patch(f"{_REPO}.list_visible", new=AsyncMock(return_value=[row])):
        response = await client.get(f"{_V1}/service-connections")

    item = response.json()["items"][0]
    assert item["secret_id"] == str(key)
    assert item["requires_key"] is True


_DOCLING = "http://docling.internal:5001"
_TEST_BODY = {"kind": "document_parser", "provider": "docling", "base_url": _DOCLING}
_PROBE = "app.services.service_connection.docling.probe"


def _as(role: str) -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORG, role=role, is_app_admin=False
    )


async def test_connection_test_answers_with_the_outcome(client: AsyncClient) -> None:
    from app.services.rag.docling import DoclingProbe

    with patch(_PROBE, new=AsyncMock(return_value=DoclingProbe("ok", "1.39.0"))):
        response = await client.post(f"{_V1}/service-connections/test", json=_TEST_BODY)

    assert response.status_code == 200
    assert response.json() == {"outcome": "ok", "version": "1.39.0"}


async def test_connection_test_requires_manage(client: AsyncClient) -> None:
    _as(OrgRoleName.VIEWER.value)
    with patch(_PROBE, new=AsyncMock()) as probe:
        response = await client.post(f"{_V1}/service-connections/test", json=_TEST_BODY)

    assert response.status_code == 403
    probe.assert_not_called()


async def test_connection_test_refuses_embedding_kind(client: AsyncClient) -> None:
    response = await client.post(
        f"{_V1}/service-connections/test",
        json={"kind": "embedding", "provider": "ollama", "base_url": "http://ollama:11434/v1"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["field"] == "kind"


@pytest.mark.security
async def test_connection_test_with_new_address_needs_key_view(client: AsyncClient) -> None:
    key = uuid.uuid4()
    row = _row(
        kind="document_parser",
        provider="docling",
        base_url=_DOCLING,
        secret_id=key,
        requires_key=True,
    )
    vault_row = MagicMock(purpose="docling")
    with (
        patch(f"{_REPO}.get_visible", new=AsyncMock(return_value=row)),
        patch(
            "app.services.service_connection.organization_secret_repo.get",
            new=AsyncMock(return_value=vault_row),
        ),
        patch("app.services.service_connection.resolve_access", new=AsyncMock(return_value=False)),
        patch(_PROBE, new=AsyncMock()) as probe,
    ):
        response = await client.post(
            f"{_V1}/service-connections/test",
            json={**_TEST_BODY, "service_id": str(row.id), "base_url": "http://elsewhere:5001"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["secret_id"] == str(key)
    probe.assert_not_called()


@pytest.mark.security
async def test_connection_test_never_returns_key_or_url_in_errors(client: AsyncClient) -> None:
    from app.services.rag.docling import DoclingProbe

    key = uuid.uuid4()
    vault_row = MagicMock(purpose="docling", kind="api_key", key_version=1)
    from app.core.secret_kinds import ApiKeySecret

    with (
        patch(
            "app.services.service_connection.organization_secret_repo.get",
            new=AsyncMock(return_value=vault_row),
        ),
        patch("app.services.service_connection.resolve_access", new=AsyncMock(return_value=True)),
        patch(
            "app.services.service_connection.unseal_secret",
            return_value=ApiKeySecret(api_key="hunter2-docling"),
        ),
        patch(_PROBE, new=AsyncMock(return_value=DoclingProbe("key_refused", None))),
    ):
        response = await client.post(
            f"{_V1}/service-connections/test", json={**_TEST_BODY, "secret_id": str(key)}
        )

    assert response.status_code == 200
    assert "hunter2-docling" not in response.text
    assert "docling.internal" not in response.text
    assert response.json() == {"outcome": "key_refused", "version": None}


async def test_connection_test_refuses_a_query_in_the_address(client: AsyncClient) -> None:
    response = await client.post(
        f"{_V1}/service-connections/test",
        json={**_TEST_BODY, "base_url": f"{_DOCLING}/?api-key=abc"},
    )

    assert response.status_code == 422
    assert "abc" not in response.text
