"""Tests for the background dispatcher that fires a matched event delivery.

The webhook route has already returned 202 by the time this runs, so its one
contract beyond firing is that an unexpected failure is logged, never raised into
the event loop as an unhandled task exception.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.background.trigger_event import process_trigger_event

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _fake_db_context():
    yield MagicMock()


async def test_it_fires_the_trigger_with_the_delivered_context():
    trigger_id = uuid.uuid4()
    service = MagicMock(fire=AsyncMock())
    with (
        patch("app.worker.background.trigger_event.get_db_context", _fake_db_context),
        patch("app.worker.background.trigger_event.AgentTriggerService", return_value=service),
    ):
        await process_trigger_event(trigger_id, "ISSUE #7 opened")
    service.fire.assert_awaited_once_with(trigger_id, event_context="ISSUE #7 opened")


async def test_an_unexpected_failure_is_logged_and_swallowed():
    service = MagicMock(fire=AsyncMock(side_effect=RuntimeError("boom")))
    with (
        patch("app.worker.background.trigger_event.get_db_context", _fake_db_context),
        patch("app.worker.background.trigger_event.AgentTriggerService", return_value=service),
    ):
        await process_trigger_event(uuid.uuid4(), "context")  # must not raise
