"""Tests for the MFA routes: the second step at sign-in, and enrolment.

The factor and persistence boundaries are mocked; token issuance stays real.
These tests exercise when a sign-in stops at a challenge, what a
challenge token may and may not become, and that enrolment answers with
its secrets once and never again.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db_session,
    get_mfa_service,
    get_redis,
    get_session_service,
    get_user_service,
    require_recent_authentication,
)
from app.api.routes.v1 import auth as auth_routes
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.security import (
    create_access_token,
    create_magic_link_token,
    create_mfa_token,
    verify_special_token,
)
from app.main import app
from app.services.session import SessionService

pytestmark = pytest.mark.anyio


class MockUser:
    """Mock user for testing, with the MFA columns the routes read."""

    def __init__(self, totp_enabled: bool = False, credential_version: int = 0) -> None:
        self.id = uuid4()
        self.email = "test@example.com"
        self.full_name = "Test User"
        self.is_active = True
        self.totp_enabled = totp_enabled
        self.credential_version = credential_version
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)


@pytest.fixture
def mock_user() -> MockUser:
    return MockUser()


@pytest.fixture
def mock_user_service(mock_user: MockUser) -> MagicMock:
    service = MagicMock()
    service.authenticate = AsyncMock(return_value=mock_user)
    service.get_by_id = AsyncMock(return_value=mock_user)
    service.consume_magic_link_token = AsyncMock(return_value=(mock_user, "/dashboard"))
    return service


@pytest.fixture
def mock_session_service() -> SessionService:
    service = SessionService(MagicMock())
    service.create_session = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), created_at=datetime.now(UTC))
    )
    return service


@pytest.fixture
def mock_mfa_service() -> MagicMock:
    service = MagicMock()
    service.is_enabled = MagicMock(return_value=False)
    service.begin_setup = AsyncMock(
        return_value=(
            "otpauth://totp/AgenticOS:test@example.com?secret=JBSWY3DPEHPK3PXP",
            "JBSWY3DPEHPK3PXP",
        )
    )
    service.enable = AsyncMock(return_value=[f"CODE-{i:04d}" for i in range(10)])
    service.disable = AsyncMock()
    service.regenerate_recovery_codes = AsyncMock(return_value=[f"NEW-{i:04d}" for i in range(10)])
    service.verify_challenge = AsyncMock(return_value=True)
    return service


@pytest.fixture
async def client(
    mock_user: MockUser,
    mock_user_service: MagicMock,
    mock_session_service: SessionService,
    mock_mfa_service: MagicMock,
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncClient:
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_mfa_service] = lambda: mock_mfa_service
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[require_recent_authentication] = lambda: None
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as http:
        yield http
    app.dependency_overrides.clear()


def _login_url() -> str:
    return f"{settings.API_V1_STR}/auth/login"


def _mfa_url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/auth/mfa{suffix}"


async def test_login_without_a_second_factor_signs_in(client: AsyncClient) -> None:
    response = await client.post(
        _login_url(), data={"username": "test@example.com", "password": "secret"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert "mfa_required" not in response.json()


async def test_login_with_a_second_factor_stops_at_a_challenge(
    client: AsyncClient, mock_user: MockUser
) -> None:
    mock_user.totp_enabled = True

    response = await client.post(
        _login_url(), data={"username": "test@example.com", "password": "secret"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert "access_token" not in body
    payload = verify_special_token(body["mfa_token"], expected_type="mfa")
    assert payload is not None
    assert payload["sub"] == str(mock_user.id)
    assert payload["cv"] == mock_user.credential_version


async def test_the_challenge_and_the_code_become_a_session(
    client: AsyncClient, mock_user: MockUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset = AsyncMock()
    monkeypatch.setattr(auth_routes.rate_limit, "reset_mfa_failures", reset)
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    reset.assert_awaited_once_with(str(mock_user.id))


async def test_a_successful_mfa_challenge_cannot_be_replayed(
    client: AsyncClient, mock_user: MockUser, mock_redis: MagicMock
) -> None:
    mock_redis.set.side_effect = [True, False]
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    first = await client.post(_mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"})
    replay = await client.post(_mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"})

    assert first.status_code == 200
    assert replay.status_code == 401
    assert mock_redis.set.await_count == 2


async def test_oidc_desktop_mfa_returns_a_nonce_bound_deep_link(
    client: AsyncClient, mock_user: MockUser, mock_redis: MagicMock
) -> None:
    nonce = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    mock_redis.getdel.return_value = json.dumps(
        {
            "groups": None,
            "provider": "oidc",
            "client": {"client": "desktop", "nonce": nonce},
        }
    )
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("agenticos://auth/callback?code=")
    assert f"desktop_nonce={nonce}" in location
    exchange_payload = json.loads(mock_redis.set.await_args_list[-1].args[1])
    assert exchange_payload["code_challenge"] == nonce


async def test_a_wrong_code_at_the_second_step_is_refused(
    client: AsyncClient,
    mock_user: MockUser,
    mock_mfa_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_mfa_service.verify_challenge = AsyncMock(return_value=False)
    record = AsyncMock()
    monkeypatch.setattr(auth_routes.rate_limit, "record_mfa_failure", record)
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "000000"}
    )

    assert response.status_code == 401
    record.assert_awaited_once_with(str(mock_user.id))


async def test_locked_account_is_refused_before_the_code_is_checked(
    client: AsyncClient,
    mock_user: MockUser,
    mock_mfa_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_routes.rate_limit, "mfa_backoff_locked", AsyncMock(return_value=True))
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 429
    assert response.json()["error"]["details"]["retry_after_seconds"] == 300
    mock_mfa_service.verify_challenge.assert_not_awaited()


async def test_an_access_token_is_not_a_challenge(client: AsyncClient, mock_user: MockUser) -> None:
    access = create_access_token(subject=str(mock_user.id))

    response = await client.post(_mfa_url("/verify"), json={"mfa_token": access, "code": "123456"})

    assert response.status_code == 401


async def test_a_challenge_from_before_a_password_change_is_refused(
    client: AsyncClient, mock_user: MockUser
) -> None:
    mock_user.credential_version = 2
    challenge = create_mfa_token(subject=str(mock_user.id), credential_version=1)

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 401


async def test_a_challenge_for_an_account_that_is_gone_is_refused(
    client: AsyncClient, mock_user: MockUser, mock_user_service: MagicMock
) -> None:
    mock_user_service.get_by_id = AsyncMock(side_effect=NotFoundError(message="User not found"))
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 401


async def test_a_magic_link_challenge_carries_its_destination_through(
    client: AsyncClient, mock_user: MockUser
) -> None:
    challenge = create_mfa_token(
        subject=str(mock_user.id),
        credential_version=mock_user.credential_version,
        return_to="/dashboard",
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 200
    assert response.json()["return_to"] == "/dashboard"


async def test_a_magic_link_sign_in_with_a_second_factor_stops_at_a_challenge(
    client: AsyncClient, mock_user: MockUser
) -> None:
    mock_user.totp_enabled = True

    response = await client.post(
        f"{settings.API_V1_STR}/auth/magic-link/verify",
        json={"token": "magic-link-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert body["return_to"] == "/dashboard"


async def test_a_magic_link_mfa_challenge_preserves_its_mailbox_proof(
    client: AsyncClient,
    mock_user: MockUser,
    mock_session_service: SessionService,
) -> None:
    mock_user.totp_enabled = True
    link = create_magic_link_token(
        subject=str(mock_user.id), email=mock_user.email, return_to="/dashboard"
    )
    challenge = await client.post(
        f"{settings.API_V1_STR}/auth/magic-link/verify", json={"token": link}
    )
    assert challenge.status_code == 200
    mfa_token = challenge.json()["mfa_token"]
    payload = verify_special_token(mfa_token, expected_type="mfa")
    assert payload is not None and payload.get("mbp") is True

    verified = await client.post(
        _mfa_url("/verify"), json={"mfa_token": mfa_token, "code": "123456"}
    )
    assert verified.status_code == 200
    session_args = mock_session_service.create_session.await_args.kwargs
    assert session_args["proved_email"] == mock_user.email


async def test_status_reports_whether_the_second_factor_is_on(
    client: AsyncClient, mock_mfa_service: MagicMock
) -> None:
    mock_mfa_service.is_enabled = MagicMock(return_value=True)

    response = await client.get(_mfa_url("/status"))

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


async def test_setup_rejects_an_access_token_without_recent_authentication(
    client: AsyncClient, mock_mfa_service: MagicMock
) -> None:
    app.dependency_overrides.pop(require_recent_authentication)
    token = create_access_token(subject=str(uuid4()))

    response = await client.post(_mfa_url("/setup"), headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    mock_mfa_service.begin_setup.assert_not_awaited()


async def test_mfa_status_accepts_a_recently_authenticated_access_token(
    client: AsyncClient, mock_mfa_service: MagicMock
) -> None:
    app.dependency_overrides.pop(require_recent_authentication)
    token = create_access_token(subject=str(uuid4()), auth_time=int(datetime.now(UTC).timestamp()))

    response = await client.get(_mfa_url("/status"), headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


async def test_mfa_status_rejects_an_old_authentication(
    client: AsyncClient,
) -> None:
    app.dependency_overrides.pop(require_recent_authentication)
    token = create_access_token(
        subject=str(uuid4()),
        auth_time=int((datetime.now(UTC) - timedelta(minutes=6)).timestamp()),
    )

    response = await client.get(_mfa_url("/status"), headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


@pytest.mark.security
async def test_setup_answers_with_the_provisioning_uri_and_the_secret_once(
    client: AsyncClient, mock_user: MockUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(auth_routes, "enforce_auth_limit", enforce)
    response = await client.post(_mfa_url("/setup"))

    assert response.status_code == 201
    body = response.json()
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["secret"] == "JBSWY3DPEHPK3PXP"
    enforce.assert_awaited_once()
    assert enforce.await_args.args[0].url.path.endswith("/mfa/setup")
    assert enforce.await_args.kwargs == {
        "surface": "auth_mfa_manage",
        "identifier": str(mock_user.id),
    }


async def test_enable_answers_with_the_recovery_codes_once(
    client: AsyncClient, mock_user: MockUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(auth_routes, "enforce_auth_limit", enforce)
    response = await client.post(_mfa_url("/enable"), json={"code": "123456"})

    assert response.status_code == 200
    assert len(response.json()["recovery_codes"]) == 10
    enforce.assert_awaited_once()
    assert enforce.await_args.args[0].url.path.endswith("/mfa/enable")
    assert enforce.await_args.kwargs == {
        "surface": "auth_mfa_manage",
        "identifier": str(mock_user.id),
    }


async def test_a_signin_challenge_is_capped_independently_of_user_rate_limit(
    client: AsyncClient, mock_user: MockUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import rate_limit

    async def consume(**kwargs: object) -> rate_limit.Decision:
        if kwargs.get("surface") == "auth_mfa_challenge":
            return rate_limit.Decision(allowed=False, retry_after_seconds=300)
        return rate_limit.Decision(allowed=True, retry_after_seconds=0)

    limited = AsyncMock(side_effect=consume)
    monkeypatch.setattr(auth_routes.rate_limit, "consume", limited)
    challenge = create_mfa_token(
        subject=str(mock_user.id), credential_version=mock_user.credential_version
    )

    response = await client.post(
        _mfa_url("/verify"), json={"mfa_token": challenge, "code": "123456"}
    )

    assert response.status_code == 429
    assert "Too many attempts for this sign-in step" in response.json()["error"]["message"]
    assert [call.kwargs["surface"] for call in limited.await_args_list] == [
        "auth_mfa_verify",
        "auth_mfa_verify",
        "auth_mfa_challenge",
    ]
    challenge_limit = limited.await_args_list[-1].kwargs
    assert challenge_limit["limit"].attempts == 5
    assert challenge_limit["limit"].window_seconds == 300
    assert challenge_limit["caller"].startswith("token:")
    assert not challenge_limit["caller"].endswith(challenge)


async def test_disable_answers_with_no_body(client: AsyncClient) -> None:
    response = await client.post(_mfa_url("/disable"), json={"code": "123456"})

    assert response.status_code == 204
    assert response.content == b""


async def test_regenerating_recovery_codes_answers_with_the_new_set_once(
    client: AsyncClient,
) -> None:
    response = await client.post(_mfa_url("/recovery-codes"), json={"code": "123456"})

    assert response.status_code == 200
    assert response.json()["recovery_codes"][0] == "NEW-0000"
