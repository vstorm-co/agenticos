"""The skill check routes: each delegates to the service and answers in its shape.

What a check decides is tested against a database in
`tests/integration/test_skill_checks.py`; these pin the HTTP layer - the path,
the status code, the body handed on, and that a refusal keeps its status.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.skill_check import (
    LineRef,
    SkillCheckApplied,
    SkillCheckAwaiting,
    SkillCheckEstimate,
    SkillCheckForked,
    SkillCheckList,
    SkillCheckRead,
)
from app.schemas.skill_version import (
    SkillForkRead,
    SkillVersionRead,
    VersionNumberRef,
    VersionRef,
)

pytestmark = pytest.mark.anyio

SKILL = uuid.uuid4()
CHECK = uuid.uuid4()
NOW = datetime(2026, 11, 3, tzinfo=UTC)
BASE = VersionRef(id=uuid.uuid4(), number=3, fork_id=None)


def _estimate() -> SkillCheckEstimate:
    return SkillCheckEstimate(
        line=LineRef(fork_id=None, name="main"),
        base_version=BASE,
        mode="quick",
        description_changed=False,
        agents=[],
        hidden=1,
        expected_usd=Decimal("0.24"),
        at_most_usd=Decimal("0.72"),
        org_remaining_usd=None,
        affordable=True,
    )


def _check(**overrides: Any) -> SkillCheckRead:
    values: dict[str, Any] = {
        **_estimate().model_dump(),
        "id": CHECK,
        "skill_id": SKILL,
        "source": "proposal",
        "status": "done",
        "verdict": "passed",
        "outcomes": ["apply", "improve_further", "discard"],
        "candidate": {"description": "Refunds", "content": "Refund within 30 days."},
        "created_at": NOW,
    }
    return SkillCheckRead(**{**values, **overrides})


def _version() -> SkillVersionRead:
    return SkillVersionRead(
        id=uuid.uuid4(),
        skill_id=SKILL,
        fork_id=None,
        number=4,
        source="edit",
        previous=BASE,
        created_at=NOW,
        agents=0,
        description="How refunds work.",
        content="An order number counts as a receipt.",
        resources=[],
    )


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.estimate = AsyncMock(return_value=_estimate())
    stub.start = AsyncMock(return_value=_check(status="running", verdict=None, outcomes=[]))
    stub.estimate_update = AsyncMock(return_value=_estimate())
    stub.start_update = AsyncMock(
        side_effect=BadRequestError(message="Not pinned", details={"agent_id": "a"})
    )
    stub.list_checks = AsyncMock(return_value=SkillCheckList(items=[_check()], total=1))
    stub.awaiting = AsyncMock(
        return_value=[
            SkillCheckAwaiting(
                id=CHECK,
                skill_id=SKILL,
                skill_name="returns",
                line=LineRef(fork_id=None, name="main"),
                status="done",
                verdict="no_better",
                agents=2,
                created_at=NOW,
            )
        ]
    )
    stub.read = AsyncMock(return_value=_check())
    stub.cancel = AsyncMock(return_value=_check(status="cancelled"))
    stub.apply = AsyncMock(return_value=SkillCheckApplied(version=_version(), pinned=[]))
    stub.fork = AsyncMock(
        return_value=SkillCheckForked(
            fork=SkillForkRead(
                id=uuid.uuid4(),
                skill_id=SKILL,
                name="online",
                base=VersionNumberRef(id=BASE.id, number=3),
                started_from=VersionNumberRef(id=BASE.id, number=3),
                latest=None,
                changes=1,
                behind_main=0,
                agents=1,
                archive_candidate=False,
                created_at=NOW,
            ),
            moved=[],
            draft_only=[],
        )
    )
    stub.discard = AsyncMock(return_value=_check(status="discarded"))
    stub.test_set = AsyncMock(side_effect=NotFoundError(message="No test questions"))
    stub.create_test_set = AsyncMock(side_effect=AlreadyExistsError(message="Has them"))
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_check_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str = "") -> str:
    return f"{settings.API_V1_STR}/skills/{SKILL}{tail}"


START = {"proposal_id": str(uuid.uuid4())}


class TestStarting:
    async def test_the_estimate_counts_hidden_agents_and_both_prices(self, client, service):
        async with client() as opened:
            response = await opened.post(_url("/checks/estimate"), json=START)

        assert response.status_code == 200
        assert (response.json()["hidden"], response.json()["at_most_usd"]) == (1, "0.72")
        assert service.estimate.await_args.args[1] == SKILL

    async def test_a_start_is_created(self, client):
        async with client() as opened:
            response = await opened.post(_url("/checks"), json=START)

        assert response.status_code == 201
        assert response.json()["status"] == "running"

    async def test_a_start_names_one_candidate(self, client):
        async with client() as opened:
            response = await opened.post(
                _url("/checks"),
                json={**START, "candidate": {"description": "d", "content": "c"}},
            )

        assert response.status_code == 422

    @pytest.mark.parametrize("tail", ["/checks", "/checks/estimate"])
    async def test_a_text_without_its_base_version_is_refused(self, client, service, tail):
        """Without it a text read on v3 would be checked, and applied, over v4."""
        text = {"candidate": {"description": "d", "content": "c"}}
        async with client() as opened:
            bare = await opened.post(_url(tail), json=text)
            based = await opened.post(_url(tail), json={**text, "base_version_id": str(BASE.id)})

        assert bare.status_code == 422
        assert based.status_code in (200, 201)


class TestAPinnedAgentsUpdate:
    async def test_its_estimate_names_the_skill_and_the_agent(self, client, service):
        agent = uuid.uuid4()
        async with client() as opened:
            response = await opened.post(
                _url(f"/agents/{agent}/update-check/estimate"), json={"mode": "thorough"}
            )
        assert response.status_code == 200
        assert service.estimate_update.await_args.args[1:3] == (SKILL, agent)
        assert service.estimate_update.await_args.args[3].mode == "thorough"

    async def test_a_refused_start_keeps_its_400_and_a_bare_body_is_quick(self, client, service):
        async with client() as opened:
            response = await opened.post(_url(f"/agents/{uuid.uuid4()}/update-check"), json={})
        assert response.status_code == 400
        assert service.start_update.await_args.args[3].mode == "quick"


class TestReading:
    async def test_a_lines_checks_are_listed(self, client, service):
        fork = uuid.uuid4()
        async with client() as opened:
            response = await opened.get(_url("/checks"), params={"fork_id": str(fork)})

        assert response.json()["total"] == 1
        assert service.list_checks.await_args.kwargs == {"fork_id": fork, "skip": 0, "limit": 20}

    async def test_one_check_is_read(self, client):
        async with client() as opened:
            response = await opened.get(_url(f"/checks/{CHECK}"))

        assert response.json()["verdict"] == "passed"


class TestDeciding:
    @pytest.mark.parametrize(
        ("tail", "body", "status"),
        [
            ("/cancel", None, 200),
            ("/apply", {"pin_worse": True}, 200),
            ("/fork", {"name": "online"}, 201),
            ("/discard", None, 200),
        ],
    )
    async def test_each_decision_goes_to_the_service(self, client, tail, body, status):
        async with client() as opened:
            response = await opened.post(_url(f"/checks/{CHECK}{tail}"), json=body)

        assert response.status_code == status


class TestTestSet:
    async def test_a_skill_with_none_answers_404(self, client):
        async with client() as opened:
            response = await opened.get(_url("/test-set"))

        assert response.status_code == 404

    async def test_a_second_one_answers_409(self, client):
        async with client() as opened:
            response = await opened.post(_url("/test-set"), json={})

        assert response.status_code == 409


class TestWaitingForYou:
    async def test_the_checks_a_person_has_to_come_back_to_are_listed(self, client, service):
        async with client() as opened:
            response = await opened.get(f"{settings.API_V1_STR}/skill-checks/awaiting")

        assert response.status_code == 200
        [item] = response.json()
        assert (item["skill_name"], item["status"], item["agents"]) == ("returns", "done", 2)
        service.awaiting.assert_awaited_once()
