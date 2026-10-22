"""How handlers are bound and how a failure is written down (#2219)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.worker.errors import _MESSAGE_LIMIT, describe
from app.worker.handlers import _each_tick
from app.worker.jobs import Tick
from app.worker.registry import Handler, by_kind
from tests import worker_handlers

pytestmark = pytest.mark.anyio


def test_two_handlers_for_one_kind_are_refused_rather_than_the_second_winning() -> None:
    ok = worker_handlers.tasks()["ok"]
    with pytest.raises(ValueError, match="two handlers for the job kind 'test-ok'"):
        by_kind([Handler(ok, worker_handlers.succeed), Handler(ok, worker_handlers.fail)])


def _raise_long() -> None:
    raise RuntimeError("x" * (_MESSAGE_LIMIT + 50))


def test_a_long_message_is_cut_and_says_so() -> None:
    with pytest.raises(RuntimeError) as caught:
        _raise_long()

    described = describe(caught.value)

    assert described.splitlines()[0] == f"RuntimeError: {'x' * _MESSAGE_LIMIT}..."
    assert "in _raise_long" in described


async def test_a_sweep_runs_on_each_tick_whatever_occurrence_it_is() -> None:
    sweep = AsyncMock(return_value=3)

    assert await _each_tick(sweep)(Tick(scheduled_for=datetime.now(UTC))) == 3
    sweep.assert_awaited_once_with()
