"""The adapter a portal registers its webhook through, mirroring the channel adapters.

A portal that delivers by `auto_webhook` has an adapter here that speaks its
provider's API: it lists the targets a preset can point at (which repository),
registers the webhook with a platform-minted secret, and deregisters it on
delete. The base methods raise `WebhookRegistrationUnavailable`, so a portal is
*correct as manual* the day it is added and auto-registration lands one adapter
at a time - the same shape `app/services/channels/base.py` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.portals.exceptions import WebhookRegistrationUnavailable


@dataclass(frozen=True)
class PortalTarget:
    """One place a preset can point at - a repository, a channel."""

    id: str
    label: str


@dataclass(frozen=True)
class PolledEvent:
    """One thing that happened, in the shape the delivery layer already matches.

    `payload` is what `trigger_events.event_matches` and `render_context` read, so
    a polled event and a posted one are indistinguishable by the time a trigger is
    chosen - which is the point: the source decides how an event *arrives*, never
    what happens next.

    `delivery_id` is the provider's own id for it, the key the idempotency claim
    dedups on. A poll that overlaps its predecessor - a retry, a cursor that did
    not advance because the fire failed - then fires nothing twice.
    """

    delivery_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PolledEvents:
    """What one poll found, and where to resume."""

    events: tuple[PolledEvent, ...]
    cursor: dict[str, Any]


@dataclass(frozen=True)
class RegisteredWebhook:
    """The provider-side hook an adapter created, kept so a delete can remove it."""

    provider_webhook_id: str


class PortalAdapter:
    """How the platform registers and removes a portal's webhook at its provider.

    Not an `abc.ABC`: the defaults raise a readable failure rather than being
    abstract, so a manual portal needs no adapter at all and a half-built one
    degrades to manual rather than crashing. Concrete adapters override only the
    methods their provider supports.
    """

    portal_key: str = ""

    async def list_preset_targets(self, *, access_token: str) -> list[PortalTarget]:
        """The targets the connected account can point a preset at.

        Empty for a portal whose presets need no target (a mailbox-wide email
        trigger). A provider the account cannot enumerate returns empty and the
        UI falls back to a free-text target.
        """
        return []

    async def register_webhook(
        self, *, access_token: str, target: str | None, webhook_url: str, secret: str
    ) -> RegisteredWebhook:
        """Register `webhook_url` at the provider, signed with `secret`.

        Raises:
            WebhookRegistrationUnavailable: The default - a portal with no
                auto-registration. Concrete adapters override this.
            WebhookRegistrationForbidden: The account lacks the permission.
        """
        raise WebhookRegistrationUnavailable(
            details={"portal_key": self.portal_key},
        )

    async def delete_webhook(
        self, *, access_token: str, target: str | None, provider_webhook_id: str
    ) -> None:
        """Remove a previously registered webhook. Best-effort; default is a no-op."""
        return

    async def poll(self, *, access_token: str, cursor: dict[str, Any] | None) -> PolledEvents:
        """What has happened at the provider since `cursor`, and the new cursor.

        For a portal whose provider pushes nothing: the heartbeat asks, once a
        minute, and the answer feeds the same match-then-fire path a webhook
        delivery does - so a polled source is a delivery mechanism, not a second
        kind of trigger.

        **The cursor is the adapter's own shape** and nothing outside reads inside
        it: Gmail's is a `historyId`, another provider's might be a timestamp or an
        etag. It is returned rather than written here, so the caller advances it in
        the same transaction that records the fires - a cursor advanced before the
        work is a batch of messages nobody ever sees.

        **A first poll returns no events.** With no cursor there is no "since", and
        the alternative is firing an agent once per message already in the mailbox
        the moment somebody connects it. So the first call establishes the position
        and answers empty.

        Raises:
            PortalUnreachable: The provider could not be asked. The caller leaves
                the cursor alone and tries again next tick.
        """
        raise WebhookRegistrationUnavailable(details={"portal_key": self.portal_key})
