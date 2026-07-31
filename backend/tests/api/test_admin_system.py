"""The admin system-health endpoint.

Two things worth a test through the app rather than against the service: that it
refuses a caller who is not an app admin - the whole reason the probe details can
be published at all - and that every check it returns carries the detail of what
was verified. A row that says "healthy" and nothing else is what the admin page
used to render, and it rendered it for services nothing had checked.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db_session, get_redis
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def one(self) -> Any:
        return self._value


class _Session:
    """Answers the probes' queries in the order they run them."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)

    async def execute(self, statement: Any) -> _Result:
        assert self._answers, "the probes ran more queries than the fake was given"
        return _Result(self._answers.pop(0))


class _User:
    def __init__(self, role: str) -> None:
        self.id = uuid4()
        self.email = f"{role}@example.com"
        # /admin/* gates on the platform flag, which is now the only one.
        self.is_app_admin = role == "admin"
        self.is_active = True
        self.created_at = datetime.now(UTC)


def _client(user: _User, mock_redis: Any) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_redis] = lambda: mock_redis
    # SELECT 1, the pgvector version, the embedding table count, then the
    # (profiles, organizations) pair.
    app.dependency_overrides[get_db_session] = lambda: _Session(1, "0.8.0", 2, (3, 2))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def admin_client(mock_redis: Any) -> AsyncGenerator[AsyncClient, None]:
    async with _client(_User("admin"), mock_redis) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def member_client(mock_redis: Any) -> AsyncGenerator[AsyncClient, None]:
    async with _client(_User("user"), mock_redis) as client:
        yield client
    app.dependency_overrides.clear()


async def test_every_check_says_what_it_verified(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"{settings.API_V1_STR}/admin/system")

    assert response.status_code == 200
    checks = response.json()["checks"]
    assert [check["key"] for check in checks] == [
        "database",
        "redis",
        "vector_store",
        "model_access",
    ]
    assert all(check["detail"] for check in checks)
    by_key = {check["key"]: check for check in checks}
    assert "pgvector 0.8.0" in by_key["vector_store"]["detail"]
    assert "3 model profile(s)" in by_key["model_access"]["detail"]


async def test_a_member_cannot_read_the_deployment_s_configuration(
    member_client: AsyncClient,
) -> None:
    """The details name extension versions and how much is configured.

    Publishing those is only defensible because this endpoint is behind an admin
    session; the readiness probe, which anyone can reach, says none of it.
    """
    response = await member_client.get(f"{settings.API_V1_STR}/admin/system")

    assert response.status_code == 403
