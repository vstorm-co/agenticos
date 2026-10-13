"""The ML usage log's repository - the predicates, read back off the statements.

A dropped `organization_id` here is one tenant reading another's usage, and a
missing `service` filter is a report that answers the wrong question quietly. So
these read the compiled parameters rather than trusting the call signature.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.ml_service_call import MLServiceCall
from app.repositories import ml_service_call_repo

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
        service=None,
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
        service="pii_detection",
        skip=0,
        limit=10,
    )

    assert "pii_detection" in _params(session).values()


async def test_the_count_is_scoped_to_the_organization() -> None:
    session = _RecordingSession(MagicMock(scalar_one=MagicMock(return_value=3)))

    total = await ml_service_call_repo.count_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        service=None,
    )

    assert total == 3
    assert _ORG in _params(session).values()


async def test_the_count_can_be_narrowed_to_one_service() -> None:
    session = _RecordingSession(MagicMock(scalar_one=MagicMock(return_value=1)))

    await ml_service_call_repo.count_for(
        session,  # ty: ignore[invalid-argument-type]
        organization_id=_ORG,
        service="ocr",
    )

    assert "ocr" in _params(session).values()


def test_the_row_says_what_it_is() -> None:
    row = MLServiceCall(organization_id=_ORG, service="ocr", status="succeeded")

    assert repr(row) == "<MLServiceCall(service=ocr, status=succeeded)>"
