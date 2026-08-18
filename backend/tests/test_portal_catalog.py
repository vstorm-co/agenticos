"""The trigger-portals catalog, and the promise each preset makes.

The load itself is proven by import - `catalog.load` validates the JSON against
the dataclasses at import time, so a malformed `portals.json` fails collection
here rather than a user's picker. What these add is the semantic check the
structural load cannot make: every preset's `event_config` must be a valid config
for its portal's `event_source`, so a preset with a typo'd key is caught in CI
rather than as a 422 the first time someone clicks the card.
"""

from __future__ import annotations

from app.db.models.agent_trigger import EventSource
from app.schemas.agent_trigger import _EVENT_CONFIG_MODELS
from app.services import mcp_catalog, portal_catalog
from app.services.portal_catalog import DeliveryMode


def test_the_catalog_loads_and_is_not_empty() -> None:
    assert portal_catalog.CATALOG
    assert portal_catalog.get_portal("github") is not None
    assert portal_catalog.get_portal("does-not-exist") is None


def test_every_preset_validates_against_its_sources_model() -> None:
    """The self-check: a preset template is normalized through the same per-source
    model a hand-typed config is (`_EVENT_CONFIG_MODELS`), so it cannot ship a key
    the source would refuse."""
    for portal in portal_catalog.CATALOG:
        model = _EVENT_CONFIG_MODELS[portal.event_source]
        for preset in portal.presets:
            # Raises pydantic.ValidationError if the template is not a valid config.
            model.model_validate(preset.event_config)


def test_every_portal_names_a_real_event_source() -> None:
    known = {source.value for source in EventSource}
    for portal in portal_catalog.CATALOG:
        assert portal.event_source in known, portal.key


def test_an_auto_webhook_portal_declares_the_scope_it_registers_with() -> None:
    """Auto-registration re-authorizes the connection for webhook-admin scopes; a
    portal that claims `auto_webhook` without naming them could never register."""
    for portal in portal_catalog.CATALOG:
        if portal.delivery is DeliveryMode.AUTO_WEBHOOK:
            assert portal.webhook_admin_scopes, portal.key
            assert portal.mcp_catalog_key, portal.key


def test_every_mcp_catalog_key_names_a_real_server() -> None:
    """A portal's `mcp_catalog_key` is the `mcp_servers.json` entry whose account
    backs both the trigger's webhook and the agent's tools, so the connect flow
    resolves it. Membership, not mere truthiness: a typo'd key would ship a portal
    whose connect flow points at a server that does not exist."""
    known = {entry.key for entry in mcp_catalog.CATALOG}
    for portal in portal_catalog.CATALOG:
        if portal.mcp_catalog_key is not None:
            assert portal.mcp_catalog_key in known, portal.key


def test_a_target_requiring_preset_lives_on_a_portal_that_has_a_target_kind() -> None:
    """A preset that needs a target is meaningless unless its portal says what a
    target *is* - the create flow reads `target_kind` to know what to ask for."""
    for portal in portal_catalog.CATALOG:
        if any(preset.target_required for preset in portal.presets):
            assert portal.target_kind, portal.key


def test_get_preset_finds_a_real_pair_and_misses_the_rest() -> None:
    found = portal_catalog.get_preset("github", "issue_opened")
    assert found is not None
    portal, preset = found
    assert portal.key == "github"
    assert preset.key == "issue_opened"
    assert portal_catalog.get_preset("github", "no-such-preset") is None
    assert portal_catalog.get_preset("no-such-portal", "issue_opened") is None
