"""The order a run's calls were made in, as `list_tool_calls_for_run` returns it.

A run's transcript is the recording an eval answers from and the trajectory it
is scored on, so the order matters wherever identical calls repeat. A turn
writes every call with one `started_at`, so time alone cannot say it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import conversation_repo

pytestmark = pytest.mark.anyio

START = datetime(2026, 10, 1, tzinfo=UTC)


def _row(call_id: str, at: datetime, turn: MagicMock) -> tuple[MagicMock, MagicMock]:
    return MagicMock(tool_call_id=call_id, started_at=at), turn


async def _ordered(rows: list[tuple[Any, Any]]) -> list[str]:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    listed = await conversation_repo.list_tool_calls_for_run(
        db, run_id=uuid.uuid4(), organization_id=uuid.uuid4()
    )
    return [call.tool_call_id for call, _ in listed]


async def test_calls_written_at_one_instant_keep_the_order_the_turn_recorded():
    turn = MagicMock(
        id=uuid.uuid4(),
        parts=[
            {"type": "text"},
            {"type": "tool", "tool_call_id": "zz"},
            {"type": "tool", "tool_call_id": "aa"},
        ],
    )

    assert await _ordered([_row("aa", START, turn), _row("zz", START, turn)]) == ["zz", "aa"]


async def test_without_parts_a_tie_falls_back_to_the_call_id_and_time_still_leads():
    older = MagicMock(id=uuid.uuid4(), parts=None)
    turn = MagicMock(id=uuid.uuid4(), parts=[{"type": "tool", "tool_call_id": "other"}])
    later = START + timedelta(seconds=1)

    assert await _ordered(
        [_row("m", START, older), _row("b", later, turn), _row("a", later, turn)]
    ) == ["m", "a", "b"]


async def test_two_turns_at_one_instant_stay_in_turn_order():
    first = MagicMock(id=uuid.uuid4(), parts=None)
    second = MagicMock(id=uuid.uuid4(), parts=None)

    assert await _ordered([_row("z", START, first), _row("a", START, second)]) == ["z", "a"]
