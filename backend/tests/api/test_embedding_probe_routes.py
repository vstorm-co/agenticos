"""The embedding-test routes, over the wire.

Their gates are proven in `test_platform_routes.py`, and what a test decides in
`test_embedding_probe.py`. What is left for a route is the shape: a failed test is a
200 the form can show, the estimate is a plain GET that sends nothing, and the new
paths are not mistaken for a knowledge base's id.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.embedding_probe import EmbeddingProbeEstimate, EmbeddingProbeResult

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_V1 = settings.API_V1_STR
_ID = uuid.uuid4()


def _as(role: OrgRoleName) -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORG, role=role.value, is_app_admin=False
    )


@pytest.fixture(autouse=True)
def service() -> AsyncMock:
    mocked = AsyncMock()
    app.dependency_overrides[deps.get_embedding_probe_service] = lambda: mocked
    _as(OrgRoleName.OWNER)
    yield mocked
    app.dependency_overrides.clear()


def _result(**overrides: object) -> EmbeddingProbeResult:
    fields: dict[str, object] = {
        "passed": True,
        "outcome": "passed",
        "dim": 768,
        "calls": 1,
        "knowledge_bases": [],
        "probe_token": "signed",
        "expires_at": datetime(2026, 11, 25, tzinfo=UTC),
    }
    return EmbeddingProbeResult(**(fields | overrides))  # type: ignore[arg-type]


_NEW = {"embedding_endpoint_id": str(_ID), "embedding_model": "corp-embed", "scope": "org"}


@pytest.mark.security
async def test_the_create_probe_needs_collections_edit(
    client: AsyncClient, service: AsyncMock
) -> None:
    _as(OrgRoleName.VIEWER)

    response = await client.post(f"{_V1}/kb/embedding-probe", json=_NEW)

    assert response.status_code == 403
    service.measure_new.assert_not_awaited()


async def test_the_create_probe_answers_the_measured_width(
    client: AsyncClient, service: AsyncMock
) -> None:
    service.measure_new.return_value = _result()

    response = await client.post(f"{_V1}/kb/embedding-probe", json=_NEW)

    assert response.status_code == 200
    assert response.json()["dim"] == 768
    assert response.json()["probe_token"] == "signed"
    assert service.measure_new.await_args.args[1].embedding_model == "corp-embed"


async def test_the_kb_probe_answers_a_failure_as_200_with_passed_false(
    client: AsyncClient, service: AsyncMock
) -> None:
    service.probe_kb_change.return_value = _result(
        passed=False, outcome="vectors_differ", probe_token=None, expires_at=None
    )

    response = await client.post(
        f"{_V1}/kb/{_ID}/embedding-probe", json={"embedding_model": "other"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["passed"], body["outcome"], body["probe_token"]) == (False, "vectors_differ", None)
    kb_id, request = service.probe_kb_change.await_args.args[1:]
    assert (kb_id, request.model_fields_set) == (_ID, {"embedding_model"})


async def test_the_kb_estimate_is_a_get_that_reports_the_calls(
    client: AsyncClient, service: AsyncMock
) -> None:
    service.estimate_kb_change.return_value = EmbeddingProbeEstimate(
        calls=3, max_calls=6, knowledge_bases=1
    )

    response = await client.get(f"{_V1}/kb/{_ID}/embedding-probe/estimate")

    assert response.status_code == 200
    assert response.json() == {"calls": 3, "max_calls": 6, "knowledge_bases": 1}


@pytest.mark.security
async def test_the_connection_probe_needs_connections_manage(
    client: AsyncClient, service: AsyncMock
) -> None:
    _as(OrgRoleName.VIEWER)

    probed = await client.post(f"{_V1}/service-connections/{_ID}/probe", json={})
    estimated = await client.get(f"{_V1}/service-connections/{_ID}/probe/estimate")

    assert (probed.status_code, estimated.status_code) == (403, 403)
    service.probe_connection_change.assert_not_awaited()


async def test_the_connection_probe_and_its_estimate_delegate(
    client: AsyncClient, service: AsyncMock
) -> None:
    service.probe_connection_change.return_value = _result()
    service.estimate_connection_change.return_value = EmbeddingProbeEstimate(
        calls=0, max_calls=0, knowledge_bases=0
    )

    probed = await client.post(
        f"{_V1}/service-connections/{_ID}/probe", json={"base_url": "https://new.example/v1"}
    )
    estimated = await client.get(f"{_V1}/service-connections/{_ID}/probe/estimate")

    assert probed.status_code == 200
    assert service.probe_connection_change.await_args.args[2].base_url == "https://new.example/v1"
    assert estimated.json()["calls"] == 0


@pytest.mark.security
async def test_a_connection_address_with_a_query_string_is_refused_in_the_probe(
    client: AsyncClient, service: AsyncMock
) -> None:
    response = await client.post(
        f"{_V1}/service-connections/{_ID}/probe", json={"base_url": "https://gw.example/v1?key=sk"}
    )

    assert response.status_code == 422
    service.probe_connection_change.assert_not_awaited()
