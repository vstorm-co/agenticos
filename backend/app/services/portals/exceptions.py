"""Portal-adapter failures, caught by the create flow to fall back to manual setup.

These are not surfaced to the caller as errors: a portal that cannot register a
webhook automatically is a portal the user wires by hand, so the create flow
turns either of these into the manual path (a returned URL and a reveal-once
secret) rather than a 4xx. They subclass `AppException` only so a stray one that
escapes the create flow is logged and mapped like any other domain error.
"""

from __future__ import annotations

from app.core.exceptions import AppException


class PortalError(AppException):
    """Base for portal-adapter failures."""

    message = "Portal operation failed"
    code = "PORTAL_ERROR"
    status_code = 502


class WebhookRegistrationUnavailable(PortalError):
    """The portal cannot register a webhook automatically at all.

    A manual-delivery portal, a provider with no webhook API, or an adapter that
    has not implemented registration yet. The create flow falls back to manual.
    """

    message = "This portal cannot register a webhook automatically"
    code = "PORTAL_WEBHOOK_UNAVAILABLE"


class WebhookRegistrationForbidden(PortalError):
    """The connected account lacks the permission to register the webhook.

    The OAuth grant is missing the webhook-admin scope, or the account cannot
    administer the chosen target. The create flow falls back to manual.
    """

    message = "The connected account may not register this webhook"
    code = "PORTAL_WEBHOOK_FORBIDDEN"
