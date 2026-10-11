"""The Virtual Tables routes end to end: HTTP, the real service, the real database.

The unit-level route tests stub the service and the service tests skip HTTP. This is
the one place a request travels the whole way, so it is where the request's commit
boundary, the replay header and the error envelope are shown to agree with what
Postgres actually holds afterwards.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableRecordHistory
from app.main import app
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


@pytest.fixture
async def http(engine: AsyncEngine, mock_redis: MagicMock):
    """A client whose requests each get a session that commits, as `DBSession` does.

    Returns the client and a one-item list holding whose context the next requests use.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        stranger = await make_user(setup)
        other_org = await make_org(setup, owner=stranger)
        await setup.commit()
    caller: list[AuthContext] = [ctx_for(owner, org)]

    async def session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: caller[0]
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    async with open_client() as client:
        yield client, caller, ctx_for(stranger, other_org), factory
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/tables{suffix}"


async def _table(client) -> dict:
    created = await client.post(
        _url(),
        json={
            "name": "Orders",
            "columns": [
                {"label": "Customer", "type": "text"},
                {"label": "Quantity", "type": "integer"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_a_retried_create_is_replayed_and_a_stale_update_is_a_typed_conflict(http):
    client, _caller, _stranger, factory = http
    table = await _table(client)
    customer = table["columns"][0]["id"]
    records = _url(f"/{table['id']}/records")
    body = {"external_id": "A-1", "values": {customer: "Acme"}}

    first = await client.post(records, json=body, headers={"Idempotency-Key": "k-1"})
    retry = await client.post(records, json=body, headers={"Idempotency-Key": "k-1"})
    changed = await client.post(
        records, json={**body, "values": {customer: "Other"}}, headers={"Idempotency-Key": "k-1"}
    )

    assert (first.status_code, retry.status_code) == (201, 201)
    assert "idempotent-replayed" not in first.headers
    assert retry.headers["idempotent-replayed"] == "true"
    assert retry.json() == first.json()
    assert (
        changed.status_code == 422 and changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )

    record = first.json()
    good = await client.patch(
        f"{records}/{record['id']}",
        json={"expected_revision": 1, "values": {customer: "Acme 2"}},
    )
    stale = await client.patch(
        f"{records}/{record['id']}",
        json={"expected_revision": 1, "values": {customer: "Lost"}},
    )
    assert good.status_code == 200 and good.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    assert stale.json()["error"]["details"] == {
        "record_id": record["id"],
        "expected_revision": 1,
        "current_revision": 2,
    }

    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecord)) == 1
        stored = await check.scalar(select(VirtualTableRecord.values))
        assert stored == {customer: "Acme 2"}
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecordHistory)) == 2


async def test_an_upsert_creates_then_asks_for_the_revision_then_updates(http):
    client, *_ = http
    table = await _table(client)
    customer = table["columns"][0]["id"]
    url = _url(f"/{table['id']}/records/by-external-id/A-1")

    created = await client.put(url, json={"values": {customer: "Acme"}})
    missing = await client.put(url, json={"values": {customer: "Acme 2"}})
    updated = await client.put(url, json={"values": {customer: "Acme 2"}, "expected_revision": 1})

    assert (created.status_code, missing.status_code, updated.status_code) == (201, 428, 200)
    assert missing.json()["error"]["code"] == "REVISION_REQUIRED"
    assert missing.json()["error"]["details"]["current_revision"] == 1
    assert updated.json()["id"] == created.json()["id"]
    exists = await client.get(_url(f"/{table['id']}/records/exists"), params={"external_id": "A-1"})
    assert exists.json() == {"exists": True}


@pytest.mark.security
async def test_a_rejected_write_leaves_nothing_behind(http):
    client, _caller, _stranger, factory = http
    table = await _table(client)
    records = _url(f"/{table['id']}/records")

    invalid = await client.post(
        records,
        json={"external_id": "A-1", "values": {table["columns"][1]["id"]: "many"}},
        headers={"Idempotency-Key": "k"},
    )

    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "INVALID_RECORD"
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecord)) == 0


@pytest.mark.security
async def test_another_organization_sees_no_such_table_over_http(http):
    client, caller, stranger, _factory = http
    table = await _table(client)
    record = await client.post(_url(f"/{table['id']}/records"), json={"values": {}})
    caller[0] = stranger

    responses = [
        await client.get(_url(f"/{table['id']}")),
        await client.get(_url(f"/{table['id']}/records")),
        await client.get(_url(f"/{table['id']}/records/{record.json()['id']}")),
        await client.post(_url(f"/{table['id']}/records"), json={"values": {}}),
    ]
    listing = await client.get(_url())

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    assert responses[0].json()["error"]["code"] == "NOT_FOUND"
    assert listing.json() == {"items": [], "total": 0}


async def test_a_delete_over_http_keeps_the_history_and_retries_cleanly(http):
    client, _caller, _stranger, factory = http
    table = await _table(client)
    records = _url(f"/{table['id']}/records")
    record = (await client.post(records, json={"values": {}})).json()

    first = await client.delete(
        f"{records}/{record['id']}",
        params={"expected_revision": 1},
        headers={"Idempotency-Key": "d"},
    )
    retry = await client.delete(
        f"{records}/{record['id']}",
        params={"expected_revision": 1},
        headers={"Idempotency-Key": "d"},
    )
    again = await client.delete(f"{records}/{record['id']}", params={"expected_revision": 1})

    assert (first.status_code, retry.status_code, again.status_code) == (204, 204, 404)
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecord)) == 0
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecordHistory)) == 2
