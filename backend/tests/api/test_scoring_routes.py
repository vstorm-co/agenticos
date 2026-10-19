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
from app.schemas.scoring import (
    CaseScoreList,
    CaseScoreRead,
    JudgeAgreement,
    JudgeTemplate,
    Rescored,
    ReviewQueue,
    ReviewRequested,
    ReviewWithdrawn,
    ScorerResult,
)

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
    question="Refund window?",
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
    stub.create_judge = AsyncMock(return_value=_DATASET)
    stub.request_reviews = AsyncMock(return_value=ReviewRequested(queued=2, replaced=0, already=1))
    stub.withdraw_reviews = AsyncMock(return_value=ReviewWithdrawn(removed=1, kept=0))
    stub.rescore = AsyncMock(return_value=Rescored(rescored=[_SCORE], kept=[]))
    stub.judge_agreement = AsyncMock(return_value=JudgeAgreement(agreed=7, decided=10))
    stub.judge_template = AsyncMock(return_value=JudgeTemplate(instructions="Grade strictly."))
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
        judged = await http.post(
            _url(f"{dataset}/judge"), json={"name": "Refunds judge", "instructions": "Be strict."}
        )
        assert judged.status_code == 201
        template = await http.get(_url(f"{dataset}/judge-template"))
        assert template.json() == {"instructions": "Grade strictly."}
        scored = await http.post(
            _url(f"{dataset}/cases/{_SCORE.case_id}/scores"), json={"run_id": str(uuid.uuid4())}
        )
        assert scored.status_code == 201
        assert (await http.get(_url(f"{dataset}/scores"))).json()["total"] == 1
        assert (await http.get(_url("/review-queue"))).json()["total"] == 1
        agreement = await http.get(_url(f"/judge-agreement?judge={uuid.uuid4()}"))
        assert agreement.json() == {"agreed": 7, "decided": 10}
        assert (await http.put(_url(f"{score}/verdict"), json={"passed": True})).status_code == 200
        assert (await http.post(_url(f"{score}/review"))).status_code == 200
        sent = await http.post(
            _url(f"{dataset}/scores/review"), json={"score_ids": [str(uuid.uuid4())]}
        )
        assert sent.json() == {"queued": 2, "replaced": 0, "already": 1}
        taken = await http.post(
            _url(f"{dataset}/scores/review/withdraw"), json={"score_ids": [str(uuid.uuid4())]}
        )
        assert taken.json() == {"removed": 1, "kept": 0}
        again = await http.post(
            _url(f"{dataset}/scores/rescore"), json={"score_ids": [str(uuid.uuid4())]}
        )
        assert again.status_code == 200
        assert again.json()["rescored"][0]["id"] == str(_SCORE.id)


async def test_more_scores_than_one_request_grades_again_are_refused(client: OpenClient) -> None:
    async with client() as http:
        refused = await http.post(
            _url(f"/{_DATASET.id}/scores/rescore"),
            json={"score_ids": [str(uuid.uuid4()) for _ in range(11)]},
        )

    assert refused.status_code == 422


async def test_a_score_carries_its_outcome_beside_the_judge_s_opinion(client: OpenClient) -> None:
    async with client() as http:
        body = (await http.get(_url(f"/{_DATASET.id}/scores"))).json()["items"][0]

    assert (body["passed"], body["human_passed"], body["outcome"]) == (False, True, True)
    assert body["unscored_reason"] is None
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
    assert kwargs == {
        "case_id": case_id,
        "pending": True,
        "outcome": None,
        "agent_id": None,
        "eval_run_id": None,
        "judge_id": None,
        "tag": None,
        "skip": 5,
        "limit": 10,
    }


async def test_the_outcome_agent_eval_run_judge_and_tag_filters_reach_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    agent_id, eval_run_id, judge_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with client() as http:
        await http.get(
            _url(
                f"/{_DATASET.id}/scores?outcome=failed&agent_id={agent_id}"
                f"&eval_run_id={eval_run_id}&judge={judge_id}&tag=billing"
            )
        )
        refused = await http.get(_url(f"/{_DATASET.id}/scores?outcome=maybe"))

    _, kwargs = service.list_scores.call_args
    assert (
        kwargs["outcome"],
        kwargs["agent_id"],
        kwargs["eval_run_id"],
        kwargs["judge_id"],
        kwargs["tag"],
    ) == ("failed", agent_id, eval_run_id, judge_id, "billing")
    assert refused.status_code == 422


async def test_a_scoring_configuration_the_schema_refuses_is_a_422(client: OpenClient) -> None:
    async with client() as http:
        response = await http.put(
            _url(f"/{_DATASET.id}/scoring"), json={"judge": {"scale_max": 3, "pass_at": 5}}
        )

    assert response.status_code == 422


async def test_a_review_request_with_no_score_or_too_many_is_a_422(client: OpenClient) -> None:
    url = _url(f"/{_DATASET.id}/scores/review")
    async with client() as http:
        empty = await http.post(url, json={"score_ids": []})
        too_many = await http.post(url, json={"score_ids": [str(uuid.uuid4()) for _ in range(501)]})

    assert (empty.status_code, too_many.status_code) == (422, 422)
