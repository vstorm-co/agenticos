"""The authoring assistant's routes, through the app.

`tests/api/test_platform_routes.py` proves the routes delegate rather than carry a
role gate; `tests/integration/test_authoring.py` proves what the service does.
Left here is the HTTP layer: each route's status, and that its body and path
reach the service.
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
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.authoring import (
    AgentAuthoringRead,
    AuthoringEstimate,
    AuthoringRequestRead,
    AuthoringWaiting,
    DecisionRead,
)
from app.schemas.context_proposal import ContextProposalList, ContextProposalRead
from tests.api.test_eval_run_routes import _ESTIMATE, _RUN

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_REQUEST = AuthoringRequestRead(
    id=uuid.uuid4(),
    kind="improve",
    target="agent",
    agent_id=uuid.uuid4(),
    skill_id=None,
    status="queued",
    error=None,
    estimate_usd=Decimal("0.04"),
    cost_usd=Decimal(0),
    run_ids=[],
    window_days=30,
    evidence={},
    report=None,
    created_at=datetime(2026, 10, 21, tzinfo=UTC),
    started_at=None,
    finished_at=None,
)
_EMPTY = AgentAuthoringRead(batch=None, latest=_REQUEST, verify=None)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.for_agent = AsyncMock(return_value=_EMPTY)
    stub.estimate_agent = AsyncMock(
        return_value=AuthoringEstimate(
            runs=3, rated_down=2, calls=1, estimate_usd=Decimal("0.04"), affordable=True
        )
    )
    stub.start_agent = AsyncMock(return_value=_REQUEST)
    stub.decide = AsyncMock(return_value=DecisionRead(authoring=_EMPTY, draft_spec={}))
    stub.dismiss_all = AsyncMock(return_value=_EMPTY)
    stub.estimate_check = AsyncMock(return_value=_ESTIMATE)
    stub.check = AsyncMock(return_value=_RUN)
    stub.estimate_skill = stub.estimate_agent
    stub.start_skill = AsyncMock(return_value=_REQUEST)
    stub.for_skill = AsyncMock(return_value=[_REQUEST])
    stub.waiting = AsyncMock(return_value=AuthoringWaiting(agents=[], skills=0))
    stub.estimate_skill_check = AsyncMock(return_value=_ESTIMATE)
    stub.check_skill = AsyncMock(return_value=_RUN)
    stub.estimate_context = stub.estimate_agent
    stub.start_context = AsyncMock(return_value=_REQUEST)
    stub.for_context = AsyncMock(return_value=[_REQUEST])
    stub.estimate_context_check = AsyncMock(return_value=_ESTIMATE)
    stub.check_context = AsyncMock(return_value=_RUN)
    return stub


_CHANGE = ContextProposalRead(
    id=uuid.uuid4(),
    context_id=uuid.uuid4(),
    context_name="returns",
    description="Returns",
    content="Returns take 30 days.",
    current_description="Returns",
    current_content="Returns take 90 days.",
    status="pending",
    stale=False,
    created_at=datetime(2026, 10, 21, tzinfo=UTC),
)


@pytest.fixture
def changes() -> MagicMock:
    stub = MagicMock()
    stub.list_read = AsyncMock(return_value=ContextProposalList(items=[_CHANGE], total=1))
    stub.read = AsyncMock(return_value=_CHANGE)
    stub.apply = AsyncMock(return_value=_CHANGE)
    stub.discard = AsyncMock(return_value=_CHANGE)
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock, changes: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_authoring_service] = lambda: service
    app.dependency_overrides[deps.get_context_proposal_service] = lambda: changes

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str) -> str:
    return f"{settings.API_V1_STR}{suffix}"


async def test_each_agent_route_answers_with_its_status(
    client: OpenClient, service: MagicMock
) -> None:
    agent = f"/agents/{uuid.uuid4()}/authoring"
    hunk = uuid.uuid4()
    dataset = {"dataset_id": str(uuid.uuid4())}
    async with client() as http:
        assert (await http.get(_url(agent))).status_code == 200
        assert (await http.post(_url(f"{agent}/estimate"), json={})).status_code == 200
        started = await http.post(_url(agent), json={"kind": "verify", "window_days": 7})
        decided = await http.post(
            _url(f"{agent}/hunks/{hunk}"), json={"action": "accept", "text": "Edited"}
        )
        assert (await http.post(_url(f"{agent}/dismiss"))).status_code == 200
        assert (await http.post(_url(f"{agent}/check/estimate"), json=dataset)).status_code == 200
        checked = await http.post(_url(f"{agent}/check"), json=dataset)

    assert started.status_code == 201
    assert service.start_agent.await_args.args[2].kind == "verify"
    assert decided.status_code == 200
    assert service.decide.await_args.args[2] == hunk
    assert service.decide.await_args.args[3].text == "Edited"
    assert checked.status_code == 201


async def test_each_skill_route_answers_with_its_status(client: OpenClient) -> None:
    skill = f"/skills/{uuid.uuid4()}/authoring"
    async with client() as http:
        assert (await http.post(_url(f"{skill}/estimate"), json={})).status_code == 200
        assert (await http.post(_url(skill), json={})).status_code == 201
        listed = await http.get(_url(skill))
        check = {"dataset_id": str(uuid.uuid4()), "proposal_id": str(uuid.uuid4())}
        assert (await http.post(_url(f"{skill}/check/estimate"), json=check)).status_code == 200
        assert (await http.post(_url(f"{skill}/check"), json=check)).status_code == 201

    assert listed.status_code == 200 and len(listed.json()) == 1


async def test_each_context_route_answers_with_its_status(
    client: OpenClient, changes: MagicMock
) -> None:
    context = f"/context/{uuid.uuid4()}/authoring"
    proposal = uuid.uuid4()
    async with client() as http:
        assert (await http.post(_url(f"{context}/estimate"), json={})).status_code == 200
        assert (await http.post(_url(context), json={})).status_code == 201
        listed = await http.get(_url(context))
        check = {"suite_id": str(uuid.uuid4()), "proposal_id": str(uuid.uuid4())}
        assert (await http.post(_url(f"{context}/check/estimate"), json=check)).status_code == 200
        assert (await http.post(_url(f"{context}/check"), json=check)).status_code == 201
        waiting = await http.get(_url("/context-changes?status=pending"))
        assert (await http.get(_url(f"/context-changes/{proposal}"))).status_code == 200
        assert (await http.post(_url(f"/context-changes/{proposal}/apply"))).status_code == 200
        assert (await http.post(_url(f"/context-changes/{proposal}/discard"))).status_code == 200

    assert listed.status_code == 200 and len(listed.json()) == 1
    assert waiting.json()["total"] == 1
    assert changes.list_read.await_args.kwargs == {"status": "pending"}
    assert changes.apply.await_args.args[1] == proposal


async def test_what_waits_is_answered(client: OpenClient) -> None:
    async with client() as http:
        response = await http.get(_url("/authoring/waiting"))

    assert response.status_code == 200 and response.json() == {
        "agents": [],
        "skills": 0,
        "contexts": 0,
        "skill_files": [],
        "context_files": [],
    }


async def test_a_decision_must_name_an_action(client: OpenClient) -> None:
    async with client() as http:
        response = await http.post(
            _url(f"/agents/{uuid.uuid4()}/authoring/hunks/{uuid.uuid4()}"),
            json={"action": "publish"},
        )

    assert response.status_code == 422
