"""External table clients use real organization keys and the console's service (#1795)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import VirtualTableOutbox, VirtualTableRecord
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.schemas.virtual_table import ColumnInput, RecordList, TableCreate, TableRead
from app.services.api_key import ApiKeyService
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


@dataclass
class _Client:
    http: AsyncClient
    ctx: AuthContext
    table: TableRead
    key: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    @property
    def url(self) -> str:
        return f"{settings.API_V1_STR}/tables/{self.table.id}"


@pytest.fixture
async def external(db: AsyncSession, mock_redis: MagicMock) -> AsyncIterator[_Client]:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    table = await VirtualTableService(db).create_table(
        ctx,
        TableCreate(name="Leads", columns=[ColumnInput(label="Email", type="text")]),
    )
    key = await ApiKeyService(db).create(
        ctx, ApiKeyCreate(name="importer", scopes=[Perm.TABLES_VIEW, Perm.TABLES_EDIT])
    )

    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield _Client(http, ctx, table, key.key)
    finally:
        app.dependency_overrides.clear()


async def test_external_crud_replays_without_another_created_event(
    db: AsyncSession, external: _Client
) -> None:
    column = str(external.table.columns[0].id)
    url = f"{external.url}/records"
    body = {"external_id": "crm/42", "values": {column: "ada@example.com"}}
    headers = {**external.headers, "Idempotency-Key": "lead-42"}
    first = await external.http.post(url, json=body, headers=headers)
    retry = await external.http.post(url, json=body, headers=headers)
    assert first.status_code == retry.status_code == 201, first.text
    assert retry.json() == first.json()
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert await db.scalar(select(func.count()).select_from(VirtualTableOutbox)) == 1
    record_id = uuid.UUID(first.json()["id"])
    console = await VirtualTableService(db).get_record(external.ctx, external.table.id, record_id)
    assert console.values == body["values"]
    updated = await external.http.patch(
        f"{url}/{record_id}",
        json={"expected_revision": 1, "values": {column: "grace@example.com"}},
        headers=external.headers,
    )
    stale = await external.http.patch(
        f"{url}/{record_id}",
        json={"expected_revision": 1, "values": {column: "lost@example.com"}},
        headers=external.headers,
    )
    assert updated.status_code == 200, updated.text
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    deleted = await external.http.delete(
        f"{url}/{record_id}", params={"expected_revision": 2}, headers=external.headers
    )
    assert deleted.status_code == 204, deleted.text
    assert await db.scalar(select(func.count()).select_from(VirtualTableRecord)) == 0


async def test_upsert_filter_sort_paging_and_bounded_field_selection(
    db: AsyncSession, external: _Client
) -> None:
    column = str(external.table.columns[0].id)
    url = f"{external.url}/records/by-external-id/crm/42"
    body = {"values": {column: "ada@example.com"}}
    headers = {**external.headers, "Idempotency-Key": "upsert-42"}
    created = await external.http.put(url, json=body, headers=headers)
    replay = await external.http.put(url, json=body, headers=headers)
    assert created.status_code == replay.status_code == 201, created.text
    assert replay.headers["Idempotent-Replayed"] == "true"
    required = await external.http.put(url, json=body, headers=external.headers)
    assert required.status_code == 428
    page = await external.http.post(
        f"{external.url}/records/query",
        json={
            "columns": [column],
            "filters": [{"column_id": column, "op": "contains", "value": "@example.com"}],
            "sort": {"by": column, "direction": "desc"},
            "skip": 0,
            "limit": 1,
        },
        headers=external.headers,
    )
    assert page.status_code == 200, page.text
    listed = RecordList.model_validate(page.json())
    assert [item.values for item in listed.items] == [body["values"]]
    empty_fields = await external.http.post(
        f"{external.url}/records/query", json={"columns": []}, headers=external.headers
    )
    assert empty_fields.status_code == 200, empty_fields.text
    assert empty_fields.json()["items"][0]["values"] == {}
    invalid = await external.http.post(
        f"{external.url}/records/query",
        json={"columns": [str(uuid.uuid4())]},
        headers=external.headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_QUERY"
    too_many = await external.http.post(
        f"{external.url}/records/query", json={"columns": [column] * 101}, headers=external.headers
    )
    assert too_many.status_code == 422


@pytest.mark.security
async def test_key_scopes_and_tenants_are_enforced_without_auth_overrides(
    db: AsyncSession, external: _Client
) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    other = await ApiKeyService(db).create(
        ctx_for(owner, org), ApiKeyCreate(name="other", scopes=[Perm.TABLES_VIEW, Perm.TABLES_EDIT])
    )
    read_only = await ApiKeyService(db).create(
        external.ctx, ApiKeyCreate(name="reader", scopes=[Perm.TABLES_VIEW])
    )
    for method, suffix, body in [("GET", "", None), ("POST", "/records", {"values": {}})]:
        refused = await external.http.request(
            method,
            f"{external.url}{suffix}",
            json=body,
            headers={"Authorization": f"Bearer {other.key}"},
        )
        assert refused.status_code == 404, refused.text
    refused = await external.http.post(
        f"{external.url}/records",
        json={"values": {}},
        headers={"Authorization": f"Bearer {read_only.key}"},
    )
    assert refused.status_code == 404, refused.text
    await ApiKeyService(db).revoke(external.ctx, read_only.id)
    revoked = await external.http.get(
        external.url, headers={"Authorization": f"Bearer {read_only.key}"}
    )
    assert revoked.status_code == 401, revoked.text


async def test_projection_calculates_formulas_without_returning_their_inputs(
    db: AsyncSession, external: _Client
) -> None:
    service = VirtualTableService(db)
    table = await service.create_table(
        external.ctx,
        TableCreate(
            name="Quotes",
            columns=[
                ColumnInput(label="Price", type="number"),
                ColumnInput(label="Quantity", type="integer"),
                ColumnInput(label="Total", type="formula", formula="{Price} * {Quantity}"),
            ],
        ),
    )
    price, quantity, total = [str(column.id) for column in table.columns]
    created = await external.http.post(
        f"{settings.API_V1_STR}/tables/{table.id}/records",
        json={"values": {price: 2.5, quantity: 4}},
        headers=external.headers,
    )
    assert created.status_code == 201, created.text
    page = await external.http.post(
        f"{settings.API_V1_STR}/tables/{table.id}/records/query",
        json={"columns": [total]},
        headers=external.headers,
    )
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["values"] == {total: 10}
    assert page.json()["items"][0]["links"] == {}
