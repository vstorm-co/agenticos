"""Both editors read the exact media request contract without reading any key."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.deps import get_auth_context
from app.api.routes.v1.model_providers import router
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm

pytestmark = [pytest.mark.security, pytest.mark.anyio]


@pytest.mark.parametrize("path", ["/image-models", "/video-models"])
@pytest.mark.parametrize(
    "permissions,subject,allowed",
    [
        ([Perm.AGENTS_VIEW], True, True),
        ([Perm.WORKFLOWS_VIEW], True, True),
        ([], True, False),
        ([Perm.SECRETS_VIEW], True, False),
        ([Perm.WORKFLOWS_VIEW], False, False),
    ],
)
async def test_media_catalog_requires_one_editor_permission(
    path: str,
    permissions: list[Perm],
    subject: bool,
    allowed: bool,
) -> None:
    app = FastAPI()
    app.include_router(router)
    ctx = AuthContext(
        user_id=uuid4() if subject else None,
        organization_id=uuid4(),
        role="owner",
        key_scopes=frozenset(permissions),
    )
    app.dependency_overrides[get_auth_context] = lambda: ctx

    @app.exception_handler(AuthorizationError)
    async def refused(_request, _error):
        return JSONResponse(status_code=403, content={"error": "permission denied"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(path)
    assert response.status_code == (200 if allowed else 403)
    if not allowed:
        assert "items" not in response.json()
        return
    models = {row["id"]: row for provider in response.json()["items"] for row in provider["models"]}
    assert models
    if path == "/image-models":
        assert models["gpt-image-1"]["workflow"] is None
        assert models["gpt-image-2"]["workflow"] is None
        support = models["gpt-image-1.5"]["workflow"]
        assert support["reference_image"] is False
        assert support["defaults"]["size"] in support["sizes"]
        assert support["max_output_tokens"] == 8192
    else:
        for model in models.values():
            support = model["workflow"]
            assert support is not None
            assert support["defaults"]["resolution"] in support["usd_per_second"]
            assert support["defaults"]["aspect_ratio"] in model["aspect_ratios"]
            assert support["defaults"]["audio"] is (False if model["audio"] == "optional" else None)
