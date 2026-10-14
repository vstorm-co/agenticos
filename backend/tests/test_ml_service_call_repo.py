"""The ML usage log's repository - the predicates, read back off the statements.

A dropped `organization_id` here is one tenant reading another's usage, and a
missing `service` filter is a report that answers the wrong question quietly. So
these read the compiled parameters rather than trusting the call signature.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.ml_service_call import MLServiceCall
from app.repositories import ml_service_call_repo
from app.repositories.ml_service_call import CallFilters

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.added: list[MLServiceCall] = []

    async def execute(self, statement: Any) -> object:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: MLServiceCall) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: MLServiceCall) -> None:
        pass


def _params(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


async def test_a_record_carries_everything_the_report_reads() -> None:
    session = _RecordingSession()

    row = await ml_service_call_repo.record(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        requested_by_user_id=None,
        service="ocr",
        status="succeeded",
        input_bytes=2048,
        units=4,
        unit="pages",
        duration_ms=1200,
    )

    assert session.added == [row]
    assert (row.organization_id, row.service, row.units, row.unit) == (_ORG, "ocr", 4, "pages")
    assert row.duration_ms == 1200


async def test_a_failure_record_keeps_the_stage_and_the_sentence() -> None:
    session = _RecordingSession()

    row = await ml_service_call_repo.record(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        requested_by_user_id=None,
        service="ocr",
        status="failed",
        input_bytes=0,
        units=0,
        unit="",
        duration_ms=3,
        failure_stage="engine",
        failure_reason="the engine returned nothing",
    )

    assert (row.failure_stage, row.failure_reason) == ("engine", "the engine returned nothing")


async def test_a_lookup_names_the_organization_as_well_as_the_id() -> None:
    call_id = uuid.uuid4()
    session = _RecordingSession(MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    found = await ml_service_call_repo.get(
        session,  # ty: ignore[invalid-argument-type]
        call_id,
        organization_id=_ORG,
    )

    assert found is None
    assert set(_params(session).values()) >= {call_id, _ORG}


async def test_the_listing_is_scoped_paged_and_newest_first() -> None:
    session = _RecordingSession(
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )

    await ml_service_call_repo.list_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        filters=CallFilters(),
        skip=20,
        limit=10,
    )

    statement = str(session.statements[-1])
    assert "ORDER BY ml_service_calls.created_at DESC" in statement
    assert _ORG in _params(session).values()


async def test_the_listing_can_be_narrowed_to_one_service() -> None:
    session = _RecordingSession(
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )

    await ml_service_call_repo.list_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        filters=CallFilters(service="pii_detection"),
        skip=0,
        limit=10,
    )

    assert "pii_detection" in _params(session).values()


async def test_the_count_is_scoped_to_the_organization() -> None:
    session = _RecordingSession(MagicMock(scalar_one=MagicMock(return_value=3)))

    total = await ml_service_call_repo.count_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        filters=CallFilters(),
    )

    assert total == 3
    assert _ORG in _params(session).values()


async def test_the_count_can_be_narrowed_to_one_service() -> None:
    session = _RecordingSession(MagicMock(scalar_one=MagicMock(return_value=1)))

    await ml_service_call_repo.count_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        filters=CallFilters(service="ocr"),
    )

    assert "ocr" in _params(session).values()


async def test_every_filter_narrows_and_the_organization_stays() -> None:
    """A filter is ANDed with the organization, never in its place: another
    tenant's agent id matches nothing rather than reaching their rows."""
    agent_id, bot_id = uuid.uuid4(), uuid.uuid4()
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 13, tzinfo=UTC)
    session = _RecordingSession(MagicMock(scalar_one=MagicMock(return_value=0)))

    await ml_service_call_repo.count_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        filters=CallFilters(
            service="speech_to_text",
            agent_id=agent_id,
            channel_bot_id=bot_id,
            surface="channel",
            since=since,
            until=until,
        ),
    )

    assert set(_params(session).values()) >= {
        _ORG,
        "speech_to_text",
        agent_id,
        bot_id,
        "channel",
        since,
        until,
    }
    statement = str(session.statements[-1])
    assert "ml_service_calls.created_at >=" in statement
    assert "ml_service_calls.created_at <" in statement


async def test_a_record_carries_a_transcriptions_attribution() -> None:
    session = _RecordingSession()
    agent_id, bot_id = uuid.uuid4(), uuid.uuid4()

    row = await ml_service_call_repo.record(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        requested_by_user_id=None,
        service="speech_to_text",
        status="succeeded",
        input_bytes=2048,
        units=3,
        unit="seconds",
        duration_ms=900,
        provider="openai",
        model="whisper-1",
        surface="channel",
        agent_id=agent_id,
        channel_bot_id=bot_id,
        audio_ms=2500,
    )

    assert (row.provider, row.model, row.surface) == ("openai", "whisper-1", "channel")
    assert (row.agent_id, row.channel_bot_id, row.audio_ms) == (agent_id, bot_id, 2500)


def _rows(*rows: tuple[object, ...]) -> MagicMock:
    return MagicMock(all=MagicMock(return_value=list(rows)), one=MagicMock(return_value=rows[0]))


async def test_the_summary_adds_up_and_orders_the_longest_first() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    bot = uuid.uuid4()
    session = _RecordingSession(
        _rows((None, 4, 4)),
        _rows((first, "Billing", 1, 1), (second, "Support", 9, 2)),
        _rows((bot, "Front desk", None, 3)),
        _rows(("chat", 10, 3), (None, None, 1)),
    )
    since = datetime(2026, 9, 13, tzinfo=UTC)

    summary = await ml_service_call_repo.summarise(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        service="speech_to_text",
        since=since,
    )

    assert (summary.seconds, summary.count, summary.count_unknown_length) == (0, 4, 4)
    assert [group.name for group in summary.by_agent] == ["Support", "Billing"]
    assert summary.by_channel[0].seconds == 0
    assert [group.surface for group in summary.by_surface] == ["chat", None]
    for statement in session.statements:
        params = statement.compile(dialect=postgresql.dialect()).params
        assert set(params.values()) >= {_ORG, "speech_to_text", "succeeded", since}
        # The rows' own rounded-up seconds, so the summary is the sum of the
        # listing rather than a second rounding of the milliseconds.
        assert "sum(ml_service_calls.units)" in str(statement)


def test_the_row_says_what_it_is() -> None:
    row = MLServiceCall(organization_id=_ORG, service="ocr", status="succeeded")

    assert repr(row) == "<MLServiceCall(service=ocr, status=succeeded)>"
