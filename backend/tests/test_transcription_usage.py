"""The one writer of a transcription's usage row (#1797).

What it decides: the unit and the rounding, what a failure keeps, and that a row
the database refuses stays inside its savepoint - logged, never raised, never a
commit or a rollback of the caller's transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppException, ExternalServiceError
from app.services import transcription_usage
from app.services.transcription_usage import TranscriptionCall

pytestmark = pytest.mark.anyio

_REPO = "app.services.transcription_usage.ml_service_call_repo.record"
_ORG = uuid.uuid4()
_CALL = TranscriptionCall(
    organization_id=_ORG,
    surface="channel",
    provider="groq",
    model="whisper-large-v3-turbo",
    requested_by_user_id=uuid.uuid4(),
    agent_id=uuid.uuid4(),
    channel_bot_id=uuid.uuid4(),
)


def _db() -> MagicMock:
    """A session double: `begin_nested()` is an async context manager, as a
    real savepoint is, and the transaction verbs are there to be asserted on."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def recorded() -> Any:
    with patch(_REPO, new=AsyncMock()) as record:
        yield record


async def test_a_success_is_counted_in_seconds_rounded_up_with_its_attribution(
    recorded: Any,
) -> None:
    db = _db()
    await transcription_usage.record(
        db, _CALL, input_bytes=1024, audio_seconds=61.2, duration_ms=800
    )

    written = recorded.await_args.kwargs
    assert written["service"] == "speech_to_text"
    assert written["status"] == "succeeded"
    assert (written["units"], written["unit"], written["audio_ms"]) == (62, "seconds", 61_200)
    assert (written["failure_stage"], written["failure_reason"]) == (None, None)
    assert written["organization_id"] == _ORG
    assert written["requested_by_user_id"] == _CALL.requested_by_user_id
    assert (written["agent_id"], written["channel_bot_id"]) == (
        _CALL.agent_id,
        _CALL.channel_bot_id,
    )
    assert (written["provider"], written["model"], written["surface"]) == (
        "groq",
        "whisper-large-v3-turbo",
        "channel",
    )
    db.begin_nested.assert_called_once()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


async def test_a_success_with_no_length_is_zero_seconds_and_a_null_length(recorded: Any) -> None:
    await transcription_usage.record(
        _db(), _CALL, input_bytes=1024, audio_seconds=None, duration_ms=800
    )

    written = recorded.await_args.kwargs
    assert (written["units"], written["unit"], written["audio_ms"]) == (0, "seconds", None)


@pytest.mark.parametrize("length", [float("inf"), float("nan")])
async def test_a_length_that_is_not_finite_is_recorded_as_unmeasured(
    recorded: Any, length: float
) -> None:
    """A JSON `1e999` parses to `inf`, and rounding it raised before the
    savepoint could catch anything - a 500 for a transcript that worked."""
    await transcription_usage.record(
        _db(), _CALL, input_bytes=1024, audio_seconds=length, duration_ms=800
    )

    written = recorded.await_args.kwargs
    assert (written["status"], written["units"], written["audio_ms"]) == ("succeeded", 0, None)


async def test_a_failure_counts_nothing_but_keeps_the_length_and_the_stage(recorded: Any) -> None:
    failure = ExternalServiceError(
        message="The transcription provider did not answer in time.",
        details={"reason": "timeout", "stage": "engine"},
    )
    await transcription_usage.record(
        _db(), _CALL, input_bytes=1024, audio_seconds=3.0, duration_ms=60_000, failure=failure
    )

    written = recorded.await_args.kwargs
    assert written["status"] == "failed"
    assert (written["units"], written["unit"], written["audio_ms"]) == (0, "", 3000)
    assert written["failure_stage"] == "engine"
    assert written["failure_reason"] == failure.message


def test_a_refusal_naming_no_stage_was_a_refusal_of_the_input() -> None:
    assert transcription_usage.failure_of(AppException(message="nope")) == ("input", "nope")


async def test_a_row_the_database_refuses_is_logged_and_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An agent deleted mid-turn breaks the foreign key; the savepoint takes the
    insert back, and the caller keeps its transcript and its transaction."""
    db = _db()
    refused = IntegrityError("INSERT", {}, Exception("fk"))
    with (
        patch(_REPO, new=AsyncMock(side_effect=refused)),
        caplog.at_level(logging.WARNING, logger="app.services.transcription_usage"),
    ):
        row = await transcription_usage.record(
            db, _CALL, input_bytes=1, audio_seconds=None, duration_ms=1
        )

    assert row is None
    assert "Could not record a channel transcription" in caplog.text
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()
