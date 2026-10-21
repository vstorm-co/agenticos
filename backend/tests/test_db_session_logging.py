"""A domain refusal is not an application error in the log (#19).

Every exception through the session dependency used to be logged at ERROR with a
full traceback - including every `NotFoundError`, `AuthorizationError` and
`AlreadyExistsError`, which are ordinary 4xx outcomes. On a platform whose value
is mostly in what it refuses, the refusals were the loudest lines in the log and
a real 500 was buried among them. `_managed_session` now rolls a domain refusal
back and re-raises it without a traceback, and keeps ERROR for the unexpected.
"""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from app.core import background
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.db.session import _managed_session

pytestmark = pytest.mark.anyio


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.info: dict[str, object] = {}

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _factory(session: _FakeSession):
    return lambda: session


async def test_a_domain_refusal_rolls_back_without_an_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession()
    with caplog.at_level(logging.ERROR, logger="app.db.session"), pytest.raises(NotFoundError):
        async with _managed_session(_factory(session)) as db:
            assert db is session
            raise NotFoundError(message="no such row")

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert caplog.records == []


async def test_an_unexpected_error_still_logs_at_error_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession()
    with caplog.at_level(logging.ERROR, logger="app.db.session"), pytest.raises(RuntimeError):
        async with _managed_session(_factory(session)) as _db:
            raise RuntimeError("something genuinely broke")

    session.rollback.assert_awaited_once()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


async def test_a_5xx_domain_error_still_logs_at_error_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A server-fault AppException (status >= 500) is not a refusal, so its
    # traceback must survive - the suppression is for 4xx outcomes only.
    session = _FakeSession()
    with (
        caplog.at_level(logging.ERROR, logger="app.db.session"),
        pytest.raises(ExternalServiceError),
    ):
        async with _managed_session(_factory(session)) as _db:
            raise ExternalServiceError(message="upstream is down")

    session.rollback.assert_awaited_once()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


class TestWhatARollbackUndoes:
    """`spawn_after_rollback` work runs exactly when the transaction did not commit."""

    @staticmethod
    def _released(session: _FakeSession) -> list[str]:
        released: list[str] = []

        async def release() -> None:
            released.append("released")

        background.spawn_after_rollback(session, release(), name="release a claim")  # ty: ignore[invalid-argument-type]
        return released

    async def test_a_commit_keeps_the_claim(self) -> None:
        session = _FakeSession()
        released = self._released(session)
        async with _managed_session(_factory(session)):
            pass
        await background.drain(timeout=5.0)

        assert released == []

    async def test_a_rollback_gives_it_back(self) -> None:
        session = _FakeSession()
        released = self._released(session)
        with pytest.raises(NotFoundError):
            async with _managed_session(_factory(session)):
                raise NotFoundError(message="no such row")
        await background.drain(timeout=5.0)

        assert released == ["released"]

    async def test_a_commit_that_fails_gives_it_back(self) -> None:
        session = _FakeSession()
        session.commit = AsyncMock(side_effect=RuntimeError("serialization failure"))
        released = self._released(session)
        with pytest.raises(RuntimeError):
            async with _managed_session(_factory(session)):
                pass
        await background.drain(timeout=5.0)

        assert released == ["released"]

    async def test_a_cancelled_request_gives_it_back(self) -> None:
        """Cancellation skips the `except`; the transaction did not commit either."""
        session = _FakeSession()
        released = self._released(session)
        with pytest.raises(asyncio.CancelledError):
            async with _managed_session(_factory(session)):
                raise asyncio.CancelledError
        await background.drain(timeout=5.0)

        assert released == ["released"]
