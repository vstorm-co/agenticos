"""A protected page's native commands: cookie reads, navigation and the fixed command set.

Nothing here reaches a browser; the client records which protocol command each
call became and answers with what the test scripts.
"""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused

pytestmark = pytest.mark.anyio

ORIGIN = "https://portal.example.com"
SESSION = "one-session"


def _page(context: str = "owned-context") -> tuple[CdpPage, MagicMock]:
    client = MagicMock()
    page = CdpPage(client, SESSION, PagePolicy(None, 60, 1024), context_id=context)
    return page, client


def _protected(context: str = "owned-context") -> tuple[CdpPage, MagicMock]:
    page, client = _page(context)
    page.protect_credentials(ORIGIN)
    return page, client


def _prepare(page: CdpPage, *answers: Any) -> AsyncMock:
    prepare = AsyncMock(side_effect=list(answers))
    page.continuation = cast(Any, SimpleNamespace(prepare=prepare, close=AsyncMock()))
    return prepare


@pytest.mark.parametrize(
    "method",
    [
        "Page.createIsolatedWorld",
        "Runtime.callFunctionOn",
        "Runtime.evaluate",
        "Runtime.releaseObject",
    ],
)
async def test_a_native_command_is_sent_on_this_pages_own_session(method: str) -> None:
    page, client = _page()
    domain, name = method.split(".")
    send = AsyncMock(return_value={"ok": method})
    setattr(getattr(client.send, domain), name, send)
    assert await page._credential_command(cast(Any, method), {"a": 1}) == {"ok": method}
    send.assert_awaited_once_with(params={"a": 1}, session_id=SESSION)


async def test_a_command_outside_the_fixed_native_set_sends_nothing() -> None:
    page, client = _page()
    assert await page._credential_command(cast(Any, "Runtime.enable"), {}) is None
    assert client.send.mock_calls == []


async def test_the_frame_tree_is_read_without_parameters() -> None:
    page, client = _page()
    client.send.Page.getFrameTree = AsyncMock(return_value="tree")
    assert await page._credential_command("Page.getFrameTree", {}) == "tree"
    client.send.Page.getFrameTree.assert_awaited_once_with(session_id=SESSION)


async def test_cookies_are_read_only_for_the_browser_context_the_page_owns() -> None:
    page, client = _page()
    client.send.Storage.getCookies = AsyncMock(return_value={"cookies": []})
    params = {"browserContextId": "owned-context"}
    assert await page._continuation_command("Storage.getCookies", params) == {"cookies": []}
    client.send.Storage.getCookies.assert_awaited_once_with(params=params)
    for wrong in ({"browserContextId": "other"}, {}):
        with pytest.raises(BrowserContinuationRefused) as refused:
            await page._continuation_command("Storage.getCookies", wrong)
        assert refused.value.reason == BrowserContinuationReason.PROTECTION_UNAVAILABLE
    contextless, _ = _page(context="")
    with pytest.raises(BrowserContinuationRefused):
        await contextless._continuation_command("Storage.getCookies", {"browserContextId": ""})


async def test_other_continuation_commands_use_the_native_command_set() -> None:
    page, client = _page()
    client.send.Runtime.evaluate = AsyncMock(return_value="seen")
    assert await page._continuation_command("Runtime.evaluate", {"c": 3}) == "seen"


async def test_navigation_is_refused_unless_the_page_is_protected_at_that_origin() -> None:
    open_page, _ = _page()
    with pytest.raises(BrowserContinuationRefused) as refused:
        await open_page.navigate_protected(ORIGIN)
    assert refused.value.reason == BrowserContinuationReason.PROTECTION_UNAVAILABLE
    protected, _ = _protected()
    with pytest.raises(BrowserContinuationRefused):
        await protected.navigate_protected("https://other.example.com")


async def test_a_navigation_that_lands_on_the_same_origin_succeeds_and_releases_the_page() -> None:
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={})
    prepare = _prepare(page, SimpleNamespace(origin=ORIGIN))
    await page.navigate_protected(ORIGIN)
    client.send.Page.navigate.assert_awaited_once_with(params={"url": ORIGIN}, session_id=SESSION)
    prepare.assert_awaited_once()
    cast(Any, page.continuation).close.assert_awaited_once()


async def test_a_navigation_the_browser_rejects_is_a_provider_failure() -> None:
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={"errorText": "net::ERR_FAILED"})
    prepare = _prepare(page)
    with pytest.raises(BrowserContinuationRefused) as refused:
        await page.navigate_protected(ORIGIN)
    assert refused.value.reason == BrowserContinuationReason.PROVIDER_UNAVAILABLE
    prepare.assert_not_awaited()
    cast(Any, page.continuation).close.assert_awaited_once()


async def test_a_navigation_that_ends_on_another_origin_is_refused() -> None:
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={})
    _prepare(page, SimpleNamespace(origin="https://elsewhere.example.com"))
    with pytest.raises(BrowserContinuationRefused) as refused:
        await page.navigate_protected(ORIGIN)
    assert refused.value.reason == BrowserContinuationReason.DESTINATION_REFUSED


async def test_a_document_still_loading_is_retried_until_it_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={})
    changed = BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
    prepare = _prepare(page, changed, changed, SimpleNamespace(origin=ORIGIN))
    await page.navigate_protected(ORIGIN)
    assert prepare.await_count == 3


async def test_a_document_that_never_settles_is_refused_after_twenty_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={})
    changed = BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
    prepare = _prepare(page, *[changed] * 20)
    with pytest.raises(BrowserContinuationRefused) as refused:
        await page.navigate_protected(ORIGIN)
    assert refused.value.reason == BrowserContinuationReason.DOCUMENT_CHANGED
    assert prepare.await_count == 20


async def test_any_other_refusal_while_reading_the_new_document_stops_the_wait() -> None:
    page, client = _protected()
    client.send.Page.navigate = AsyncMock(return_value={})
    other = BrowserContinuationRefused(BrowserContinuationReason.DESTINATION_REFUSED)
    prepare = _prepare(page, other)
    with pytest.raises(BrowserContinuationRefused) as refused:
        await page.navigate_protected(ORIGIN)
    assert refused.value is other
    assert prepare.await_count == 1
