"""Tests for the background handler that fires a trigger out of a request.

The caller - a webhook that has answered 202, or a "run now" that has - is gone by
the time this runs, so its one contract beyond firing is that an unexpected failure
is logged, never raised into the event loop as an unhandled task exception.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.background.trigger_fire import fire_trigger

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _fake_db_context():
    yield MagicMock()


async def test_it_fires_the_trigger_with_the_delivered_context():
    trigger_id = uuid.uuid4()
    service = MagicMock(fire=AsyncMock())
    with (
        patch("app.worker.background.trigger_fire.get_db_context", _fake_db_context),
        patch("app.worker.background.trigger_fire.AgentTriggerService", return_value=service),
    ):
        await fire_trigger(trigger_id, event_context="ISSUE #7 opened")
    service.fire.assert_awaited_once_with(trigger_id, event_context="ISSUE #7 opened")


async def test_a_manual_fire_arrives_with_no_event_context():
    """A manual fire sends the trigger's own prompt - there is no delivery to append."""
    trigger_id = uuid.uuid4()
    service = MagicMock(fire=AsyncMock())
    with (
        patch("app.worker.background.trigger_fire.get_db_context", _fake_db_context),
        patch("app.worker.background.trigger_fire.AgentTriggerService", return_value=service),
    ):
        await fire_trigger(trigger_id)
    service.fire.assert_awaited_once_with(trigger_id, event_context=None)


async def test_an_unexpected_failure_is_logged_and_swallowed():
    service = MagicMock(fire=AsyncMock(side_effect=RuntimeError("boom")))
    with (
        patch("app.worker.background.trigger_fire.get_db_context", _fake_db_context),
        patch("app.worker.background.trigger_fire.AgentTriggerService", return_value=service),
    ):
        await fire_trigger(uuid.uuid4(), event_context="context")  # must not raise
