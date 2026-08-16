"""Tests for application settings validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestDefaultOrgBudget:
    def test_a_positive_default_is_accepted(self):
        expected = Decimal("100")
        settings = Settings(DEFAULT_ORG_MONTHLY_BUDGET_USD=expected)
        assert expected == settings.DEFAULT_ORG_MONTHLY_BUDGET_USD

    def test_none_disables_the_default(self):
        """`None` is the older opt-in posture, not a misconfiguration."""
        settings = Settings(DEFAULT_ORG_MONTHLY_BUDGET_USD=None)
        assert settings.DEFAULT_ORG_MONTHLY_BUDGET_USD is None

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
    def test_a_non_positive_default_is_refused(self, bad):
        """Zero or below would refuse every new org's first run - the same reason
        `ck_organization_budget_positive` forbids it on the row."""
        with pytest.raises(ValidationError):
            Settings(DEFAULT_ORG_MONTHLY_BUDGET_USD=bad)
