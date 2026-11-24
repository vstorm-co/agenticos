"""The reviewed optional transport must not publish protocol records at any level."""

import asyncio
import builtins
import logging
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.capabilities.browser_use import _page as page_module
from app.agents.capabilities.browser_use import _transport_privacy as privacy
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from tests.test_browser_credentials import PASSWORD

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def transport_failure() -> None:
    raise RuntimeError(PASSWORD)


@pytest.fixture
def private_loggers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in privacy.PAYLOAD_LOGGERS:
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "filters", [])
    for handler in privacy._handlers():
        monkeypatch.setattr(handler, "filters", list(handler.filters))
    monkeypatch.setattr(
        privacy,
        "version",
        lambda package: {
            "cdp-use": privacy.CDP_USE_VERSION,
            "websockets": privacy.WEBSOCKETS_VERSION,
        }[package],
    )


async def test_payloads_are_dropped_before_handlers_including_late_and_other_task_records(
    private_loggers: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    privacy.protect_transport_logging()
    privacy.protect_transport_logging()
    privacy.require_private_transport()
    ready = asyncio.Event()

    async def delayed() -> None:
        await ready.wait()
        for name in privacy.PAYLOAD_LOGGERS:
            logger = logging.getLogger(name)
            assert logger.filters.count(privacy._FILTER) == 1
            for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
                logger.log(level, "protocol parameter %s", PASSWORD, extra={"payload": PASSWORD})
            try:
                transport_failure()
            except RuntimeError:
                logger.exception("upstream callback failed")

    task = asyncio.create_task(delayed())
    ready.set()
    await task
    for name in privacy.PAYLOAD_LOGGERS:
        child = logging.getLogger(name + ".later_redirect")
        child.setLevel(logging.DEBUG)
        child.error("late event %s", PASSWORD, extra={"raw_event": PASSWORD})
    assert caplog.records == []
    logging.getLogger("app.browser_credential_boundary").warning("browser_unavailable")
    assert caplog.messages == ["browser_unavailable"]


@pytest.mark.parametrize("missing", privacy.PAYLOAD_LOGGERS)
async def test_a_missing_payload_guard_refuses_before_any_secret_can_be_opened(
    private_loggers: None,
    missing: str,
) -> None:
    privacy.protect_transport_logging()
    logging.getLogger(missing).removeFilter(privacy._FILTER)
    with pytest.raises(BrowserFillRefused) as caught:
        privacy.require_private_transport()
    assert caught.value.reason == BrowserFillReason.PROTECTION_UNAVAILABLE


@pytest.mark.parametrize("installed", [None, "1.4.4", "1.4.6"])
async def test_unreviewed_or_missing_optional_library_refuses(
    private_loggers: None,
    monkeypatch: pytest.MonkeyPatch,
    installed: str | None,
) -> None:
    privacy.protect_transport_logging()

    def version(package: str) -> str:
        if installed is None:
            raise PackageNotFoundError(package)
        return installed

    monkeypatch.setattr(privacy, "version", version)
    with pytest.raises(BrowserFillRefused):
        privacy.require_private_transport()


async def test_unreviewed_websocket_library_refuses(
    private_loggers: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    privacy.protect_transport_logging()
    monkeypatch.setattr(
        privacy,
        "version",
        lambda package: privacy.CDP_USE_VERSION if package == "cdp-use" else "unreviewed",
    )
    with pytest.raises(BrowserFillRefused):
        privacy.require_private_transport()


async def test_a_new_unprotected_handler_requires_configuration_before_admission(
    private_loggers: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    privacy.protect_transport_logging()
    caplog.handler.removeFilter(privacy._NAMESPACE_FILTER)
    with pytest.raises(BrowserFillRefused):
        privacy.require_private_transport()


async def test_guards_exist_before_optional_import_and_the_first_connection(
    private_loggers: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    phases: list[str] = []
    original_import = builtins.__import__

    def record(phase: str) -> None:
        privacy.require_private_transport()
        phases.append(phase)
        for name in privacy.PAYLOAD_LOGGERS:
            logging.getLogger(name).error("initial protocol payload %s", PASSWORD)

    class Client:
        def __init__(self, socket: str) -> None:
            record("construct")

        async def start(self) -> None:
            record("connect")
            raise RuntimeError("synthetic startup stop")

    def import_library(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cdp_use":
            record("import")
            return SimpleNamespace(CDPClient=Client)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_library)
    monkeypatch.setattr(page_module, "_resolve", AsyncMock(return_value="127.0.0.1"))
    with pytest.raises(RuntimeError, match="synthetic startup stop"):
        async with page_module.open_page(
            cdp_url="ws://127.0.0.1:9222/devtools/browser/synthetic",
            start_url="https://example.test/login",
            policy=page_module.PagePolicy(["example.test"], 60, 1000),
        ):
            pytest.fail("The synthetic client must stop before opening a page")
    assert phases == ["import", "construct", "connect"]
    assert caplog.records == []
