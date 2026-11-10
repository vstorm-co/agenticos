"""The promotion gate through the app: its two routes, and the refusal a console reads.

`tests/integration/test_promotion_gate.py` proves what the gate decides. Left
here is the HTTP layer - each route's status, and the 409 a blocked promotion
answers with, whose `details.gate` is the contract the promotion dialog renders.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import PromotionBlockedError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.eval_suite import EvalSuiteResultRead, EvalSuiteThreshold
from app.schemas.promotion_gate import (
    PromotionGateRead,
    PromotionGateRunRead,
    PromotionGuardRead,
)

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 10, 21, tzinfo=UTC)
_AGENT = uuid.uuid4()
_ENV = uuid.uuid4()
_VERSION = uuid.uuid4()
_SUITE = uuid.uuid4()
_RESULT = EvalSuiteResultRead(
    id=uuid.uuid4(),
    suite_id=_SUITE,
    trigger="gate",
    trigger_detail=None,
    version_number=2,
    baseline_version_number=1,
    environment_id=None,
    status="failed",
    reason=None,
    due_at=_NOW,
    eval_run_id=uuid.uuid4(),
    baseline_eval_run_id=None,
    run_as_user_id=None,
    threshold=EvalSuiteThreshold(min_pass_rate=0.9),
    summary=None,
    notified_at=_NOW,
    created_at=_NOW,
    started_at=_NOW,
    settled_at=_NOW,
)
_GATE = PromotionGateRead(
    environment_id=_ENV,
    environment_name="production",
    version_id=_VERSION,
    version=2,
    guarded=True,
    passing=False,
    can_override=False,
    guards=[
        PromotionGuardRead(suite_id=_SUITE, suite_name="Refunds", state="failed", result=_RESULT)
    ],
)


@pytest.fixture
def gate() -> MagicMock:
    stub = MagicMock()
    stub.read = AsyncMock(return_value=_GATE)
    stub.run = AsyncMock(return_value=PromotionGateRunRead(started=[_SUITE], gate=_GATE))
    return stub


@pytest.fixture
def environments() -> MagicMock:
    stub = MagicMock()
    stub.update = AsyncMock(
        side_effect=PromotionBlockedError(
            message="v2 has not passed 'Refunds', which guards production.",
            details={"gate": _GATE.model_dump(mode="json")},
        )
    )
    return stub


@pytest.fixture
def client(
    mock_redis: MagicMock, gate: MagicMock, environments: MagicMock
) -> Iterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_promotion_gate_service] = lambda: gate
    app.dependency_overrides[deps.get_agent_environment_service] = lambda: environments
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def _url(suffix: str) -> str:
    return f"{settings.API_V1_STR}/agents/{_AGENT}/environments/{_ENV}{suffix}"


async def test_the_gate_is_read_for_a_version_and_its_guards_run(
    client: AsyncClient, gate: MagicMock
) -> None:
    async with client as http:
        read = await http.get(_url("/gate"), params={"version_id": str(_VERSION)})
        ran = await http.post(_url("/gate/run"), json={"version_id": str(_VERSION)})
        missing = await http.get(_url("/gate"))

    assert read.status_code == 200
    assert read.json()["guards"][0]["state"] == "failed"
    assert gate.read.await_args.args[1:] == (_AGENT, _ENV, _VERSION)
    assert (ran.status_code, ran.json()["started"]) == (200, [str(_SUITE)])
    assert missing.status_code == 422


async def test_a_blocked_promotion_is_a_conflict_carrying_the_whole_gate(
    client: AsyncClient,
) -> None:
    async with client as http:
        response = await http.patch(_url(""), json={"version_id": str(_VERSION)})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "PROMOTION_BLOCKED"
    gate = error["details"]["gate"]
    assert set(gate) == {
        "environment_id",
        "environment_name",
        "version_id",
        "version",
        "guarded",
        "passing",
        "can_override",
        "guards",
    }
    assert (gate["environment_id"], gate["version"], gate["can_override"]) == (
        str(_ENV),
        2,
        False,
    )
    [guard] = gate["guards"]
    assert set(guard) == {"suite_id", "suite_name", "state", "paused_reason", "result"}
    assert (guard["suite_id"], guard["state"], guard["result"]["id"]) == (
        str(_SUITE),
        "failed",
        str(_RESULT.id),
    )
    assert guard["result"]["trigger"] == "gate"


async def test_a_reason_too_short_to_say_anything_is_refused_before_the_service(
    client: AsyncClient, environments: MagicMock
) -> None:
    async with client as http:
        response = await http.patch(
            _url(""), json={"version_id": str(_VERSION), "override_reason": "because"}
        )

    assert response.status_code == 422
    environments.update.assert_not_awaited()
