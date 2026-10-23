"""The eval run routes, through the app.

`tests/api/test_platform_routes.py` proves the routes are gated or delegate to
the service; `tests/integration/test_eval_runs.py` proves what the service does.
Left here is the HTTP layer: each route's status, that the query parameters
reach the service as the service names them, and that a budget refusal is a 402.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.spec import AgentSpec
from app.api import deps
from app.core.config import settings
from app.core.exceptions import PaymentRequiredError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.eval_run import (
    ArmSummaryRead,
    ComparisonSide,
    EvalCaseList,
    EvalComparisonRead,
    EvalRunEstimate,
    EvalRunList,
    EvalRunRead,
)

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_NOW = datetime(2026, 10, 14, tzinfo=UTC)
_SUMMARY = ArmSummaryRead(
    cases=1,
    passed=1,
    failed=0,
    incomplete=0,
    pass_rate=1.0,
    first_pass_rate=1.0,
    cost_usd=Decimal("0.01"),
    cost_per_pass_usd=Decimal("0.01"),
    avg_tokens=120,
    p50_ms=500,
    p95_ms=500,
)
_RUN = EvalRunRead(
    id=uuid.uuid4(),
    agent_id=uuid.uuid4(),
    dataset_id=uuid.uuid4(),
    dataset_name="refunds",
    dataset_version=1,
    environment_id=None,
    status="queued",
    purpose="manual",
    paired=False,
    from_recordings=False,
    live_reads=False,
    reruns=2,
    estimate_usd=Decimal("0.05"),
    rerun_ceiling_usd=Decimal("0.10"),
    cost_usd=Decimal(0),
    cost_is_partial=False,
    attempts_done=0,
    attempts_total=1,
    cases=1,
    first_done=0,
    first_total=1,
    outcome=None,
    routed_to_review=0,
    routed_replacing=0,
    error=None,
    created_by_user_id=None,
    created_at=_NOW,
    started_at=None,
    ended_at=None,
    arms=[],
)
_ESTIMATE = EvalRunEstimate(
    cases=1,
    arms=[],
    judge_usd=Decimal(0),
    total_usd=Decimal("0.05"),
    rerun_ceiling_usd=Decimal("0.10"),
    agent_remaining_usd=None,
    org_remaining_usd=Decimal("10"),
    agent_after_usd=None,
    org_after_usd=Decimal("9.95"),
    affordable=True,
)
_SIDE = ComparisonSide(
    run_id=_RUN.id,
    arm_id=uuid.uuid4(),
    role="candidate",
    source="version",
    version_number=7,
    model_label="gpt-test",
    dataset_version=1,
    finished_at=_NOW,
)
_COMPARISON = EvalComparisonRead(
    candidate=_SIDE,
    baseline=None,
    paired=False,
    verdict=None,
    overall=None,
    p_value=None,
    invalid_reason=None,
    regressions_confirmed=0,
    regressions_unconfirmed=0,
    fixed_confirmed=0,
    fixed_unconfirmed=0,
    compared=0,
    not_compared=1,
    candidate_summary=_SUMMARY,
    baseline_summary=None,
    efficiency=None,
    cases=[],
    flips_by_tag={},
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.estimate = AsyncMock(return_value=_ESTIMATE)
    stub.start = AsyncMock(return_value=_RUN)
    stub.list_for_agent = AsyncMock(return_value=EvalRunList(items=[_RUN], total=1))
    stub.list_for_dataset = AsyncMock(return_value=EvalRunList(items=[_RUN], total=1))
    stub.recent = AsyncMock(return_value=EvalRunList(items=[_RUN], total=1))
    stub.get = AsyncMock(return_value=_RUN)
    stub.cases = AsyncMock(return_value=EvalCaseList(items=[], total=0))
    stub.compare = AsyncMock(return_value=_COMPARISON)
    stub.arm_spec = AsyncMock(return_value=AgentSpec(name="Support", instructions="Draft"))
    stub.cancel = AsyncMock(return_value=_RUN)
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_eval_run_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str) -> str:
    return f"{settings.API_V1_STR}{suffix}"


async def test_each_route_answers_with_its_status(client: OpenClient, service: MagicMock) -> None:
    agent = f"/agents/{_RUN.agent_id}/eval-runs"
    run = f"/eval-runs/{_RUN.id}"
    body = {"dataset_id": str(_RUN.dataset_id), "candidate": "draft"}
    async with client() as http:
        estimated = await http.post(_url(f"{agent}/estimate"), json=body)
        started = await http.post(_url(agent), json=body)
        listed = await http.get(_url(f"{agent}?skip=20&limit=10"))
        drafts = await http.get(_url(f"{agent}?draft=current"))
        by_dataset = await http.get(_url(f"/datasets/{_RUN.dataset_id}/eval-runs?limit=5"))
        recent = await http.get(_url("/eval-runs/recent?skip=20&limit=5"))
        read = await http.get(_url(run))
        cases = await http.get(_url(f"{run}/cases?outcome=failed&tag=refunds"))
        named = await http.get(_url(f"{run}/cases?case_id={_RUN.id}&case_id={_RUN.agent_id}"))
        compared = await http.get(_url(f"{run}/comparison"))
        spec = await http.get(_url(f"{run}/arms/{_RUN.agent_id}/spec"))
        cancelled = await http.post(_url(f"{run}/cancel"))

    assert estimated.json()["org_after_usd"] == "9.95"
    assert started.status_code == 201
    assert service.start.await_args.args[2].candidate == "draft"
    assert listed.json()["total"] == 1
    assert drafts.status_code == by_dataset.status_code == named.status_code == 200
    assert service.list_for_agent.await_args_list[0].kwargs == {
        "draft": False,
        "skip": 20,
        "limit": 10,
    }
    assert service.list_for_agent.await_args.kwargs["draft"] is True
    assert service.list_for_dataset.await_args.kwargs == {"skip": 0, "limit": 5}
    assert service.cases.await_args.kwargs["case_ids"] == [_RUN.id, _RUN.agent_id]
    assert service.recent.await_args.kwargs == {"skip": 20, "limit": 5}
    assert recent.status_code == read.status_code == compared.status_code == 200
    assert cases.status_code == 200
    assert service.cases.await_args_list[0].kwargs["outcome"] == "failed"
    assert service.cases.await_args_list[0].kwargs["tag"] == "refunds"
    assert service.cases.await_args_list[0].kwargs["case_ids"] is None
    assert cancelled.json()["status"] == "queued"
    assert spec.json()["instructions"] == "Draft"
    assert service.arm_spec.await_args.args[1:] == (_RUN.id, _RUN.agent_id)


async def test_the_same_model_twice_is_refused_before_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    model = str(uuid.uuid4())
    async with client() as http:
        refused = await http.post(
            _url(f"/agents/{_RUN.agent_id}/eval-runs/estimate"),
            json={"dataset_id": str(_RUN.dataset_id), "model_profile_ids": [model, model]},
        )

    assert refused.status_code == 422
    service.estimate.assert_not_awaited()


@pytest.mark.security
async def test_a_run_past_the_budget_answers_402(client: OpenClient, service: MagicMock) -> None:
    service.start.side_effect = PaymentRequiredError(
        message="This eval would cost more than is left", details={"estimate_usd": "1.00"}
    )
    async with client() as http:
        refused = await http.post(
            _url(f"/agents/{_RUN.agent_id}/eval-runs"),
            json={"dataset_id": str(_RUN.dataset_id)},
        )

    assert refused.status_code == 402
    assert refused.json()["error"]["details"] == {"estimate_usd": "1.00"}


async def test_a_comparison_can_name_its_arm_and_baseline(
    client: OpenClient, service: MagicMock
) -> None:
    arm, baseline = uuid.uuid4(), uuid.uuid4()
    async with client() as http:
        await http.get(
            _url(f"/eval-runs/{_RUN.id}/comparison?arm_id={arm}&baseline_run_id={baseline}")
        )

    assert service.compare.await_args.kwargs == {"arm_id": arm, "baseline_run_id": baseline}
