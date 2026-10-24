"""Rewriting the waiting proposal: a second read when the first one moved meanwhile.

A decision or another run can change the proposal between reading it and the
conditional rewrite, so the rewrite reads the waiting proposal once more before
leaving the caller to make a new one - two runs on one target still leave one
waiting.
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.repositories import context_proposal_repo, skill_proposal_repo

pytestmark = pytest.mark.anyio


class _Session:
    """Answers each statement with the next row given, `None` for no row."""

    def __init__(self, *rows: Any) -> None:
        self.rows = list(rows)
        self.statements = 0

    async def execute(self, _statement: Any) -> Any:
        self.statements += 1
        result = MagicMock()
        result.scalars.return_value.first.return_value = self.rows.pop(0)
        return result


def _row() -> MagicMock:
    return MagicMock(id=uuid.uuid4(), organization_id=uuid.uuid4(), revision=1)


async def _context(session: _Session) -> Any:
    return await context_proposal_repo.replace_pending(
        session, organization_id=uuid.uuid4(), context_id=uuid.uuid4(), values={"content": "x"}
    )


async def _skill(session: _Session) -> Any:
    return await skill_proposal_repo.replace_pending(
        session,
        organization_id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        name="refunds",
        agent_id=uuid.uuid4(),
        description="d",
        content="c",
        resources={},
        conversation_id=None,
        base_version=1,
    )


@pytest.mark.parametrize("replace", [_context, _skill])
async def test_a_proposal_that_moved_meanwhile_is_read_again_and_rewritten(replace):
    first, second = _row(), _row()

    session = _Session(first, None, second, second)

    assert await replace(session) is second
    assert session.statements == 4
    # However often it moves, the one waiting is rewritten rather than joined by another.
    third = _row()
    assert await replace(_Session(_row(), None, _row(), None, third, third)) is third


@pytest.mark.parametrize("replace", [_context, _skill])
async def test_nothing_left_waiting_leaves_the_caller_to_propose_anew(replace):
    assert await replace(_Session(None)) is None
    # Decided while it was being rewritten: the caller makes a proposal of its own.
    assert await replace(_Session(_row(), None, None)) is None
