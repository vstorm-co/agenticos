"""Routes for a case's drafted keys: wiring, status codes, and refusals passed through."""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.case_key_draft import CaseKeyDraftRead
from app.schemas.scoring import DocumentKey

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_DATASET = uuid.uuid4()
_CASE = uuid.uuid4()
_DRAFT = CaseKeyDraftRead(
    id=uuid.uuid4(),
    case_id=_CASE,
    status="ready",
    keys=[DocumentKey(key="Invoice", value="INV-7")],
    error=None,
    created_at=datetime(2026, 11, 20, tzinfo=UTC),
    finished_at=datetime(2026, 11, 20, tzinfo=UTC),
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.start = AsyncMock(return_value=_DRAFT.model_copy(update={"status": "running", "keys": []}))
    stub.get = AsyncMock(return_value=_DRAFT)
    stub.dismiss = AsyncMock(return_value=None)
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_case_key_draft_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


_URL = f"{settings.API_V1_STR}/datasets/{_DATASET}/cases/{_CASE}/key-draft"


async def test_each_route_answers_with_its_status(client: OpenClient, service: MagicMock) -> None:
    async with client() as http:
        started = await http.post(_URL)
        read = await http.get(_URL)
        dismissed = await http.delete(_URL)

    assert (started.status_code, started.json()["status"]) == (202, "running")
    assert (read.status_code, read.json()["keys"]) == (200, [{"key": "Invoice", "value": "INV-7"}])
    assert dismissed.status_code == 204
    for method in (service.start, service.get, service.dismiss):
        assert method.await_args.args[1:] == (_DATASET, _CASE)


@pytest.mark.parametrize(
    ("refusal", "status"),
    [
        (BadRequestError(message="This case has no reference answer to list keys from"), 400),
        (AuthorizationError(message="Editing this dataset needs datasets:edit"), 403),
        (NotFoundError(message="Dataset not found"), 404),
    ],
)
async def test_a_refusal_reaches_the_caller(
    client: OpenClient, service: MagicMock, refusal: Exception, status: int
) -> None:
    service.start = AsyncMock(side_effect=refusal)

    async with client() as http:
        answer = await http.post(_URL)

    assert answer.status_code == status
