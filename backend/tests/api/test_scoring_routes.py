"""The scoring routes, through the app.

`tests/api/test_platform_routes.py` proves which routes delegate to the service
and which carry a gate; `tests/integration/test_scoring.py` proves what scoring
does. What is left is the HTTP layer: each route's status, the arguments a
query string becomes, and that a score's `outcome` reaches the wire.
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
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.dataset import DatasetRead
from app.schemas.scoring import CaseScoreList, CaseScoreRead, ReviewQueue, ScorerResult

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_NOW = datetime(2026, 10, 13, tzinfo=UTC)
_DATASET = DatasetRead(
    id=uuid.uuid4(),
    name="refunds",
    visibility="private",
    latest_version=1,
    case_count=1,
    created_at=_NOW,
)
_SCORE = CaseScoreRead(
    id=uuid.uuid4(),
    dataset_id=_DATASET.id,
    case_id=uuid.uuid4(),
    case_revision_id=uuid.uuid4(),
    results=[
        ScorerResult(scorer="judge", name="tone", required=True, status="fail", reason="2/5: curt")
    ],
    passed=False,
    review_state="done",
    human_passed=True,
    created_at=_NOW,
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.set_scoring = AsyncMock(return_value=_DATASET)
    stub.score_run = AsyncMock(return_value=_SCORE)
    stub.list_scores = AsyncMock(return_value=CaseScoreList(items=[_SCORE], total=1))
    stub.review_queue = AsyncMock(return_value=ReviewQueue(items=[], total=1, datasets=[]))
    stub.set_verdict = AsyncMock(return_value=_SCORE)
    stub.request_review = AsyncMock(return_value=_SCORE)
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_scoring_service] = lambda: service

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
    score = f"{dataset}/scores/{_SCORE.id}"
    async with client() as http:
        assert (await http.put(_url(f"{dataset}/scoring"), json={})).status_code == 200
        scored = await http.post(
            _url(f"{dataset}/cases/{_SCORE.case_id}/scores"), json={"run_id": str(uuid.uuid4())}
        )
        assert scored.status_code == 201
        assert (await http.get(_url(f"{dataset}/scores"))).json()["total"] == 1
        assert (await http.get(_url("/review-queue"))).json()["total"] == 1
        assert (await http.put(_url(f"{score}/verdict"), json={"passed": True})).status_code == 200
        assert (await http.post(_url(f"{score}/review"))).status_code == 200


async def test_a_score_carries_its_outcome_beside_the_judge_s_opinion(client: OpenClient) -> None:
    async with client() as http:
        body = (await http.get(_url(f"/{_DATASET.id}/scores"))).json()["items"][0]

    assert (body["passed"], body["human_passed"], body["outcome"]) == (False, True, True)
    assert body["results"][0]["status"] == "fail"


async def test_the_listing_filters_reach_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    case_id = uuid.uuid4()
    async with client() as http:
        await http.get(
            _url(f"/{_DATASET.id}/scores?case_id={case_id}&pending=true&skip=5&limit=10")
        )

    _, kwargs = service.list_scores.call_args
    assert kwargs == {"case_id": case_id, "pending": True, "skip": 5, "limit": 10}


async def test_a_scoring_configuration_the_schema_refuses_is_a_422(client: OpenClient) -> None:
    async with client() as http:
        response = await http.put(
            _url(f"/{_DATASET.id}/scoring"), json={"judge": {"scale_max": 3, "pass_at": 5}}
        )

    assert response.status_code == 422
