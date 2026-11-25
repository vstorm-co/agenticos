"""The route contract for /me/nav-pins.

The service is stubbed; under test is what the routes own: the caller's ids
(never a request field) reach the service, the write shape is closed, and an
organization API key is refused before anything is read. Isolation through a
real database is tests/integration/test_nav_pins.py.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.main import app
from app.schemas.nav_pins import MAX_NAV_PINS
from app.services.api_key import KEY_PREFIX

pytestmark = pytest.mark.anyio

_USER_ID = uuid4()
_ORG_ID = uuid4()


def _service(saved: list[str] | None = None) -> MagicMock:
    service = MagicMock()
    service.get_for_user = AsyncMock(return_value=saved or [])
    service.replace = AsyncMock(side_effect=lambda **kw: kw["data"].item_ids)
    return service


@asynccontextmanager
async def _client(service: MagicMock, *, signed_in: bool = True) -> AsyncIterator[AsyncClient]:
    if signed_in:
        app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(id=_USER_ID)
        app.dependency_overrides[deps.get_active_organization] = lambda: MagicMock(id=_ORG_ID)
    app.dependency_overrides[deps.get_nav_pins_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_no_saved_pins_reads_as_an_empty_list() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.get("/api/v1/me/nav-pins")
    assert resp.status_code == 200
    assert resp.json() == {"item_ids": []}
    assert service.get_for_user.call_args.kwargs == {
        "user_id": _USER_ID,
        "organization_id": _ORG_ID,
    }


async def test_saved_pins_come_back_in_order() -> None:
    service = _service(["agentMessages", "runs"])
    async with _client(service) as client:
        resp = await client.get("/api/v1/me/nav-pins")
    assert resp.json() == {"item_ids": ["agentMessages", "runs"]}


async def test_replacing_pins_uses_the_callers_user_and_active_org() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put("/api/v1/me/nav-pins", json={"item_ids": ["runs", "agents"]})
    assert resp.status_code == 200
    assert resp.json() == {"item_ids": ["runs", "agents"]}
    kwargs = service.replace.call_args.kwargs
    assert (kwargs["user_id"], kwargs["organization_id"]) == (_USER_ID, _ORG_ID)


@pytest.mark.parametrize(
    "body",
    [
        {"item_ids": ["1runs"]},
        {"item_ids": ["bad_id"]},
        {"item_ids": ["has space"]},
        {"item_ids": ["a" * 65]},
        {"item_ids": ["runs", "runs"]},
        {"item_ids": [f"item{n}" for n in range(MAX_NAV_PINS + 1)]},
        {"item_ids": ["runs"], "user_id": str(uuid4())},
        {"item_ids": ["runs"], "organization_id": str(uuid4())},
        {},
    ],
)
async def test_a_malformed_write_is_refused_and_not_stored(body: dict[str, object]) -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put("/api/v1/me/nav-pins", json=body)
    assert resp.status_code == 422
    service.replace.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_an_organization_api_key_is_refused(method: str) -> None:
    service = _service()
    async with _client(service, signed_in=False) as client:
        resp = await client.request(
            method,
            "/api/v1/me/nav-pins",
            headers={"Authorization": f"Bearer {KEY_PREFIX}notarealkey"},
            json={"item_ids": ["runs"]} if method == "PUT" else None,
        )
    assert resp.status_code == 403
    service.get_for_user.assert_not_called()
    service.replace.assert_not_called()
