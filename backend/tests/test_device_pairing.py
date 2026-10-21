"""Signing a phone in by scanning the console's QR (#2097).

The code is single-use, lives a minute, and holds no tokens: the session is
opened when the phone redeems it, under the phone's own user agent. A password
changed - or an account deactivated - between showing and scanning refuses it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import verify_token
from app.main import app
from app.services.device_pairing import PAIRING_TTL_SECONDS, DevicePairingService

pytestmark = pytest.mark.anyio

_ISSUE = f"{settings.API_V1_STR}/auth/pairing-codes"
_REDEEM = f"{settings.API_V1_STR}/auth/pairing-codes/redeem"


class _FakeRedis:
    """An in-memory stand-in with the two methods pairing touches, and the TTL it was given."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)


def _user(*, active: bool = True, version: int = 3) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), is_active=active, credential_version=version)


def _service(
    user: SimpleNamespace, redis: _FakeRedis | None = None
) -> tuple[DevicePairingService, MagicMock]:
    users = MagicMock(get_by_id=AsyncMock(return_value=user))
    sessions = MagicMock(create_session=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    return DevicePairingService(redis or _FakeRedis(), users, sessions), sessions


async def test_a_code_lives_a_minute_and_carries_no_tokens() -> None:
    redis = _FakeRedis()
    user = _user()
    service, _ = _service(user, redis)

    issued = await service.issue(user)

    assert issued.expires_in == PAIRING_TTL_SECONDS == 60
    (key,) = redis.store
    assert redis.ttls[key] == 60
    assert "token" not in redis.store[key]
    assert str(user.id) in redis.store[key]


async def test_redeeming_opens_the_phones_own_session_once() -> None:
    user = _user()
    service, sessions = _service(user)
    issued = await service.issue(user)

    paired = await service.redeem(issued.code, ip_address="10.0.0.9", user_agent="AgenticOS iOS")

    sessions.create_session.assert_awaited_once()
    call = sessions.create_session.await_args.kwargs
    assert call["user_id"] == user.id
    assert call["user_agent"] == "AgenticOS iOS"
    assert call["ip_address"] == "10.0.0.9"
    claims = verify_token(paired.access_token)
    assert claims is not None and claims["sub"] == str(user.id)
    assert claims["sid"] == str(sessions.create_session.return_value.id)
    with pytest.raises(AuthenticationError):
        await service.redeem(issued.code, ip_address=None, user_agent=None)


async def test_an_unknown_code_is_refused_without_opening_anything() -> None:
    service, sessions = _service(_user())
    with pytest.raises(AuthenticationError):
        await service.redeem("never-issued", ip_address=None, user_agent=None)
    sessions.create_session.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [{"active": False}, {"version": 4}],
    ids=["account deactivated", "password changed"],
)
async def test_a_code_shown_before_the_account_changed_is_refused(changed: dict) -> None:
    shown = _user()
    now = SimpleNamespace(
        id=shown.id,
        is_active=changed.get("active", True),
        credential_version=changed.get("version", shown.credential_version),
    )
    redis = _FakeRedis()
    service, sessions = _service(now, redis)
    issued = await DevicePairingService(redis, MagicMock(), MagicMock()).issue(shown)

    with pytest.raises(AuthenticationError):
        await service.redeem(issued.code, ip_address=None, user_agent=None)
    sessions.create_session.assert_not_awaited()


async def test_the_routes_issue_for_the_caller_and_redeem_for_the_phone(
    client: AsyncClient,
) -> None:
    caller = _user()
    pairing = MagicMock(
        issue=AsyncMock(return_value=SimpleNamespace(code="c0de", expires_in=60)),
        redeem=AsyncMock(return_value=SimpleNamespace(access_token="acc", refresh_token="ref")),
    )
    app.dependency_overrides[deps.get_current_user] = lambda: caller
    app.dependency_overrides[deps.get_device_pairing_service] = lambda: pairing

    issued = await client.post(_ISSUE)
    redeemed = await client.post(
        _REDEEM, json={"code": "c0de"}, headers={"User-Agent": "AgenticOS iOS"}
    )

    assert issued.status_code == 201
    assert issued.json() == {"code": "c0de", "expires_in": 60}
    pairing.issue.assert_awaited_once_with(caller)
    assert redeemed.status_code == 200
    assert redeemed.json()["access_token"] == "acc"
    assert pairing.redeem.await_args.kwargs["user_agent"] == "AgenticOS iOS"


async def test_issuing_needs_a_signed_in_caller_and_a_bad_code_answers_401(
    client: AsyncClient,
) -> None:
    pairing = MagicMock(redeem=AsyncMock(side_effect=AuthenticationError(message="expired")))
    app.dependency_overrides[deps.get_device_pairing_service] = lambda: pairing

    assert (await client.post(_ISSUE)).status_code == 401
    assert (await client.post(_REDEEM, json={"code": "nope"})).status_code == 401


def test_the_service_is_wired_over_redis_and_the_request_session() -> None:
    service = deps.get_device_pairing_service(MagicMock(), MagicMock())
    assert isinstance(service, DevicePairingService)
