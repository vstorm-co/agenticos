"""Portal adapters - how the platform registers a trigger's webhook at its provider.

External callers use `get_adapter` and the base types; the concrete adapters are
package-internal, resolved by key through the registry.
"""

from __future__ import annotations

from app.services.portals.base import PortalAdapter, PortalTarget, RegisteredWebhook
from app.services.portals.exceptions import (
    PortalError,
    WebhookRegistrationForbidden,
    WebhookRegistrationUnavailable,
)
from app.services.portals.registry import get_adapter

__all__ = [
    "PortalAdapter",
    "PortalError",
    "PortalTarget",
    "RegisteredWebhook",
    "WebhookRegistrationForbidden",
    "WebhookRegistrationUnavailable",
    "get_adapter",
]
