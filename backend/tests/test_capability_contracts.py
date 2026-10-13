"""What the model is actually told about each tool - the two edges.

`capability_contracts.tool_contracts` is read by the Toolbox panel and by the
exposure form's channel-lookups checklist (#1473) alike, so both trust it to
degrade rather than break: a secret kind the documentation stub cannot fake is
left unstubbed rather than faked wrong, and a capability that raises while
building is logged and skipped rather than taking the whole catalog down with
it. Neither edge is exercised by the tests that only read a working capability's
contract, so they get their own file.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.secret_kinds import SecretKind, SecretRequirement
from app.services.capability_contracts import _documentation_secret, tool_contracts

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """`tool_contracts` caches for the process - a test faking the registry
    must not leave that fake behind for every test that runs after it.
    `monkeypatch` restores the original value on teardown either way."""
    monkeypatch.setattr("app.services.capability_contracts._CACHED", None)


class TestDocumentationSecret:
    """The stand-in credential `tool_contracts` builds a capability with."""

    def test_a_capability_needing_no_secret_gets_none(self):
        definition = SimpleNamespace(
            secret=None, needs_secret=lambda config: True, validate_config=lambda blob: blob
        )

        assert _documentation_secret(definition) is None

    def test_a_conditional_secret_the_default_config_does_not_need_gets_none(self):
        definition = SimpleNamespace(
            secret=SecretRequirement(kind=SecretKind.API_KEY, description="test"),
            needs_secret=lambda config: False,
            validate_config=lambda blob: blob,
        )

        assert _documentation_secret(definition) is None

    def test_a_non_api_key_secret_gets_no_stand_in(self):
        """Only `API_KEY` is faked - another kind is the wrong shape to stub,
        and should show up as a missing contract rather than a mistaken one."""
        definition = SimpleNamespace(
            secret=SecretRequirement(kind=SecretKind.AZURE_OPENAI, description="test"),
            needs_secret=lambda config: True,
            validate_config=lambda blob: blob,
        )

        assert _documentation_secret(definition) is None

    def test_an_unconditional_api_key_secret_gets_a_probe_value(self):
        definition = SimpleNamespace(
            secret=SecretRequirement(kind=SecretKind.API_KEY, description="test"),
            needs_secret=lambda config: True,
            validate_config=lambda blob: blob,
        )

        secret = _documentation_secret(definition)

        assert secret is not None
        assert secret.api_key.get_secret_value() == "documentation-probe"


class TestToolContracts:
    """The catalog-wide read, and what happens when one capability cannot build."""

    async def test_a_capability_that_raises_while_building_is_logged_and_skipped(self, caplog):
        """One broken capability must not take the whole catalog down with it -
        the Builder can still show every other one, with one fewer contract."""
        broken = SimpleNamespace(
            id="broken_for_this_test",
            builder=MagicMock(side_effect=RuntimeError("boom")),
            validate_config=lambda blob: blob,
            secret=None,
            needs_secret=lambda config: False,
        )

        with (
            patch("app.services.capability_contracts.all_capabilities", return_value=[broken]),
            caplog.at_level("ERROR"),
        ):
            contracts = await tool_contracts()

        assert contracts == {"broken_for_this_test": {}}
        assert "broken_for_this_test" in caplog.text

    async def test_a_capability_with_no_toolset_offers_no_contracts(self):
        """`get_toolset` answering `None` is not a failure - a capability may
        attach nothing without a config to work with, and the catalog should
        show it with an empty contract set rather than logging an error for it."""
        empty = SimpleNamespace(
            id="toolset_free_for_this_test",
            builder=MagicMock(return_value=SimpleNamespace(get_toolset=lambda: None)),
            validate_config=lambda blob: blob,
            secret=None,
            needs_secret=lambda config: False,
        )

        with patch("app.services.capability_contracts.all_capabilities", return_value=[empty]):
            contracts = await tool_contracts()

        assert contracts == {"toolset_free_for_this_test": {}}
