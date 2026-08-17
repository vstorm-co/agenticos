"""Tests for the ingestion spend repository - the ledger runs cannot carry.

The predicate is the point, as with every repository here: a dropped
`organization_id` filter would let one tenant's ingestion exhaust another's
budget, and a dropped window would bill this month for every month there ever
was.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.ingestion_spend import IngestionSpend
from app.repositories import ingestion_spend_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, scalar_result: object = None) -> None:
        self._scalar_result = scalar_result
        self.statements: list[object] = []
        self.added: list[IngestionSpend] = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self._scalar_result

    def add(self, instance: IngestionSpend) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: IngestionSpend) -> None:
        pass


class TestRecording:
    async def test_a_window_is_written_with_everything_a_bill_needs(self):
        session = _RecordingSession()
        organization_id, document_id = uuid.uuid4(), uuid.uuid4()

        spend = await ingestion_spend_repo.record(
            session,
            organization_id=organization_id,
            rag_document_id=document_id,
            model="text-embedding-3-large",
            input_tokens=12_345,
            output_tokens=0,
            cost_usd=Decimal("0.13"),
            cost_is_partial=False,
        )

        assert session.added == [spend]
        assert (spend.organization_id, spend.rag_document_id) == (organization_id, document_id)
        assert (spend.model, spend.input_tokens, spend.output_tokens) == (
            "text-embedding-3-large",
            12_345,
            0,
        )
        assert (spend.cost_usd, spend.cost_is_partial) == (Decimal("0.13"), False)

    async def test_an_unpriced_window_is_flagged_not_silently_free(self):
        session = _RecordingSession()

        spend = await ingestion_spend_repo.record(
            session,
            organization_id=None,
            rag_document_id=None,
            model="mystery-embedder",
            input_tokens=1000,
            output_tokens=0,
            cost_usd=Decimal(0),
            cost_is_partial=True,
        )

        assert spend.cost_is_partial is True


class TestSumming:
    async def test_the_sum_filters_on_the_organization_and_the_window(self):
        organization_id = uuid.uuid4()
        since = datetime(2026, 7, 1, tzinfo=UTC)
        session = _RecordingSession(scalar_result=Decimal("1.75"))

        total = await ingestion_spend_repo.sum_cost_since(
            session, organization_id=organization_id, since=since
        )

        assert total == Decimal("1.75")
        params = session.statements[-1].compile(dialect=postgresql.dialect()).params
        assert set(params.values()) >= {organization_id, since}

    async def test_a_month_with_no_ingestion_sums_to_zero_not_none(self):
        session = _RecordingSession(scalar_result=None)

        total = await ingestion_spend_repo.sum_cost_since(
            session, organization_id=uuid.uuid4(), since=datetime(2026, 7, 1, tzinfo=UTC)
        )

        assert total == Decimal(0)

    async def test_a_closed_window_carries_both_of_its_edges(self):
        # The dashboard asks about a range, not about everything since a date:
        # a `sum_cost_since` here would bill July's card for August as well.
        organization_id = uuid.uuid4()
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        session = _RecordingSession(scalar_result=Decimal("0.42"))

        total = await ingestion_spend_repo.sum_cost_window(
            session, organization_id=organization_id, start=start, end=end
        )

        assert total == Decimal("0.42")
        params = session.statements[-1].compile(dialect=postgresql.dialect()).params
        assert set(params.values()) >= {organization_id, start, end}

    async def test_a_window_with_no_ingestion_sums_to_zero_not_none(self):
        session = _RecordingSession(scalar_result=None)

        total = await ingestion_spend_repo.sum_cost_window(
            session,
            organization_id=uuid.uuid4(),
            start=datetime(2026, 7, 1, tzinfo=UTC),
            end=datetime(2026, 8, 1, tzinfo=UTC),
        )

        assert total == Decimal(0)
