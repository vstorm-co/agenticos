"""The generated-case routes, through the app.

`tests/api/test_platform_routes.py` proves the routes delegate access to the
service; `tests/integration/test_case_generation.py` proves what the service
does against Postgres. What is left is the HTTP layer: the status each route
answers with, and that a decision reaches the service as the client sent it.
"""

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
from app.schemas.case_generation import (
    CaseGenerationEstimate,
    CaseGenerationList,
    CaseGenerationRead,
    CaseProposalList,
    CaseProposalRead,
)
from app.schemas.dataset import DatasetVersionRead

pytestmark = pytest.mark.anyio

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

_NOW = datetime(2026, 10, 13, tzinfo=UTC)
_DATASET = uuid.uuid4()
_GENERATION = CaseGenerationRead(
    id=uuid.uuid4(),
    agent_id=uuid.uuid4(),
    sources=["knowledge", "red_team"],
    requested_count=20,
    status="ready",
    proposed_count=18,
    accepted_count=0,
    dismissed_count=0,
    created_at=_NOW,
)
_PROPOSAL = CaseProposalRead(
    id=uuid.uuid4(),
    generation_id=_GENERATION.id,
    origin="knowledge",
    input="How long is the return window?",
    source_document_id=uuid.uuid4(),
    created_at=_NOW,
)
_VERSION = DatasetVersionRead(
    id=uuid.uuid4(), number=3, case_count=5, change="generate", changed_cases=2, created_at=_NOW
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_generations = AsyncMock(return_value=CaseGenerationList(items=[_GENERATION]))
    stub.list_proposals = AsyncMock(return_value=CaseProposalList(items=[_PROPOSAL], total=1))
    stub.accept = AsyncMock(return_value=_VERSION)
    stub.dismiss = AsyncMock(return_value=None)
    stub.estimate = AsyncMock(
        return_value=CaseGenerationEstimate(
            count=20, sources=[], excluded_collections=0, estimated_cost_usd=None
        )
    )
    stub.start = AsyncMock(return_value=_GENERATION.model_copy(update={"status": "running"}))
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_case_generation_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str) -> str:
    return f"{settings.API_V1_STR}/datasets/{_DATASET}{suffix}"


async def test_each_route_answers_with_its_status(client: OpenClient) -> None:
    async with client() as http:
        generations = await http.get(_url("/generations"))
        proposals = await http.get(_url(f"/proposals?generation_id={_GENERATION.id}"))
        accepted = await http.post(
            _url("/proposals/accept"), json={"items": [{"id": str(_PROPOSAL.id)}]}
        )
        dismissed = await http.post(_url("/proposals/dismiss"), json={"ids": [str(_PROPOSAL.id)]})

    assert generations.json()["items"][0]["status"] == "ready"
    assert proposals.json()["items"][0]["origin"] == "knowledge"
    assert (accepted.status_code, accepted.json()["change"]) == (201, "generate")
    assert dismissed.status_code == 204


async def test_an_edited_draft_reaches_the_service_as_sent(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        await http.post(
            _url("/proposals/accept"),
            json={
                "items": [
                    {
                        "id": str(_PROPOSAL.id),
                        "content": {"input": "Reworded?", "reference_answer": "Yes."},
                    }
                ]
            },
        )

    (item,) = service.accept.await_args.args[2].items
    assert (item.id, item.content.input) == (_PROPOSAL.id, "Reworded?")


async def test_an_empty_decision_is_refused_before_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        response = await http.post(_url("/proposals/accept"), json={"items": []})
    assert response.status_code == 422
    service.accept.assert_not_awaited()


async def test_drafts_already_decided_are_a_404(client: OpenClient, service: MagicMock) -> None:
    service.dismiss.side_effect = NotFoundError(message="already decided", details={})
    async with client() as http:
        response = await http.post(_url("/proposals/dismiss"), json={"ids": [str(uuid.uuid4())]})
    assert response.status_code == 404


async def test_an_estimate_answers_200_and_a_start_202(
    client: OpenClient, service: MagicMock
) -> None:
    body = {"agent_id": str(uuid.uuid4()), "sources": ["red_team", "agent"], "count": 20}
    async with client() as http:
        estimate = await http.post(_url("/generations/estimate"), json=body)
        started = await http.post(_url("/generations"), json=body)

    assert (estimate.status_code, estimate.json()["estimated_cost_usd"]) == (200, None)
    assert (started.status_code, started.json()["status"]) == (202, "running")
    request = service.start.await_args.args[2]
    assert request.sources == ["agent", "red_team"]


async def test_a_generation_past_the_ceiling_is_refused_before_the_service(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        response = await http.post(
            _url("/generations"),
            json={"agent_id": str(uuid.uuid4()), "sources": ["agent"], "count": 51},
        )
    assert response.status_code == 422
    service.start.assert_not_awaited()
