"""Tests for the organization's monthly spend and the refusal that reads it.

One module owns "what has this organization spent this month" so the number a
budget enforces cannot drift from the number a dashboard shows - and the
refusal made before a document upload is the same `BudgetExceeded` a stopped
run raises, for the same reason.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.services.spend import (
    assert_organization_within_budget,
    month_start,
    organization_monthly_spend,
)

pytestmark = pytest.mark.anyio


def _org(monthly_budget_usd: Decimal | None) -> MagicMock:
    return MagicMock(monthly_budget_usd=monthly_budget_usd)


class TestMonthlySpend:
    async def test_the_month_is_runs_plus_ingestion(self):
        """The cap is a cap on the bill, and ingestion is the half of the bill
        no run carries."""
        organization_id = uuid.uuid4()

        with (
            patch(
                "app.services.spend.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("10")),
            ) as runs,
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal("2.5")),
            ) as ingestion,
        ):
            total = await organization_monthly_spend(MagicMock(), organization_id)

        assert total == Decimal("12.5")
        for lookup in (runs, ingestion):
            assert lookup.call_args.kwargs["organization_id"] == organization_id
            assert lookup.call_args.kwargs["since"] == month_start()


class TestTheRefusal:
    @staticmethod
    def _repos(organization, spent: Decimal):
        return (
            patch(
                "app.services.spend.organization_repo.get_by_id",
                new=AsyncMock(return_value=organization),
            ),
            patch(
                "app.services.spend.agent_run_repo.sum_cost_since",
                new=AsyncMock(return_value=spent),
            ),
            patch(
                "app.services.spend.ingestion_spend_repo.sum_cost_since",
                new=AsyncMock(return_value=Decimal(0)),
            ),
        )

    async def test_a_spent_cap_refuses_with_both_numbers(self):
        """The refusal names the ceiling and what was spent against it, exactly
        as a stopped run would - one message wherever a budget binds."""
        org, runs, ingestion = self._repos(_org(Decimal("40")), Decimal("40"))
        with org, runs, ingestion, pytest.raises(BudgetExceeded) as exc:
            await assert_organization_within_budget(MagicMock(), uuid.uuid4())

        assert exc.value.scope is BudgetScope.ORGANIZATION
        assert (exc.value.limit_usd, exc.value.spent_usd) == (Decimal("40"), Decimal("40"))

    async def test_an_organization_under_its_cap_passes(self):
        org, runs, ingestion = self._repos(_org(Decimal("40")), Decimal("39.99"))
        with org, runs, ingestion:
            await assert_organization_within_budget(MagicMock(), uuid.uuid4())

    async def test_no_cap_means_no_check_and_no_spend_query(self):
        """An organization that never opened the setting costs nothing here."""
        with (
            patch(
                "app.services.spend.organization_repo.get_by_id",
                new=AsyncMock(return_value=_org(None)),
            ),
            patch("app.services.spend.agent_run_repo.sum_cost_since") as runs,
        ):
            await assert_organization_within_budget(MagicMock(), uuid.uuid4())

        runs.assert_not_called()

    async def test_an_organization_that_is_gone_is_nothing_to_refuse(self):
        """A worker can hold a document whose tenant was deleted while it sat
        in the queue; that is a row nobody is billed for, not a crash."""
        with (
            patch(
                "app.services.spend.organization_repo.get_by_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.spend.agent_run_repo.sum_cost_since") as runs,
        ):
            await assert_organization_within_budget(MagicMock(), uuid.uuid4())

        runs.assert_not_called()
