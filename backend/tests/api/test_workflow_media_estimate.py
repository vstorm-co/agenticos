"""The estimate route has workflow authority and no credential/provider side effect."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.deps import get_auth_context, get_db_session
from app.api.routes.v1.workflows import router
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "permissions,allowed",
    [
        ([Perm.WORKFLOWS_VIEW], True),
        ([Perm.AGENTS_VIEW], False),
        ([Perm.SECRETS_VIEW], False),
        ([], False),
    ],
)
async def test_estimate_requires_workflow_view_and_uses_metadata_only(
    monkeypatch, permissions, allowed
):
    app = FastAPI()
    app.include_router(router, prefix="/workflows")
    ctx = AuthContext(
        user_id=uuid4(), organization_id=uuid4(), role="owner", key_scopes=frozenset(permissions)
    )
    app.dependency_overrides[get_auth_context] = lambda: ctx

    async def session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = session

    @app.exception_handler(AppException)
    async def refused(_request, error):
        return JSONResponse(status_code=error.status_code, content={"code": error.code})

    metadata = AsyncMock()
    unwrap = AsyncMock(side_effect=AssertionError("The route must not unwrap a key"))
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_secret", metadata)
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_key", unwrap)
    secret_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workflows/media-estimate",
            json={
                "kind": "image",
                "config": {
                    "provider": "openai",
                    "model": "gpt-image-1.5",
                    "secret_id": str(secret_id),
                    "max_cost_usd": 0.01,
                },
            },
        )
    assert response.status_code == (200 if allowed else 403)
    unwrap.assert_not_awaited()
    if allowed:
        body = response.json()
        assert body["reservation_usd"] == "6.109320"
        assert body["sufficient_max_cost_usd"] is False and body["deficit_usd"] == "6.099320"
        assert body["assumptions"][0] == {"code": "conservative_reservation"}
        metadata.assert_awaited_once_with(ctx, secret_id, provider="openai")
    else:
        metadata.assert_not_awaited()
        assert "reservation_usd" not in response.json()
