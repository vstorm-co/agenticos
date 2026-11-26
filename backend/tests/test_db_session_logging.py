"""A domain refusal is not an application error in the log (#19).

Every exception through the session dependency used to be logged at ERROR with a
full traceback - including every `NotFoundError`, `AuthorizationError` and
`AlreadyExistsError`, which are ordinary 4xx outcomes. On a platform whose value
is mostly in what it refuses, the refusals were the loudest lines in the log and
a real 500 was buried among them. `_managed_session` now rolls a domain refusal
back and re-raises it without a traceback, and keeps ERROR for the unexpected.
"""

import ast
import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import background
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.db import session as session_module
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


_ENGINE_FACTORIES = {
    "create_async_engine",
    "create_engine",
    "engine_from_config",
    "async_engine_from_config",
}
# Five in app/db/session.py, one each in the ingestion and teardown tasks, and
# the migration environment. A new engine changes this number on purpose.
_ENGINE_SITES = 8


def _engine_calls() -> tuple[list[tuple[str, int, ast.Call]], list[str]]:
    """Every engine-building call under `app/` and the migration environment, and any
    factory imported under another name, which the name match would miss."""
    backend = Path(__file__).resolve().parent.parent
    files = [*sorted((backend / "app").rglob("*.py")), backend / "alembic" / "env.py"]
    found: list[tuple[str, int, ast.Call]] = []
    aliased: list[str] = []
    for path in files:
        relative = path.relative_to(backend).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom | ast.Import):
                aliased += [
                    f"{relative}:{node.lineno}"
                    for alias in node.names
                    if alias.asname and alias.name.rpartition(".")[2] in _ENGINE_FACTORIES
                ]
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _ENGINE_FACTORIES:
                found.append((relative, node.lineno, node))
    return found, aliased


@pytest.mark.security
def test_every_engine_hides_statement_parameters() -> None:
    """A failed statement's values can be personal data and must not reach a log."""
    calls, aliased = _engine_calls()
    assert aliased == [], "an engine factory imported under another name"
    sites = [f"{path}:{line}" for path, line, _ in calls]
    assert len(calls) == _ENGINE_SITES, sites
    unhidden = [
        f"{path}:{line}"
        for path, line, call in calls
        if not any(
            kw.arg == "hide_parameters"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in call.keywords
        )
    ]
    assert unhidden == []


@pytest.mark.security
@pytest.mark.parametrize(
    "engine",
    [session_module.engine, session_module.vector_engine, session_module.agent_vector_engine],
)
def test_the_process_engines_hide_statement_parameters(engine: AsyncEngine) -> None:
    assert engine.sync_engine.hide_parameters is True
