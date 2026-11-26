"""Device flow is private, interval-bound, single-use and cannot revive a deleted connection."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import httpx2
import pytest
from pydantic_ai.providers.github_copilot import GitHubCopilotDeviceAuthorization

from app.clients.github_copilot import CopilotGrant, CopilotModel, CopilotPending
from app.clients.redis import RedisClient
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.schemas.personal_model_key import PersonalModelDestination
from app.services import copilot_sign_in as module
from app.services.copilot_sign_in import CopilotSignInService
from tests.test_personal_model_keys import context

pytestmark = pytest.mark.anyio


class MemoryRedis(RedisClient):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.values.get(key) != value:
            return False
        del self.values[key]
        return True

    async def replace_if_equal(self, key: str, expected: str, value: str, *, ttl: int) -> bool:
        if self.values.get(key) != expected:
            return False
        self.values[key] = value
        return True


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 18, 12, tzinfo=UTC)

    def now(self, zone: tzinfo) -> datetime:
        return self.at.astimezone(zone)

    def advance(self, seconds: int) -> None:
        self.at += timedelta(seconds=seconds)


class Account:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.polled: list[tuple[str, str]] = []
        self.listed: list[str] = []
        self.challenge = GitHubCopilotDeviceAuthorization(
            device_code="private-device-code",
            user_code="OWN-CODE",
            verification_uri="https://github.com/login/device",
            expires_in=900,
            interval=5,
        )
        self.result: CopilotGrant | CopilotPending = CopilotGrant(
            access_token="private-user-token", token_type="bearer"
        )
        self.models_result = [
            CopilotModel(id="plan-model", supported_endpoints=["/chat/completions"])
        ]
        self.error: Exception | None = None

    async def start(self, client_id: str) -> GitHubCopilotDeviceAuthorization:
        self.started.append(client_id)
        return self.challenge

    async def poll(self, *, client_id: str, device_code: str) -> CopilotGrant | CopilotPending:
        self.polled.append((client_id, device_code))
        if self.error is not None:
            raise self.error
        return self.result

    async def models(self, token: str) -> list[CopilotModel]:
        self.listed.append(token)
        return self.models_result


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    value = Clock()
    monkeypatch.setattr(module, "datetime", value)
    return value


@pytest.fixture
def destination() -> PersonalModelDestination:
    return PersonalModelDestination(
        profile_id=uuid4(), provider="github_copilot", endpoint=None, model="plan-model"
    )


@pytest.fixture
def service(
    monkeypatch: pytest.MonkeyPatch, destination: PersonalModelDestination
) -> CopilotSignInService:
    value = CopilotSignInService(
        AsyncMock(), MemoryRedis(), Account(), client_id="agenticos-client"
    )
    monkeypatch.setattr(value.keys, "destination", AsyncMock(return_value=destination))
    monkeypatch.setattr(module.key_repo, "bump_generation", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(module.key_repo, "claim_generation", AsyncMock(return_value=True))
    monkeypatch.setattr(module.key_repo, "save", AsyncMock())
    monkeypatch.setattr(module, "record_audit", AsyncMock())
    return value


async def test_start_returns_own_code_but_never_device_code_or_account_token(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    challenge = await service.start(context(), uuid4(), destination)
    assert challenge.user_code == "OWN-CODE" and challenge.poll_after_seconds == 5
    assert challenge.expires_at == clock.at + timedelta(seconds=900)
    assert "private-device-code" not in challenge.model_dump_json()
    assert "private-user-token" not in challenge.model_dump_json()
    assert len(challenge.handle) >= 32


@pytest.mark.parametrize("change", ["client", "provider", "endpoint", "model", "profile"])
async def test_wrong_setup_or_destination_does_not_start_oauth(
    service: CopilotSignInService, destination: PersonalModelDestination, change: str, clock: Clock
) -> None:
    expected = destination
    if change == "client":
        service.client_id = ""
    elif change == "model":
        expected = destination.model_copy(update={"model": "changed"})
    elif change == "profile":
        expected = destination.model_copy(update={"profile_id": uuid4()})
    else:
        actual = destination.model_copy(
            update={"provider": "github"}
            if change == "provider"
            else {"endpoint": "https://elsewhere.example"}
        )
        service.keys.destination = AsyncMock(return_value=actual)
        expected = actual
    with pytest.raises((BadRequestError, ConflictError)):
        await service.start(context(), uuid4(), expected)
    assert isinstance(service.account, Account) and not service.account.started


@pytest.mark.parametrize("expires,interval", [(3601, 5), (3, 5)])
async def test_unsupported_device_timing_is_not_persisted(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    expires: int,
    interval: int,
    clock: Clock,
) -> None:
    assert isinstance(service.account, Account)
    service.account.challenge = replace(
        service.account.challenge, expires_in=expires, interval=interval
    )
    with pytest.raises(BadRequestError, match="timing"):
        await service.start(context(), uuid4(), destination)
    assert isinstance(service.redis, MemoryRedis) and not service.redis.values


async def test_poll_waits_then_saves_only_a_verified_owner_sealed_token(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert (await service.poll(ctx, agent, challenge.handle)).poll_after_seconds == 5
    assert isinstance(service.account, Account) and not service.account.polled
    clock.advance(6)
    result = await service.poll(ctx, agent, challenge.handle)
    assert result.status == "connected"
    assert service.account.polled == [("agenticos-client", "private-device-code")]
    assert service.account.listed == ["private-user-token"]
    assert isinstance(module.key_repo.save, AsyncMock)
    assert isinstance(module.record_audit, AsyncMock)
    saved = module.key_repo.save.call_args.kwargs
    assert saved["user_id"] == ctx.user_id and saved["organization_id"] == ctx.organization_id
    assert "private-user-token" not in saved["sealed_secret"]
    assert "private-user-token" not in str(module.record_audit.call_args)
    with pytest.raises(NotFoundError):
        await service.poll(ctx, agent, challenge.handle)


@pytest.mark.security
@pytest.mark.parametrize("change", ["user", "tenant", "agent"])
async def test_other_identities_cannot_consume_or_inspect_a_sign_in(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock, change: str
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    other = (
        replace(ctx, user_id=uuid4())
        if change == "user"
        else replace(ctx, organization_id=uuid4())
        if change == "tenant"
        else ctx
    )
    with pytest.raises(NotFoundError):
        await service.poll(other, uuid4() if change == "agent" else agent, challenge.handle)
    clock.advance(6)
    assert (await service.poll(ctx, agent, challenge.handle)).status == "connected"


@pytest.mark.parametrize("change", ["expired", "application"])
async def test_expired_or_reconfigured_app_requires_a_new_sign_in(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock, change: str
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    if change == "expired":
        clock.advance(901)
    else:
        service.client_id = "new-app"
    with pytest.raises(BadRequestError, match="expired"):
        await service.poll(ctx, agent, challenge.handle)
    with pytest.raises(NotFoundError):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(service.account, Account) and not service.account.polled


async def test_slow_down_advances_interval_and_pending_never_stores_a_key(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert isinstance(service.account, Account)
    service.account.result = CopilotPending(error="slow_down", interval=12)
    clock.advance(6)
    assert (await service.poll(ctx, agent, challenge.handle)).poll_after_seconds == 12
    assert (await service.poll(ctx, agent, challenge.handle)).poll_after_seconds == 12
    clock.advance(13)
    service.account.result = CopilotPending(error="authorization_pending")
    assert (await service.poll(ctx, agent, challenge.handle)).poll_after_seconds == 12
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        BadRequestError(message="Denied"),
        httpx2.ConnectError("unknown acceptance"),
        ValueError("bug"),
    ],
)
async def test_failed_or_unknown_exchange_is_not_replayed(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    error: Exception,
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert isinstance(service.account, Account)
    service.account.error = error
    clock.advance(6)
    with pytest.raises(BadRequestError if isinstance(error, httpx2.HTTPError) else type(error)):
        await service.poll(ctx, agent, challenge.handle)
    with pytest.raises(NotFoundError):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


async def test_missing_account_model_does_not_persist_authorization(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert isinstance(service.account, Account)
    service.account.models_result = []
    clock.advance(6)
    with pytest.raises(BadRequestError, match="selected model"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


@pytest.mark.security
async def test_a_replaced_or_deleted_connection_cannot_be_revived_by_an_older_grant(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert isinstance(module.key_repo.claim_generation, AsyncMock)
    module.key_repo.claim_generation.return_value = False
    clock.advance(6)
    with pytest.raises(ConflictError, match="No older grant"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


async def test_parallel_poll_is_throttled_and_does_not_exchange_the_device_code_twice(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = anyio.Event(), anyio.Event()
    calls = 0

    async def poll(*, client_id: str, device_code: str) -> CopilotPending:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return CopilotPending(error="authorization_pending")

    monkeypatch.setattr(service.account, "poll", poll)
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    clock.advance(6)

    async def first() -> None:
        await service.poll(ctx, agent, challenge.handle)

    async with anyio.create_task_group() as group:
        group.start_soon(first)
        await entered.wait()
        assert (await service.poll(ctx, agent, challenge.handle)).status == "pending"
        release.set()
    assert calls == 1


async def test_cancellation_consumes_an_unknown_exchange_and_releases_its_lease(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def poll(*, client_id: str, device_code: str) -> None:
        await anyio.sleep_forever()

    monkeypatch.setattr(service.account, "poll", poll)
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    clock.advance(6)
    with anyio.move_on_after(0.01) as cancelled:
        await service.poll(ctx, agent, challenge.handle)
    assert cancelled.cancel_called
    assert isinstance(service.redis, MemoryRedis) and not service.redis.values


async def test_expiry_during_a_pending_reply_does_not_extend_the_device_grant(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def poll(*, client_id: str, device_code: str) -> CopilotPending:
        clock.advance(901)
        return CopilotPending(error="authorization_pending")

    monkeypatch.setattr(service.account, "poll", poll)
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    clock.advance(6)
    with pytest.raises(BadRequestError, match="expired"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


async def test_changed_pending_record_is_not_exchanged_or_overwritten(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    raw = await service.redis.get(module._PREFIX + challenge.handle)
    assert raw is not None
    monkeypatch.setattr(service.redis, "get", AsyncMock(side_effect=[raw, raw + " "]))
    clock.advance(6)
    with pytest.raises(ConflictError, match="changed"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(service.account, Account) and not service.account.polled


@pytest.mark.parametrize("pending", [True, False])
async def test_an_expired_or_consumed_record_is_never_revived_by_a_late_reply(
    service: CopilotSignInService,
    destination: PersonalModelDestination,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    pending: bool,
) -> None:
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    assert isinstance(service.account, Account)
    service.account.result = (
        CopilotPending(error="authorization_pending") if pending else service.account.result
    )
    if pending:
        monkeypatch.setattr(service.redis, "replace_if_equal", AsyncMock(return_value=False))
    else:
        original = service.redis.delete_if_equal

        async def consume(key: str, value: str) -> bool:
            if key == module._PREFIX + challenge.handle:
                return False
            return await original(key, value)

        monkeypatch.setattr(service.redis, "delete_if_equal", consume)
    clock.advance(6)
    with pytest.raises(ConflictError, match="consumed"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()


async def test_publish_or_model_change_during_authorization_does_not_change_the_destination(
    service: CopilotSignInService, destination: PersonalModelDestination, clock: Clock
) -> None:
    service.keys.destination = AsyncMock(
        side_effect=[
            destination,
            destination,
            destination.model_copy(update={"model": "different-model"}),
        ]
    )
    ctx, agent = context(), uuid4()
    challenge = await service.start(ctx, agent, destination)
    clock.advance(6)
    with pytest.raises(ConflictError, match="destination changed"):
        await service.poll(ctx, agent, challenge.handle)
    assert isinstance(module.key_repo.save, AsyncMock)
    module.key_repo.save.assert_not_called()
