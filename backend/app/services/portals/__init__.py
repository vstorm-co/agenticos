"""Portal adapters - how the platform registers a trigger's webhook at its provider.

External callers use `get_adapter` and the base types; the concrete adapters are
package-internal, resolved by key through the registry.
"""

from app.services.portals.base import (
    NOWHERE,
    PolledEvent,
    PolledEvents,
    PortalAdapter,
    PortalTarget,
    RegisteredWebhook,
)
from app.services.portals.exceptions import (
    PortalError,
    PortalUnreachable,
    WebhookRegistrationForbidden,
    WebhookRegistrationUnavailable,
)
from app.services.portals.microsoft_files import place_key as files_place
from app.services.portals.outlook import place_key as outlook_place
from app.services.portals.registry import get_adapter

__all__ = [
    "NOWHERE",
    "PolledEvent",
    "PolledEvents",
    "PortalAdapter",
    "PortalError",
    "PortalTarget",
    "PortalUnreachable",
    "RegisteredWebhook",
    "WebhookRegistrationForbidden",
    "WebhookRegistrationUnavailable",
    "files_place",
    "get_adapter",
    "outlook_place",
]
