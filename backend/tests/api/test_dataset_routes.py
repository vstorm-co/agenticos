"""The dataset routes, through the app.

`tests/api/test_platform_routes.py` proves the collection routes are gated and
the per-dataset routes delegate to the service; `tests/integration/test_datasets.py`
proves what the service does against Postgres. What is left is the HTTP layer
itself: which status each route answers with, that an upload reaches the service
as the bytes and name it was sent with, that `format` is the query parameter a
client writes, and that an export downloads as a file of the right type.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.dataset import (
    NO_EXPECTATION,
    DatasetCaseList,
    DatasetCaseRead,
    DatasetList,
    DatasetRead,
    DatasetVersionList,
    DatasetVersionRead,
)
from app.services.dataset_files import MAX_IMPORT_BYTES
from app.services.exporting import ExportResult

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_NOW = datetime(2026, 10, 13, tzinfo=UTC)
_DATASET = DatasetRead(
    id=uuid.uuid4(),
    name="refunds",
    visibility="private",
    latest_version=1,
    case_count=1,
    can_edit=True,
    created_at=_NOW,
)
_CASE = DatasetCaseRead(
    id=uuid.uuid4(), case_id=uuid.uuid4(), input="q", source="manual", created_at=_NOW
)
_VERSION = DatasetVersionRead(
    id=uuid.uuid4(), number=2, case_count=3, change="import", changed_cases=2, created_at=_NOW
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_readable = AsyncMock(return_value=DatasetList(items=[_DATASET], total=1))
    stub.create = AsyncMock(return_value=_DATASET)
    stub.read = AsyncMock(return_value=_DATASET)
    stub.update = AsyncMock(return_value=_DATASET)
    stub.delete = AsyncMock(return_value=None)
    stub.list_versions = AsyncMock(return_value=DatasetVersionList(items=[_VERSION], total=1))
    stub.list_cases = AsyncMock(return_value=DatasetCaseList(items=[_CASE], total=1, version=1))
    stub.add_case = AsyncMock(return_value=_CASE)
    stub.add_from_message = AsyncMock(return_value=_CASE)
    stub.update_case = AsyncMock(return_value=_CASE)
    stub.remove_case = AsyncMock(return_value=None)
    stub.import_cases = AsyncMock(return_value=_VERSION)
    stub.export = AsyncMock(
        return_value=ExportResult(content="input\nq\n", filename="dataset_v1.csv", row_count=1)
    )
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_dataset_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/datasets{suffix}"


async def test_each_route_answers_with_its_status(client: OpenClient) -> None:
    dataset = f"/{_DATASET.id}"
    case = f"{dataset}/cases/{_CASE.case_id}"
    async with client() as http:
        listed = await http.get(_url())
        created = await http.post(_url(), json={"name": "refunds"})
        read = await http.get(_url(dataset))
        renamed = await http.patch(_url(dataset), json={"description": "x"})
        versions = await http.get(_url(f"{dataset}/versions"))
        cases = await http.get(_url(f"{dataset}/cases?version=1"))
        added = await http.post(
            _url(f"{dataset}/cases"), json={"input": "q", "reference_answer": "a"}
        )
        from_message = await http.post(
            _url(f"{dataset}/cases/from-message"), json={"message_id": str(uuid.uuid4())}
        )
        edited = await http.patch(_url(case), json={"note": "n"})
        removed = await http.delete(_url(case))
        deleted = await http.delete(_url(dataset))

    assert listed.json()["total"] == 1
    assert created.status_code == 201
    assert read.json()["can_edit"] is True
    assert renamed.status_code == 200
    assert versions.json()["items"][0]["number"] == 2
    assert cases.json()["version"] == 1
    assert added.status_code == 201
    assert from_message.status_code == 201
    assert edited.status_code == 200
    assert removed.status_code == 204
    assert deleted.status_code == 204


async def test_a_case_that_expects_nothing_is_refused_naming_the_field(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        refused = await http.post(_url(f"/{_DATASET.id}/cases"), json={"input": "q"})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["fields"] == [
        {"field": "reference_answer", "message": NO_EXPECTATION}
    ]
    service.add_case.assert_not_awaited()


async def test_an_upload_reaches_the_service_with_its_name_and_declared_format(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        response = await http.post(
            _url(f"/{_DATASET.id}/import?format=jsonl"),
            files={"file": ("cases.txt", b'{"input": "q"}\n', "text/plain")},
        )
    assert response.status_code == 201
    assert response.json()["change"] == "import"
    kwargs = service.import_cases.await_args.kwargs
    assert kwargs == {"content": b'{"input": "q"}\n', "filename": "cases.txt", "fmt": "jsonl"}


async def test_an_upload_is_read_only_one_byte_past_the_limit(
    client: OpenClient, service: MagicMock
) -> None:
    """Enough for the service to refuse it by size, without holding all of it."""
    async with client() as http:
        await http.post(
            _url(f"/{_DATASET.id}/import"),
            files={"file": ("big.csv", b"x" * (MAX_IMPORT_BYTES + 10), "text/csv")},
        )
    assert len(service.import_cases.await_args.kwargs["content"]) == MAX_IMPORT_BYTES + 1


@pytest.mark.parametrize(("fmt", "media"), [("csv", "text/csv"), ("jsonl", "application/x-ndjson")])
async def test_an_export_downloads_as_a_file(
    client: OpenClient, service: MagicMock, fmt: str, media: str
) -> None:
    async with client() as http:
        response = await http.get(_url(f"/{_DATASET.id}/export?format={fmt}&version=1"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    assert "attachment" in response.headers["content-disposition"]
    assert service.export.await_args.kwargs == {"version": 1, "fmt": fmt}


async def test_a_dataset_the_service_will_not_show_is_a_404(
    client: OpenClient, service: MagicMock
) -> None:
    service.read.side_effect = NotFoundError(message="Dataset not found", details={})
    async with client() as http:
        response = await http.get(_url(f"/{uuid.uuid4()}"))
    assert response.status_code == 404
