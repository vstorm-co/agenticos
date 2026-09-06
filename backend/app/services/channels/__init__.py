"""Channel adapter registry."""

from typing import TYPE_CHECKING

from app.services.channels.webhooks import (
    INBOUND_PATHS,
    SECRET_MINTED_BY_US,
    inbound_webhook_url,
)

if TYPE_CHECKING:
    from app.services.channels.base import ChannelAdapter

__all__ = [
    "INBOUND_PATHS",
    "SECRET_MINTED_BY_US",
    "get_adapter",
    "inbound_webhook_url",
    "register_adapter",
]

_adapters: dict[str, "ChannelAdapter"] = {}


def register_adapter(adapter: "ChannelAdapter") -> None:
    """Register a channel adapter by its platform name."""
    _adapters[adapter.platform] = adapter


def get_adapter(platform: str) -> "ChannelAdapter":
    """Retrieve a registered adapter by platform name.

    Raises:
        KeyError: If no adapter is registered for the given platform.
    """
    if platform not in _adapters:
        raise KeyError(f"No channel adapter registered for platform '{platform}'")
    return _adapters[platform]
