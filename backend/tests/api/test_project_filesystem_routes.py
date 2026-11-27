"""The machine mount API accepts only a binding bearer and never browser authority."""

import pytest
from httpx import AsyncClient

from app.api import deps
from app.main import app
from tests.test_project_filesystem_bindings import TOKEN, BindingFixture
from tests.test_project_filesystem_bindings import binding as binding
from tests.test_project_filesystem_gateway import GatewayFixture
from tests.test_project_filesystem_gateway import gateway as gateway

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-workspace-token", "Basic ignored"])
async def test_machine_proof_refuses_missing_or_unrelated_credentials(
    client: AsyncClient,
    binding: BindingFixture,
    authorization: str | None,
) -> None:
    app.dependency_overrides[deps.get_project_filesystem_binding_service] = lambda: binding.service
    headers = {} if authorization is None else {"Authorization": authorization}
    response = await client.get(
        f"/api/v1/project-filesystem/bindings/{binding.rows.binding.id}",
        headers=headers,
    )
    assert response.status_code == 401
    assert TOKEN not in response.text


async def test_proof_discloses_only_fixed_binding_identity_and_cannot_be_cached(
    client: AsyncClient,
    binding: BindingFixture,
) -> None:
    app.dependency_overrides[deps.get_project_filesystem_binding_service] = lambda: binding.service
    row = binding.rows.binding
    response = await client.get(
        f"/api/v1/project-filesystem/bindings/{row.id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "binding_id": str(row.id),
        "session_name": row.session_name,
        "tenant": str(row.organization_id),
        "mount_path": "/project",
    }
    assert TOKEN not in response.text and row.ciphertext not in response.text


async def test_filesystem_rpc_keeps_the_binding_bearer_and_bounded_request_contract(
    client: AsyncClient,
    gateway: GatewayFixture,
) -> None:
    app.dependency_overrides[deps.get_project_filesystem_gateway] = lambda: gateway.gateway
    route = f"/api/v1/project-filesystem/bindings/{gateway.rows.binding.id}/fs"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = await client.post(
        route,
        headers=headers,
        json={"op": "read", "path": f"{gateway.rows.lease.id}/file", "offset": 0, "count": 1},
    )
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"ok": True, "data": "YQ==", "eof": True}
    rejected = await client.post(
        route,
        headers=headers,
        json={"op": "read", "path": f"{gateway.rows.lease.id}/file", "count": 131073},
    )
    assert rejected.status_code == 422 and gateway.perform.await_count == 1
    unauthorized = await client.post(route, json={"op": "stat", "path": "."})
    assert unauthorized.status_code == 401
    assert gateway.perform.await_count == 1


async def test_binding_credential_cannot_create_run_leases_over_http(
    client: AsyncClient,
    binding: BindingFixture,
) -> None:
    response = await client.post(
        f"/api/v1/project-filesystem/bindings/{binding.rows.binding.id}/leases",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"project_id": str(binding.rows.lease.project_id)},
    )
    assert response.status_code == 404
