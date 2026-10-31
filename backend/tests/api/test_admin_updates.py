"""Deployment updates are never available to an ordinary organization member."""

from uuid import uuid4

import pytest

from app.api import deps
from app.core.config import settings
from app.db.models.user import User
from app.main import app

pytestmark = pytest.mark.anyio


async def test_every_update_action_requires_app_administration(client, monkeypatch):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", None)
    user = User(id=uuid4(), email="private@example.com", is_active=True, is_app_admin=False)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    for path, data in (
        ("prepare", {"version": "1.33.0"}),
        ("apply", {"id": "a" * 32}),
        ("cancel", {"id": "a" * 32}),
    ):
        assert (await client.post(f"/api/v1/admin/updates/{path}", json=data)).status_code == 403
    assert (await client.get("/api/v1/admin/updates")).status_code == 403
    user.is_app_admin = True
    status = await client.get("/api/v1/admin/updates")
    assert status.status_code == 200 and status.json()["configured"] is False
    assert (
        await client.post("/api/v1/admin/updates/prepare", json={"version": "main; rm -rf /"})
    ).status_code == 422
    assert (
        await client.post("/api/v1/admin/updates/apply", json={"id": "../../etc/passwd"})
    ).status_code == 422
