"""The outcome routes, wired (#2575)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

PERSON, ORG, OUTCOME, CHAT = uuid4(), uuid4(), uuid4(), uuid4()


def _row(status: str = "open") -> SimpleNamespace:
    return SimpleNamespace(
        id=OUTCOME,
        kind="finding",
        summary="Found it",
        context_url="/inbox",
        status=status,
        source_conversation_id=CHAT,
        created_at=datetime.now(UTC),
        settled_at=None,
        settled_via=None,
    )


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.VIEWER)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_viewer_lists_their_open_outcomes_for_one_chat() -> None:
    listed = AsyncMock(return_value=[_row()])
    with patch("app.services.outcome.OutcomeService.list_mine", new=listed):
        async with _client() as client:
            response = await client.get(
                f"{settings.API_V1_STR}/outcomes", params={"conversation_id": str(CHAT)}
            )

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert (item["id"], item["status"], item["summary"]) == (str(OUTCOME), "open", "Found it")
    assert listed.await_args.kwargs == {"open_only": True, "conversation_id": CHAT}


async def test_a_viewer_settles_their_own_outcome_and_says_where() -> None:
    settled = AsyncMock(return_value=_row("resolved"))
    with patch("app.services.outcome.OutcomeService.settle", new=settled):
        async with _client() as client:
            response = await client.post(
                f"{settings.API_V1_STR}/outcomes/{OUTCOME}/settle",
                json={"action": "resolve", "via": "chat"},
            )

    assert response.status_code == 200 and response.json()["status"] == "resolved"
    assert settled.await_args.args[1:3] == (OUTCOME, "resolve")
    assert settled.await_args.kwargs == {"via": "chat"}


@pytest.mark.parametrize(
    ("failure", "code"),
    [(NotFoundError(message="Outcome not found"), 404), (ConflictError(message="closed"), 409)],
)
async def test_somebody_elses_or_a_closed_outcome_is_refused(failure: Exception, code: int) -> None:
    with patch("app.services.outcome.OutcomeService.settle", new=AsyncMock(side_effect=failure)):
        async with _client() as client:
            response = await client.post(
                f"{settings.API_V1_STR}/outcomes/{OUTCOME}/settle", json={"action": "mute"}
            )

    assert response.status_code == code


async def test_an_unknown_action_is_a_validation_error() -> None:
    async with _client() as client:
        response = await client.post(
            f"{settings.API_V1_STR}/outcomes/{OUTCOME}/settle", json={"action": "delete"}
        )

    assert response.status_code == 422
