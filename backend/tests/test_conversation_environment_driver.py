"""Physical ownership is checked in the same transaction as each fenced claim."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.services import conversation_environment_driver as drivers

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    db = AsyncMock()
    entered = []

    @asynccontextmanager
    async def session():
        entered.append(True)
        try:
            yield db
        finally:
            entered.pop()

    check = AsyncMock()

    async def validate(actual):
        assert entered and actual is db
        await check(actual)

    monkeypatch.setattr(drivers, "get_db_context", session)
    for name, result in [("claim_driver", True), ("renew_driver", True), ("release_driver", None)]:
        operation = AsyncMock(return_value=result)

        async def effect(*args, _operation=operation, **kwargs):
            assert entered
            return _operation.return_value

        operation.side_effect = effect
        monkeypatch.setattr(drivers.environments, name, operation)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    return drivers.EnvironmentDriver("same-physical-screen", ctx, "human", validate), check


async def test_claim_renew_and_release_are_fenced_and_cleanup_is_idempotent(case):
    driver, check = case
    try:
        await driver.acquire()
        await driver.require()
        assert check.await_count == 2
        assert drivers.environments.claim_driver.await_args.kwargs["token"] == driver.token
        assert drivers.environments.renew_driver.await_args.kwargs["token"] == driver.token
    finally:
        await driver.close()
    await driver.close()
    assert drivers.environments.release_driver.await_count == 1
    assert driver._heartbeat is not None and driver._heartbeat.done()
    with pytest.raises(ConflictError):
        await driver.require()


async def test_a_busy_physical_screen_is_never_taken_from_another_driver(case):
    driver, _ = case
    drivers.environments.claim_driver.return_value = False
    with pytest.raises(ConflictError):
        await driver.acquire()
    assert driver._heartbeat is None
    await driver.close()


async def test_authority_revocation_stops_before_claim_or_input(case):
    driver, check = case
    check.side_effect = AuthorizationError(message="Membership was revoked")
    with pytest.raises(AuthorizationError):
        await driver.acquire()
    drivers.environments.claim_driver.assert_not_awaited()
    check.side_effect = None
    await driver.acquire()
    try:
        check.side_effect = AuthorizationError(message="Membership was revoked")
        with pytest.raises(AuthorizationError):
            await driver.require()
        drivers.environments.renew_driver.assert_not_awaited()
    finally:
        await driver.close()


async def test_a_lost_token_cannot_send_another_input(case):
    driver, _ = case
    await driver.acquire()
    try:
        drivers.environments.renew_driver.return_value = False
        with pytest.raises(ConflictError):
            await driver.require()
    finally:
        await driver.close()


@pytest.mark.parametrize("fails", [False, True])
async def test_heartbeat_failure_is_sticky_and_never_hides_as_valid_control(
    case, monkeypatch, fails
):
    driver, check = case

    async def tick(_seconds):
        return None

    monkeypatch.setattr(drivers.anyio, "sleep", tick)
    if fails:
        check.side_effect = AuthorizationError(message="Lost membership")
    else:
        drivers.environments.renew_driver.return_value = False
    await driver._beat()
    with pytest.raises(ConflictError):
        await driver.require()
    await driver.close()


async def test_adoption_callback_runs_only_after_successful_physical_claim(case):
    driver, _ = case
    adoption = AsyncMock()
    driver._on_acquired = adoption
    drivers.environments.claim_driver.return_value = False
    with pytest.raises(ConflictError):
        await driver.acquire()
    adoption.assert_not_awaited()
    drivers.environments.claim_driver.return_value = True
    await driver.acquire()
    try:
        adoption.assert_awaited_once_with(drivers.environments.claim_driver.await_args.args[0])
    finally:
        await driver.close()


async def test_healthy_heartbeat_keeps_running_until_a_later_lease_loss(case, monkeypatch):
    driver, _ = case

    async def tick(_seconds):
        return None

    monkeypatch.setattr(drivers.anyio, "sleep", tick)
    renew = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(driver, "_renew", renew)
    await driver._beat()
    assert renew.await_count == 2
    with pytest.raises(ConflictError):
        await driver.require()


async def test_release_timeout_does_not_block_process_shutdown(case, monkeypatch, caplog):
    driver, _ = case
    original = drivers.anyio.move_on_after
    monkeypatch.setattr(
        drivers.anyio, "move_on_after", lambda _seconds, **options: original(0.001, **options)
    )

    async def blocked(*_args, **_kwargs):
        await drivers.anyio.sleep_forever()

    drivers.environments.release_driver.side_effect = blocked
    await driver.close()
    assert "environment_driver_release_timed_out" in caplog.text
