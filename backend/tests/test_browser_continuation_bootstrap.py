"""Protocol-response refusal and exact-origin egress before protected cookie restoration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest

from app.agents.capabilities.browser_use import _page as pages
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_session import ProtectedSignIn, bounded_cookies
from tests.test_browser_session import ORIGIN, provenance, raw_cookie

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "response", [{}, {"browserContextId": ""}, {"browserContextId": None}, {"browserContextId": 7}]
)
@pytest.mark.parametrize("protected", [True, False])
async def test_malformed_context_never_falls_back_to_default_cookie_store(
    monkeypatch, response, protected
):
    import cdp_use

    target = SimpleNamespace(
        createBrowserContext=AsyncMock(return_value=response),
        createTarget=AsyncMock(),
        closeTarget=AsyncMock(),
        disposeBrowserContext=AsyncMock(),
    )
    storage = SimpleNamespace(setCookies=AsyncMock())
    client = SimpleNamespace(
        send=SimpleNamespace(Target=target, Storage=storage), start=AsyncMock(), stop=AsyncMock()
    )
    monkeypatch.setattr(cdp_use, "CDPClient", lambda socket: client)
    state = ProtectedSignIn(
        provenance=provenance(), cookies=bounded_cookies(ORIGIN, [raw_cookie()], now=20)
    )
    with pytest.raises(BrowserContinuationRefused if protected else pages.EndpointError) as refused:
        async with pages.open_page(
            cdp_url="ws://127.0.0.1:9222/devtools/browser/synthetic",
            start_url=ORIGIN,
            policy=pages.PagePolicy([urlsplit(ORIGIN).hostname], 200, 1280),
            protected_sign_in=state if protected else None,
        ):
            pytest.fail("A malformed context must not publish a page")
    if protected:
        assert refused.value.reason == BrowserContinuationReason.PROTECTION_UNAVAILABLE
    else:
        assert str(refused.value) == "The browser did not allocate an isolated context."
    target.createTarget.assert_not_awaited()
    storage.setCookies.assert_not_awaited()
    target.closeTarget.assert_not_awaited()
    target.disposeBrowserContext.assert_not_awaited()
    client.stop.assert_awaited_once()


@pytest.mark.parametrize(
    "url,admitted",
    [
        (ORIGIN + "/safe?opaque=value", True),
        ("https://other.example.com/path", False),
        ("https://child.portal.example.com/path", False),
        ("https://portal.example.com:8443/path", False),
        ("http://portal.example.com/path", False),
        ("https://secret:password@portal.example.com/path", False),
    ],
)
async def test_redirects_and_subresources_are_refused_before_any_broader_egress_policy(
    monkeypatch, url, admitted
):
    callbacks = {}
    fetch = SimpleNamespace(
        enable=AsyncMock(),
        failRequest=AsyncMock(),
        continueRequest=AsyncMock(),
        continueWithAuth=AsyncMock(),
    )

    def register(name):
        return lambda callback: callbacks.__setitem__(name, callback)

    client = SimpleNamespace(
        send=SimpleNamespace(Fetch=fetch),
        register=SimpleNamespace(
            Fetch=SimpleNamespace(requestPaused=register("request"), authRequired=register("auth"))
        ),
    )
    egress = AsyncMock(return_value=False)
    monkeypatch.setattr(pages, "egress_refused", egress)
    await pages._intercept(client, "owned-session", None, None, protected_origin=ORIGIN)
    callbacks["request"]({"requestId": "owned-request", "request": {"url": url}}, "another-session")
    await asyncio.sleep(0)
    fetch.failRequest.assert_not_awaited()
    fetch.continueRequest.assert_not_awaited()
    callbacks["request"]({"requestId": "owned-request", "request": {"url": url}}, "owned-session")
    for _ in range(5):
        await asyncio.sleep(0)
        if fetch.failRequest.await_count or fetch.continueRequest.await_count:
            break
    if admitted:
        egress.assert_awaited_once_with(url, None)
        fetch.continueRequest.assert_awaited_once_with(
            params={"requestId": "owned-request"}, session_id="owned-session"
        )
        fetch.failRequest.assert_not_awaited()
    else:
        egress.assert_not_awaited()
        fetch.continueRequest.assert_not_awaited()
        fetch.failRequest.assert_awaited_once_with(
            params={"requestId": "owned-request", "errorReason": "AddressUnreachable"},
            session_id="owned-session",
        )
