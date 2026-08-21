"""The auth surface carries a rate limit, at the route.

No route in `auth.py` was rate-limited, and `verify_password` runs bcrypt -
~170ms with no suspension point. Unmetered, a `/login` flood for any address
that has an account saturates a worker's event loop with no credentials at all
(#947). These assert the limiter is wired to the route, not merely present in
the module: `test_rate_limit.py` covers the limiter itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.main import app
from app.services import rate_limit

pytestmark = pytest.mark.anyio


def _redis_counting(count: int) -> MagicMock:
    """A shared-Redis stand-in whose window counter always answers `count`."""
    client = MagicMock()
    client.count_in_window = AsyncMock(return_value=count)
    return client


@pytest.fixture(autouse=True)
def _reset_limiter():
    yield
    rate_limit.configure(None)


async def test_login_over_the_window_is_refused_with_429(client: AsyncClient, monkeypatch):
    """The Nth attempt inside the minute, refused before authenticate - and so
    before bcrypt - is the whole point: the refusal has to cost less than the
    attack it stops."""
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
    rate_limit.configure(_redis_counting(4))

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "victim@example.com", "password": "guess"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


async def test_login_inside_the_window_reaches_the_service(client: AsyncClient, monkeypatch):
    """The refusal is about the rate, not about login: under the window the
    request reaches the service, which answers 401 on bad credentials."""
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
    rate_limit.configure(_redis_counting(1))
    service = MagicMock()
    service.authenticate = AsyncMock(side_effect=AuthenticationError(message="Invalid"))
    app.dependency_overrides[deps.get_user_service] = lambda: service

    try:
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "victim@example.com", "password": "guess"},
        )
    finally:
        app.dependency_overrides.pop(deps.get_user_service, None)

    assert response.status_code == 401
    service.authenticate.assert_awaited_once()
