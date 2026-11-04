"""A model turn owns a renewable lease, without retaining a database connection."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AlreadyExistsError
from app.services import conversation_turns as module

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def database():
    yield MagicMock()


async def test_foreground_waits_for_a_return_and_releases_its_own_claim() -> None:
    claim_id = uuid4()
    with (
        patch.object(module, "get_db_context", database),
        patch.object(
            module.task_repo, "claim_turn", new=AsyncMock(side_effect=[None, claim_id])
        ) as claim,
        patch.object(module.task_repo, "release_turn", new=AsyncMock()) as release,
    ):
        async with module.claim(uuid4(), background=False) as admitted:
            assert admitted
        assert claim.await_count == 2
        release.assert_awaited_once_with(release.call_args.args[0], claim_id)


async def test_a_background_return_defers_and_a_bounded_foreground_wait_reports_busy() -> None:
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "claim_turn", new=AsyncMock(return_value=None)),
        patch.object(module, "WAIT_SECONDS", 0.01),
    ):
        async with module.claim(uuid4(), background=True) as admitted:
            assert admitted is False
        with pytest.raises(AlreadyExistsError, match="receiving a task result"):
            async with module.claim(uuid4(), background=False):
                pytest.fail("A busy topic cannot admit this turn")


async def test_a_turn_that_cannot_renew_is_stopped_and_its_lease_is_released() -> None:
    claim_id = uuid4()
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "claim_turn", new=AsyncMock(return_value=claim_id)),
        patch.object(
            module.task_repo, "renew_turn", new=AsyncMock(side_effect=[True, False])
        ) as renew,
        patch.object(module.task_repo, "release_turn", new=AsyncMock()) as release,
        patch.object(module, "RENEW_SECONDS", 0.001),
    ):
        with pytest.raises(AlreadyExistsError, match="lost its conversation admission") as error:
            async with module.claim(uuid4(), background=False):
                await asyncio.sleep(1)
        assert error.value.message is not None
        assert renew.await_count == 2
        release.assert_awaited_once()


@pytest.mark.parametrize("failure", [TimeoutError(), SQLAlchemyError()])
async def test_database_renewal_failures_stop_the_writer(failure: Exception) -> None:
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "renew_turn", new=AsyncMock(side_effect=failure)),
        patch.object(module, "RENEW_SECONDS", 0),
        pytest.raises(module._LostClaim),
    ):
        await module._renew(uuid4())


async def test_cleanup_does_not_replace_the_error_that_ended_the_turn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "claim_turn", new=AsyncMock(return_value=uuid4())),
        patch.object(
            module.task_repo, "release_turn", new=AsyncMock(side_effect=SQLAlchemyError())
        ),
    ):
        with pytest.raises(ExceptionGroup) as error:
            async with module.claim(uuid4(), background=False):
                raise ValueError("Original failure")
        assert isinstance(error.value.exceptions[0], ValueError)
        assert "conversation_turn_release_failed" in caplog.text


async def test_cleanup_timeout_is_bounded_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    async def slow_release(*_args) -> None:
        await asyncio.sleep(1)

    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "claim_turn", new=AsyncMock(return_value=uuid4())),
        patch.object(module.task_repo, "release_turn", new=slow_release),
        patch.object(module, "RELEASE_SECONDS", 0.001),
    ):
        async with module.claim(uuid4(), background=False) as admitted:
            assert admitted
    assert "conversation_turn_release_timed_out" in caplog.text
