"""A curated catalog of trigger *portals* - a service, and the events it can fire an agent on.

An event trigger used to be a raw choice of source plus a signing secret the user
pasted into a provider's webhook settings. A portal is the friendlier shape over
the same machinery: a named service (GitHub, Gmail, …) with a handful of
ready-made **presets** - "fire when a new issue is opened" - so a non-technical
user picks a card instead of composing an `event_config`.

Each portal names the `event_source` its presets fire through, so the delivery
layer (`app/services/trigger_events.py`) is unchanged - a portal is a *setup*
concept, not a new kind of trigger. `delivery` records how the webhook gets
registered: `auto_webhook` means the platform registers it at the provider using
a connected account (the non-technical path); `manual` means the user still wires
a relay and pastes the URL (the advanced fallback, and the only option for a
provider with no webhook API); `polling` is reserved for providers that push
nothing and must be asked (Gmail).

Hand-maintained data, like `mcp_servers.json` beside it: adding a portal or a
preset is a JSON edit, never code, and `catalog.load` validates every field at
import so a malformed entry refuses to start the app rather than vanishing from
the picker. What *interprets* a portal - the adapter that registers its webhook -
stays in code (`app/services/portals/`); a portal whose `delivery` is
`auto_webhook` with no adapter behind it falls back to manual, so the two cannot
disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import TypeAdapter

from app.core import catalog


class DeliveryMode(StrEnum):
    """How a portal's webhook reaches the platform."""

    # The platform registers the webhook at the provider through a connected
    # account - the user never touches the provider's settings.
    AUTO_WEBHOOK = "auto_webhook"
    # The user wires a relay (or the provider's own UI) and pastes the URL. The
    # fallback when there is no account, no scope, or no webhook API.
    MANUAL = "manual"
    # The provider pushes nothing; a background job asks it on a schedule.
    POLLING = "polling"


@dataclass(frozen=True)
class PortalPreset:
    """One ready-made event a portal can fire on.

    `event_config` is a template for the portal's `event_source` - it is
    validated against that source's typed model at trigger-create time, the same
    normalization a hand-typed config goes through, so a preset with a bad key is
    a 422 there rather than a lie here. `target_required` marks a preset that
    cannot be registered until the user chooses a target (which repository), which
    the create flow resolves from the connected account.
    """

    key: str
    label: str
    description: str
    event_config: dict[str, Any] = field(default_factory=dict)
    target_required: bool = False


@dataclass(frozen=True)
class PortalEntry:
    """One connectable service and the events it fires an agent on."""

    key: str
    name: str
    description: str
    category: str
    # The `event_source` every preset here fires through - the delivery layer's
    # vocabulary (`app/db/models/agent_trigger.py:EventSource`).
    event_source: str
    delivery: DeliveryMode
    presets: tuple[PortalPreset, ...]
    # The brand mark to draw, as `BrandIcon` names them; empty falls back to a
    # monogram.
    icon: str = ""
    # OAuth scopes the connected account needs: `read_scopes` to see the events,
    # `webhook_admin_scopes` to register the webhook. Split so the escalation to
    # webhook-admin is explicit and requested only when auto-registration is used.
    read_scopes: tuple[str, ...] = ()
    webhook_admin_scopes: tuple[str, ...] = ()
    # The `mcp_servers.json` entry this portal shares a connection with, so one
    # connected account backs both triggers and the agent's MCP tools. None when
    # the portal has no MCP counterpart.
    mcp_catalog_key: str | None = None
    # What a preset's target names, when one is required - "repo", "channel". None
    # when presets never need a target (a mailbox-wide email trigger).
    target_kind: str | None = None


# Validated against the dataclasses at import, like every catalog here: a
# malformed portal stops the deployment instead of shipping a picker with a hole.
CATALOG: tuple[PortalEntry, ...] = catalog.load(
    "portals.json", TypeAdapter(tuple[PortalEntry, ...])
)

BY_KEY: dict[str, PortalEntry] = {entry.key: entry for entry in CATALOG}


def get_portal(key: str) -> PortalEntry | None:
    return BY_KEY.get(key)


def get_preset(portal_key: str, preset_key: str) -> tuple[PortalEntry, PortalPreset] | None:
    """The portal and preset a create request names, or None if either is unknown."""
    portal = BY_KEY.get(portal_key)
    if portal is None:
        return None
    for preset in portal.presets:
        if preset.key == preset_key:
            return portal, preset
    return None
