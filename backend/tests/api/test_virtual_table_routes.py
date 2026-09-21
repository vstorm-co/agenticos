"""The Virtual Tables routes, through the app: the wire contract other components build on.

`tests/api/test_platform_routes.py` proves the collection routes are gated and the
per-table routes delegate to the service; `tests/integration/test_virtual_table_*.py`
proves what the service does against a database. What is left is the wire itself:
status codes, the replay header, the error envelope a client branches on, request
validation, and the OpenAPI document Kacper's external API is generated from.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.virtual_table import (
    RecordExists,
    RecordList,
    RecordQuery,
    RecordRead,
    TableList,
    TableRead,
)
from app.services.virtual_tables import RecordWrite
from app.services.virtual_tables.exceptions import (
    IdempotencyKeyReuseError,
    InvalidRecordError,
    RevisionConflictError,
    RevisionRequiredError,
    SchemaDependencyError,
    TableArchivedError,
)

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_TABLE = uuid.uuid4()
_RECORD = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _record(revision: int = 1) -> RecordRead:
    return RecordRead(
        id=_RECORD,
        table_id=_TABLE,
        external_id="A-1",
        schema_version=1,
        values={"c": "x"},
        revision=revision,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


def _table() -> TableRead:
    return TableRead(
        id=_TABLE,
        name="Orders",
        visibility="private",
        schema_version=1,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
        columns=[],
    )


@pytest.fixture
def service() -> MagicMock:
    return MagicMock(
        create_table=AsyncMock(return_value=_table()),
        list_tables=AsyncMock(
            return_value=TableList(items=[], total=0),
        ),
        describe_table=AsyncMock(return_value=_table()),
        update_table=AsyncMock(return_value=_table()),
        archive_table=AsyncMock(return_value=_table()),
        update_schema=AsyncMock(return_value=_table()),
        list_schema_versions=AsyncMock(return_value={"items": []}),
        list_records=AsyncMock(return_value=RecordList(items=[], skip=0, limit=50, has_more=False)),
        record_exists=AsyncMock(return_value=True),
        get_record=AsyncMock(return_value=_record()),
        get_record_by_external_id=AsyncMock(return_value=_record()),
        create_record=AsyncMock(
            return_value=RecordWrite(record=_record(), created=True, replayed=False)
        ),
        update_record=AsyncMock(
            return_value=RecordWrite(record=_record(2), created=False, replayed=False)
        ),
        upsert_record=AsyncMock(
            return_value=RecordWrite(record=_record(), created=True, replayed=False)
        ),
        delete_record=AsyncMock(return_value=None),
    )


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_virtual_table_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/tables{suffix}"


def _records(suffix: str = "") -> str:
    return _url(f"/{_TABLE}/records{suffix}")


async def test_a_table_is_created_with_201_and_listed_with_its_total(client, service):
    async with client() as http:
        created = await http.post(_url(), json={"name": "Orders", "columns": []})
        listed = await http.get(_url(), params={"q": "ord", "include_archived": "true"})

    assert created.status_code == 201 and created.json()["name"] == "Orders"
    assert listed.json() == {"items": [], "total": 0}
    assert service.list_tables.await_args.kwargs == {
        "include_archived": True,
        "search": "ord",
        "skip": 0,
        "limit": 50,
    }


async def test_the_per_table_routes_answer_with_the_table(client):
    async with client() as http:
        responses = [
            await http.get(_url(f"/{_TABLE}")),
            await http.patch(_url(f"/{_TABLE}"), json={"name": "Renamed"}),
            await http.post(_url(f"/{_TABLE}/archive")),
            await http.put(_url(f"/{_TABLE}/schema"), json={"expected_version": 1, "columns": []}),
        ]
        versions = await http.get(_url(f"/{_TABLE}/schema-versions"))

    assert [r.status_code for r in responses] == [200, 200, 200, 200]
    assert versions.json() == {"items": []}


async def test_creating_a_record_is_a_201_and_passes_the_operation_key_through(client, service):
    async with client() as http:
        response = await http.post(
            _records(),
            json={"external_id": "A-1", "values": {"c": "x"}},
            headers={"Idempotency-Key": "import-17"},
        )

    assert response.status_code == 201
    assert "idempotent-replayed" not in response.headers
    assert response.json()["revision"] == 1
    assert service.create_record.await_args.kwargs == {"operation_key": "import-17"}


async def test_a_replayed_write_says_so_in_a_header(client, service):
    service.create_record.return_value = RecordWrite(record=_record(), created=True, replayed=True)

    async with client() as http:
        response = await http.post(
            _records(), json={"values": {}}, headers={"Idempotency-Key": "k"}
        )

    assert response.status_code == 201
    assert response.headers["idempotent-replayed"] == "true"


async def test_an_upsert_is_201_when_it_creates_and_200_when_it_updates(client, service):
    async with client() as http:
        created = await http.put(_records("/by-external-id/A-1"), json={"values": {}})
        service.upsert_record.return_value = RecordWrite(
            record=_record(2), created=False, replayed=False
        )
        updated = await http.put(
            _records("/by-external-id/A-1"), json={"values": {}, "expected_revision": 1}
        )

    assert (created.status_code, updated.status_code) == (201, 200)
    assert service.upsert_record.await_args.args[2:3] == ("A-1",)


async def test_an_update_is_200_and_needs_its_expected_revision(client, service):
    async with client() as http:
        ok = await http.patch(
            _records(f"/{_RECORD}"), json={"expected_revision": 1, "values": {"c": "y"}}
        )
        missing = await http.patch(_records(f"/{_RECORD}"), json={"values": {}})
        misspelled = await http.patch(
            _records(f"/{_RECORD}"), json={"expected_revison": 1, "values": {}}
        )

    assert ok.status_code == 200 and ok.json()["revision"] == 2
    assert missing.status_code == 422 and misspelled.status_code == 422
    assert service.update_record.await_count == 1


async def test_a_delete_is_204_and_needs_its_expected_revision(client, service):
    async with client() as http:
        deleted = await http.delete(_records(f"/{_RECORD}"), params={"expected_revision": 3})
        missing = await http.delete(_records(f"/{_RECORD}"))

    assert deleted.status_code == 204 and deleted.content == b""
    assert missing.status_code == 422
    assert service.delete_record.await_args.kwargs["expected_revision"] == 3


async def test_the_literal_record_routes_are_not_swallowed_by_the_record_id_route(client):
    async with client() as http:
        exists = await http.get(_records("/exists"), params={"external_id": "A-1"})
        by_key = await http.get(_records("/by-external-id/A-1"))
        one = await http.get(_records(f"/{_RECORD}"))

    assert exists.json() == RecordExists(exists=True).model_dump()
    assert by_key.status_code == 200 and one.status_code == 200


async def test_listing_and_querying_records_hand_the_service_one_bounded_query(client, service):
    body = {
        "filters": [{"column_id": str(uuid.uuid4()), "op": "gte", "value": 3}],
        "sort": {"by": "updated_at", "direction": "desc"},
        "skip": 5,
        "limit": 10,
    }
    async with client() as http:
        plain = await http.get(
            _records(), params={"sort": "updated_at", "direction": "desc", "skip": 5, "limit": 10}
        )
        queried = await http.post(_records("/query"), json=body)
        too_many = await http.get(_records(), params={"limit": 101})
        too_deep = await http.post(_records("/query"), json={"skip": 10_001})

    assert plain.status_code == queried.status_code == 200
    assert (too_many.status_code, too_deep.status_code) == (422, 422)
    listed, searched = (call.args[2] for call in service.list_records.await_args_list)
    assert isinstance(listed, RecordQuery)
    assert (listed.sort.by, listed.sort.direction, listed.skip, listed.limit) == (
        "updated_at",
        "desc",
        5,
        10,
    )
    assert searched.filters[0].op == "gte" and searched.skip == 5


async def test_every_refusal_answers_in_the_one_envelope_with_its_own_code(client, service):
    record_id = uuid.uuid4()
    cases: list[tuple[Any, int, str, dict[str, Any]]] = [
        (
            RevisionConflictError(record_id=record_id, expected_revision=1, current_revision=4),
            409,
            "REVISION_CONFLICT",
            {"record_id": str(record_id), "expected_revision": 1, "current_revision": 4},
        ),
        (
            RevisionRequiredError(record_id=record_id, current_revision=4),
            428,
            "REVISION_REQUIRED",
            {"record_id": str(record_id), "current_revision": 4},
        ),
        (InvalidRecordError([("values.x", "Expected text")]), 422, "INVALID_RECORD", {}),
        (TableArchivedError(table_id=_TABLE), 409, "TABLE_ARCHIVED", {"table_id": str(_TABLE)}),
        (IdempotencyKeyReuseError(operation="record.create"), 422, "IDEMPOTENCY_KEY_REUSED", {}),
        (SchemaDependencyError([{"kind": "view", "id": record_id}]), 409, "SCHEMA_DEPENDENCY", {}),
    ]
    async with client() as http:
        for error, status_code, code, details in cases:
            service.update_record.side_effect = error
            response = await http.patch(
                _records(f"/{_RECORD}"), json={"expected_revision": 1, "values": {}}
            )
            body = response.json()
            assert response.status_code == status_code
            assert list(body) == ["error"]
            assert body["error"]["code"] == code
            assert details.items() <= (body["error"]["details"] or {}).items()


def test_the_openapi_document_types_the_write_contract():
    document = app.openapi()

    path = document["paths"][f"{settings.API_V1_STR}/tables/{{table_id}}/records/{{record_id}}"]
    patch = path["patch"]
    assert patch["responses"]["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert {"idempotency-key"} <= {p["name"] for p in patch["parameters"]}
    request = document["components"]["schemas"]["RecordUpdate"]
    assert set(request["required"]) == {"expected_revision", "values"}
    assert request["additionalProperties"] is False
    assert {"created_at", "updated_at"} <= set(
        document["components"]["schemas"]["RecordRead"]["properties"]
    )
    upsert = document["paths"][
        f"{settings.API_V1_STR}/tables/{{table_id}}/records/by-external-id/{{external_id}}"
    ]["put"]
    assert {"200", "201", "428"} <= set(upsert["responses"])
