"""`app.services.workflow_execution.events`: append, and the cursor codec."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.services.workflow_execution import events

pytestmark = pytest.mark.anyio

EVENTS_PATH = "app.services.workflow_execution.events"


class TestAppend:
    async def test_delegates_to_the_repository_with_the_run_and_kind(self):
        run = object()
        db = object()
        with patch(
            f"{EVENTS_PATH}.workflow_run_repo.append_event", new=AsyncMock()
        ) as append_event:
            await events.append(db, run=run, kind="node_completed", node_run_id=None)
        append_event.assert_awaited_once_with(
            db, run=run, kind="node_completed", node_run_id=None, payload={}
        )

    async def test_a_payload_is_passed_through_unchanged(self):
        run = object()
        db = object()
        payload = {"attempt_no": 2}
        with patch(
            f"{EVENTS_PATH}.workflow_run_repo.append_event", new=AsyncMock()
        ) as append_event:
            await events.append(db, run=run, kind="node_retrying", payload=payload)
        append_event.assert_awaited_once_with(
            db, run=run, kind="node_retrying", node_run_id=None, payload=payload
        )


class TestCursorCodec:
    def test_a_seq_round_trips_through_the_cursor(self):
        assert events.decode_cursor(events.encode_cursor(42)) == 42

    def test_zero_is_a_legitimate_cursor(self):
        assert events.decode_cursor(events.encode_cursor(0)) == 0

    def test_a_non_numeric_cursor_is_refused(self):
        with pytest.raises(BadRequestError):
            events.decode_cursor("not-a-number")
