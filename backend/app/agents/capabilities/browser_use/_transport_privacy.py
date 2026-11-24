"""No protocol payload logging, including late replies and callbacks on other tasks.

The reviewed cdp-use 1.4.5 wheel logs parameters, results, events and exception
messages through these exact loggers. Dropping the whole record, before any
handler, also protects traceback/extra fields. This is installed for the complete
transport lifetime, never temporarily around a write: responses and callbacks
can outlive the writer and a second tab can be active concurrently.

Application-owned fixed failure codes remain available. Upstream payload debug
logging is deliberately unavailable for this browser transport.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from app.core.browser_fill import BrowserFillReason, BrowserFillRefused

CDP_USE_VERSION = "1.4.5"
WEBSOCKETS_VERSION = "17.4"
PAYLOAD_LOGGERS = ("websockets.client", "cdp_use.client", "cdp_use.cdp.registry")


class _DropProtocolRecord(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


_FILTER = _DropProtocolRecord()


class _DropProtocolNamespace(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(
            record.name == name or record.name.startswith(name + ".") for name in PAYLOAD_LOGGERS
        )


_NAMESPACE_FILTER = _DropProtocolNamespace()


def _handlers() -> set[logging.Handler]:
    # Children inherit handlers, not logger filters. Cover every configured sink
    # so a child created after startup cannot bypass privacy by changing its level.
    handlers = set(logging.getLogger().handlers)
    for item in tuple(logging.Logger.manager.loggerDict.values()):
        if isinstance(item, logging.Logger):
            handlers.update(item.handlers)
    return handlers


def protect_transport_logging() -> None:
    """Install before importing/starting the optional CDP library. Idempotent."""
    for name in PAYLOAD_LOGGERS:
        logger = logging.getLogger(name)
        logger.addFilter(_FILTER)
    for handler in _handlers():
        handler.addFilter(_NAMESPACE_FILTER)


def require_private_transport() -> None:
    """A package upgrade needs a new source review before it may transport secrets."""
    try:
        supported = (
            version("cdp-use") == CDP_USE_VERSION and version("websockets") == WEBSOCKETS_VERSION
        )
    except PackageNotFoundError:
        supported = False
    if (
        not supported
        or any(_FILTER not in logging.getLogger(name).filters for name in PAYLOAD_LOGGERS)
        or any(_NAMESPACE_FILTER not in handler.filters for handler in _handlers())
    ):
        raise BrowserFillRefused(BrowserFillReason.PROTECTION_UNAVAILABLE)
