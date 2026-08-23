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


KEY = "vault-master-key-" + "x" * 32


class TestVaultMasterKeyValidation:
    """The vault key must be explicit anywhere real credentials live.

    An unset `VAULT_MASTER_KEY` falls back to `SECRET_KEY`, whose default is a
    string published in this repository. The old validator refused that default
    only in production, so a staging deployment - first-class here - booted with
    its whole vault sealed under a public key (#8).
    """

    @pytest.mark.parametrize("env", ["staging", "production"])
    def test_an_unset_key_is_refused_outside_local_and_development(self, env):
        # SECRET_KEY and API_KEY are valid so the one refusal left is the vault's -
        # production already refused their defaults, staging refused nothing (#8).
        with pytest.raises(ValidationError, match="VAULT_MASTER_KEY"):
            Settings(
                ENVIRONMENT=env,
                SECRET_KEY="s" * 64,
                API_KEY="a" * 64,
                VAULT_MASTER_KEY="",
                VAULT_MASTER_KEYS={},
            )

    @pytest.mark.parametrize("env", ["local", "development"])
    def test_a_fresh_checkout_still_boots(self, env):
        settings = Settings(ENVIRONMENT=env, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={})
        assert settings.VAULT_MASTER_KEY == ""

    def test_the_single_key_satisfies_staging(self):
        settings = Settings(ENVIRONMENT="staging", VAULT_MASTER_KEY=KEY, VAULT_MASTER_KEYS={})
        assert settings.VAULT_MASTER_KEY == KEY

    def test_the_versioned_map_satisfies_staging(self):
        settings = Settings(ENVIRONMENT="staging", VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={1: KEY})
        assert settings.VAULT_MASTER_KEYS == {1: KEY}

    def test_both_forms_at_once_are_refused(self):
        """Two sources for the current key make it ambiguous which seals new
        secrets - a rotation configured that way would be wrong half the time."""
        with pytest.raises(ValidationError, match="not both"):
            Settings(ENVIRONMENT="local", VAULT_MASTER_KEY=KEY, VAULT_MASTER_KEYS={1: KEY})

    def test_an_empty_key_in_the_map_is_refused(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            Settings(ENVIRONMENT="local", VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={1: ""})

    def test_a_non_positive_version_is_refused(self):
        """`key_version` columns default to 1 and `current_key_version` is the
        highest configured, so version 0 could never be anything but a mistake."""
        with pytest.raises(ValidationError, match="positive"):
            Settings(ENVIRONMENT="local", VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={0: KEY})
