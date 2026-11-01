"""Neither an anonymous caller nor an ordinary account can read installation state."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api import deps
from app.core.config import settings
from app.db.models.user import User
from app.main import app
from app.repositories import diagnostics as repo

pytestmark = pytest.mark.anyio


async def test_anonymous_presence_and_status_are_refused(client):
    assert (
        await client.post("/api/v1/diagnostics/presence", json={"surface": "web"})
    ).status_code == 401
    assert (await client.get("/api/v1/admin/diagnostics")).status_code == 401


async def test_only_app_admin_sees_status_and_presence_cannot_choose_an_account(
    client, monkeypatch
):
    user = User(id=uuid4(), email="private@example.com", is_active=True, is_app_admin=False)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    monkeypatch.setattr(settings, "DIAGNOSTICS_ENABLED", False)
    monkeypatch.setattr(repo, "get", AsyncMock(return_value=None))
    assert (await client.get("/api/v1/admin/diagnostics")).status_code == 403
    assert (
        await client.post("/api/v1/diagnostics/presence", json={"surface": "web"})
    ).json() is None
    assert (
        await client.post(
            "/api/v1/diagnostics/presence", json={"surface": "web", "user_id": str(uuid4())}
        )
    ).status_code == 422
    user.is_app_admin = True
    response = await client.get("/api/v1/admin/diagnostics")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert user.email not in response.text
