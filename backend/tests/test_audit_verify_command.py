"""The `audit-verify` command reads the trail's evidence and fails loudly.

What matters here: naming one organization verifies only its chain and no name
verifies every chain, an intact trail exits zero, and any broken chain exits
non-zero naming the entry it broke on - so a scheduled run cannot pass over a
trail that has been altered.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from app.commands import audit_verify as cmd
from app.commands.audit_verify import _run, audit_verify
from app.services.audit import ChainBreak, ChainVerification

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _db_context(db: object) -> AsyncIterator[object]:
    yield db


def _run_returning(results: list[ChainVerification]) -> Callable[[Coroutine[Any, Any, Any]], Any]:
    """Stand in for `asyncio.run`: close the coroutine the command built (so it is
    not left un-awaited) and hand back the results the command would have gotten."""

    def fake(coro: Coroutine[Any, Any, Any]) -> list[ChainVerification]:
        coro.close()
        return results

    return fake


async def test_naming_an_organization_verifies_only_its_chain() -> None:
    org = uuid.uuid4()
    service = MagicMock()
    service.verify_chain = AsyncMock(return_value=ChainVerification(org, 3, None))
    service.verify_all_chains = AsyncMock()

    with (
        patch.object(cmd, "get_db_context", lambda: _db_context(MagicMock())),
        patch.object(cmd, "AuditService", return_value=service),
    ):
        results = await _run(org)

    assert results == [ChainVerification(org, 3, None)]
    service.verify_chain.assert_awaited_once_with(org)
    service.verify_all_chains.assert_not_awaited()


async def test_no_organization_verifies_every_chain() -> None:
    every = [ChainVerification(None, 1, None)]
    service = MagicMock()
    service.verify_all_chains = AsyncMock(return_value=every)

    with (
        patch.object(cmd, "get_db_context", lambda: _db_context(MagicMock())),
        patch.object(cmd, "AuditService", return_value=service),
    ):
        results = await _run(None)

    assert results == every
    service.verify_all_chains.assert_awaited_once_with()


def test_an_intact_trail_is_reported_and_exits_zero() -> None:
    results = [
        ChainVerification(None, 2, None),
        ChainVerification(uuid.uuid4(), 5, None),
    ]
    with patch.object(cmd.asyncio, "run", side_effect=_run_returning(results)):
        outcome = CliRunner().invoke(audit_verify, [])

    assert outcome.exit_code == 0
    assert "deployment: 2 entries verified" in outcome.output
    assert "5 entries verified" in outcome.output
    assert "intact" in outcome.output


def test_a_broken_chain_is_named_and_exits_non_zero() -> None:
    org = uuid.uuid4()
    entry_id = uuid.uuid4()
    results = [
        ChainVerification(
            org,
            3,
            ChainBreak(
                seq=3, entry_id=entry_id, reason="entry_hash does not match the entry's contents"
            ),
        )
    ]
    with patch.object(cmd.asyncio, "run", side_effect=_run_returning(results)):
        outcome = CliRunner().invoke(audit_verify, [])

    assert outcome.exit_code == 1
    assert "broke at seq 3" in outcome.output
    assert str(entry_id) in outcome.output
    assert "failed verification" in outcome.output
