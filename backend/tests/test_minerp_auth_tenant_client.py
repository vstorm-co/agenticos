"""Auth internal tenant name client."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.clients.minerp_auth_tenant import fetch_minerp_tenant_display_name
from app.core.config import settings

pytestmark = pytest.mark.anyio


async def test_fetch_display_name_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MINERP_AUTH_TENANT_LOOKUP_ENABLED", False)
    assert await fetch_minerp_tenant_display_name(uuid4()) is None


async def test_fetch_display_name_success(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(settings, "MINERP_AUTH_TENANT_LOOKUP_ENABLED", True)
    monkeypatch.setattr(settings, "MINERP_AUTH_INTERNAL_API_KEY", "test-key")
    monkeypatch.setattr(settings, "IAM_AUTH_INTERNAL_BASE_URL", "http://auth.test")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
            assert str(tenant_id) in url
            assert headers[settings.API_KEY_HEADER] == "test-key"
            return httpx.Response(200, json={"name": "Shop Alpha"})

    monkeypatch.setattr("app.clients.minerp_auth_tenant.httpx.AsyncClient", FakeClient)
    assert await fetch_minerp_tenant_display_name(tenant_id) == "Shop Alpha"
