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

from app.services.portals.exceptions import WebhookRegistrationUnavailable


@dataclass(frozen=True)
class PortalTarget:
    """One place a preset can point at - a repository, a channel."""

    id: str
    label: str


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
