"""The public API's OpenAPI document agrees with the routes a key may call (#1796)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from httpx import ASGITransport, AsyncClient

from app.api.public_api import (
    INTERNAL,
    PUBLIC,
    public_openapi,
    public_operations,
)
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


@pytest.fixture
async def document() -> dict[str, Any]:
    app.state.public_openapi = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get(f"{settings.API_V1_STR}/public/openapi.json")
    assert response.status_code == 200
    return response.json()


async def test_it_is_served_without_a_credential_and_holds_only_public_routes(
    document: dict[str, Any],
) -> None:
    paths = document["paths"]

    assert f"{settings.API_V1_STR}/agents" in paths
    assert f"{settings.API_V1_STR}/kb/{{kb_id}}/documents" in paths
    # Console-only routes, and key management, are not part of the contract.
    assert f"{settings.API_V1_STR}/api-keys" not in paths
    assert f"{settings.API_V1_STR}/users/me" not in paths
    assert f"{settings.API_V1_STR}/orgs/{{org_id}}/leave" not in paths
    # A directory on the deployment's own disk is never a key's to point at.
    assert f"{settings.API_V1_STR}/rag/sync/local" not in paths
    assert "compatibility" in document["info"]["description"].lower()


async def test_every_reference_resolves_inside_the_document(document: dict[str, Any]) -> None:
    schemas = document["components"]["schemas"]

    for ref in _refs(document["paths"]) | _refs(schemas):
        assert ref.removeprefix("#/components/schemas/") in schemas, ref
    assert "HTTPValidationError" not in schemas


async def test_every_operation_needs_a_key_and_answers_the_error_envelope(
    document: dict[str, Any],
) -> None:
    envelope = {"$ref": "#/components/schemas/ErrorEnvelope"}

    for operations in document["paths"].values():
        for operation in operations.values():
            assert operation["security"] == [{"ApiKey": []}]
            for code in ("401", "403", "404", "422", "429"):
                schema = operation["responses"][code]["content"]["application/json"]["schema"]
                assert schema == envelope
    assert document["components"]["securitySchemes"]["ApiKey"]["scheme"] == "bearer"


async def test_the_document_is_built_once_per_process() -> None:
    app.state.public_openapi = {"cached": True}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            response = await http.get(f"{settings.API_V1_STR}/public/openapi.json")
        assert response.json() == {"cached": True}
    finally:
        app.state.public_openapi = None


def test_a_route_mounted_directly_on_an_app_is_read_too() -> None:
    """Not every route arrives through `include_router`; one declared on the app
    itself, or opted out with `INTERNAL`, is answered from the route alone."""
    small = FastAPI()
    router = APIRouter(dependencies=[PUBLIC])

    @router.get("/public-thing")
    async def public_thing() -> dict[str, str]:
        return {}

    @router.get("/console-thing", openapi_extra=INTERNAL)
    async def console_thing() -> dict[str, str]:
        return {}

    @small.get("/bare", dependencies=[PUBLIC])
    async def bare() -> dict[str, str]:
        return {}

    small.include_router(router, prefix="/v1")

    operations = public_operations(small.routes)
    document = public_openapi(get_openapi(title="t", version="1", routes=small.routes), operations)

    assert ("get", "/v1/public-thing") in operations
    assert ("get", "/bare") in operations
    assert ("get", "/v1/console-thing") not in operations
    assert set(document["paths"]) == {"/v1/public-thing", "/bare"}
