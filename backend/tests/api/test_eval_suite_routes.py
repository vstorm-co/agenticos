"""The eval suite routes, through the app.

`tests/api/test_platform_routes.py` proves the routes are gated or delegate to
the service; `tests/integration/test_eval_suites.py` proves what the service
does. Left here is the HTTP layer: each route's status, that the paging reaches
the service, and that a suite that cannot run now is a 409.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import EvalSuiteNotRunnableError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.eval_run import EvalRunEstimate
from app.schemas.eval_suite import (
    EvalSuiteEstimate,
    EvalSuiteList,
    EvalSuiteRead,
    EvalSuiteResultList,
    EvalSuiteResultRead,
    EvalSuiteThreshold,
)

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_NOW = datetime(2026, 10, 19, tzinfo=UTC)
_SUITE = EvalSuiteRead(
    id=uuid.uuid4(),
    agent_id=uuid.uuid4(),
    agent_name="Clerk",
    dataset_id=uuid.uuid4(),
    dataset_name="refunds",
    environment_id=None,
    environment_name=None,
    owner_user_id=None,
    owner_email=None,
    name="Nightly",
    description=None,
    is_active=True,
    paused_reason=None,
    threshold=EvalSuiteThreshold(),
    on_publish=True,
    on_promotion=False,
    on_dependency_change=False,
    schedule=None,
    next_fire_at=None,
    max_run_usd=None,
    last_result=None,
    open_result=None,
    created_at=_NOW,
    updated_at=None,
)
_RESULT = EvalSuiteResultRead(
    id=uuid.uuid4(),
    suite_id=_SUITE.id,
    trigger="manual",
    trigger_detail=None,
    version_number=1,
    baseline_version_number=None,
    environment_id=None,
    status="running",
    reason=None,
    due_at=_NOW,
    eval_run_id=uuid.uuid4(),
    baseline_eval_run_id=None,
    run_as_user_id=None,
    threshold=EvalSuiteThreshold(),
    summary=None,
    notified_at=None,
    created_at=_NOW,
    started_at=_NOW,
    settled_at=None,
)
_RUN_ESTIMATE = EvalRunEstimate(
    cases=1,
    arms=[],
    judge_usd=Decimal(0),
    total_usd=Decimal("0.05"),
    rerun_ceiling_usd=Decimal("0.10"),
    agent_remaining_usd=None,
    org_remaining_usd=None,
    agent_after_usd=None,
    org_after_usd=None,
    affordable=True,
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_visible = AsyncMock(return_value=EvalSuiteList(items=[_SUITE], total=1))
    stub.list_for_agent = AsyncMock(return_value=EvalSuiteList(items=[_SUITE], total=1))
    stub.estimate = AsyncMock(
        return_value=EvalSuiteEstimate(
            run=_RUN_ESTIMATE, paired_run=None, fires_per_month=30, monthly_usd=Decimal("1.50")
        )
    )
    stub.create = AsyncMock(return_value=_SUITE)
    stub.get = AsyncMock(return_value=_SUITE)
    stub.update = AsyncMock(return_value=_SUITE)
    stub.delete = AsyncMock(return_value=None)
    stub.results = AsyncMock(return_value=EvalSuiteResultList(items=[_RESULT], total=1))
    stub.run_now = AsyncMock(return_value=_RESULT)
    return stub


def _client(mock_redis: MagicMock, service: MagicMock, role: OrgRoleName) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_eval_suite_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    yield from _client(mock_redis, service, OrgRoleName.OWNER)


@pytest.fixture
def viewer(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    yield from _client(mock_redis, service, OrgRoleName.VIEWER)


def _url(suffix: str) -> str:
    return f"{settings.API_V1_STR}{suffix}"


async def test_each_route_answers_with_its_status(client: OpenClient, service: MagicMock) -> None:
    suites = f"/agents/{_SUITE.agent_id}/eval-suites"
    one = f"{suites}/{_SUITE.id}"
    body = {"name": "Nightly", "dataset_id": str(_SUITE.dataset_id), "on_publish": True}
    async with client() as http:
        assert (await http.get(_url("/eval-suites"))).status_code == 200
        assert (await http.get(_url(suites))).status_code == 200
        assert (
            await http.post(_url(f"{suites}/estimate"), json={"dataset_id": str(_SUITE.dataset_id)})
        ).status_code == 200
        assert (await http.post(_url(suites), json=body)).status_code == 201
        assert (await http.get(_url(one))).status_code == 200
        assert (await http.patch(_url(one), json={"is_active": False})).status_code == 200
        assert (await http.post(_url(f"{one}/run"))).status_code == 201
        listed = await http.get(_url(f"{one}/results"), params={"skip": 20, "limit": 10})
        assert listed.status_code == 200
        assert (await http.delete(_url(one))).status_code == 204

    assert service.results.await_args.kwargs == {"skip": 20, "limit": 10}
    assert listed.json()["items"][0]["status"] == "running"


async def test_a_suite_that_cannot_run_now_is_a_conflict(
    client: OpenClient, service: MagicMock
) -> None:
    service.run_now.side_effect = EvalSuiteNotRunnableError(
        message="'Nightly' is paused.", details={"suite_id": str(_SUITE.id), "reason": "paused"}
    )
    async with client() as http:
        response = await http.post(_url(f"/agents/{_SUITE.agent_id}/eval-suites/{_SUITE.id}/run"))

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "paused"


async def test_a_schedule_that_never_fires_is_refused_before_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    body = {
        "name": "Nightly",
        "dataset_id": str(_SUITE.dataset_id),
        "schedule": {"cron": "0 0 31 2 *", "timezone": "UTC"},
    }
    async with client() as http:
        response = await http.post(_url(f"/agents/{_SUITE.agent_id}/eval-suites"), json=body)

    assert response.status_code == 422
    service.create.assert_not_awaited()


@pytest.mark.security
async def test_the_organizations_suites_need_permission_to_view_runs(
    viewer: OpenClient, service: MagicMock
) -> None:
    async with viewer() as http:
        response = await http.get(_url("/eval-suites"))

    assert response.status_code == 403
    service.list_visible.assert_not_awaited()
