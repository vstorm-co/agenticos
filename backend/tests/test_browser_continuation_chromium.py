"""Actual Chromium cookie export/restore with one synthetic disposable browser process.

The original network admission guard runs; only its exact synthetic-origin admitted
requests are fulfilled locally. No user profile, website, provider or paid call is used.
"""

import base64
import json
import time
from dataclasses import asdict
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest

from app.agents.capabilities.browser_use import _continuation_page as native
from app.agents.capabilities.browser_use import _credential_page as fill_native
from app.agents.capabilities.browser_use import _page as pages
from app.agents.capabilities.browser_use._protected import PROTECTED_TEXT
from app.core.browser_continuation import BrowserContinuationRefused
from app.core.browser_session import ProtectedSignIn
from tests.test_browser_credential_chromium import (
    LOGIN,
    ORIGIN,
    PASSWORD,
    USERNAME,
    NativeCdp,
    NativeClient,
    NativeDomain,
    SyntheticPage,
    fake_values,
    selected,
)
from tests.test_browser_credential_chromium import chromium_process as chromium_process
from tests.test_browser_session import PRIVATE, provenance

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
async def owned_page(chromium_process, monkeypatch):
    from websockets.asyncio.client import connect

    original = native.public_destination

    async def destination(origin):
        if origin != ORIGIN:
            await original(origin)

    monkeypatch.setattr(native, "public_destination", destination)
    monkeypatch.setattr(fill_native, "public_destination", destination)
    async with connect(chromium_process.websocket, proxy=None, max_size=8 * 1024 * 1024) as socket:
        cdp = NativeCdp(socket)
        context = (await cdp.send("Target.createBrowserContext", {"disposeOnDetach": True}))[
            "browserContextId"
        ]
        target = (
            await cdp.send(
                "Target.createTarget", {"url": "about:blank", "browserContextId": context}
            )
        )["targetId"]
        session = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))[
            "sessionId"
        ]
        browser = SyntheticPage(cdp, session)
        client = NativeClient(cdp)
        client.Storage = NativeDomain(cdp, "Storage")
        browser.page = pages.CdpPage(
            client,
            session,
            pages.PagePolicy([urlsplit(ORIGIN).hostname], 200, 1280),
            context_id=context,
        )
        browser.context = context
        try:
            await cdp.send("Page.enable", session_id=session)
            await cdp.send("Network.enable", session_id=session)
            await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session)
            yield browser
        finally:
            try:
                await browser.page.credentials.close()
                await browser.page.continuation.close()
            finally:
                try:
                    await cdp.send("Target.closeTarget", {"targetId": target})
                finally:
                    await cdp.send("Target.disposeBrowserContext", {"browserContextId": context})
                    await cdp.close()


async def post_submit(browser):
    await browser.open(LOGIN)
    snapshot = await browser.snapshot()
    filled = await browser.page.credentials.prepare(
        selected(snapshot, ("username", "#username"), ("password", "#password")), snapshot
    )
    browser.page.protect_credentials(ORIGIN)
    assert await browser.page.credentials.fill(lambda: fake_values(USERNAME, PASSWORD))
    assert await browser.evaluate("submitCount") == 0
    assert await browser.page.credentials.submit()
    assert await browser.evaluate("submitCount") == 1
    # Simulate the site's next document, retaining the protected original context.
    await browser.open("<p>Post-submit synthetic page</p>", path="/after-submit")
    await browser.cdp.send(
        "Storage.setCookies",
        {
            "browserContextId": browser.context,
            "cookies": [
                {
                    "url": ORIGIN,
                    "name": "sid",
                    "value": PRIVATE,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Strict",
                },
                {
                    "domain": "." + urlsplit(ORIGIN).hostname,
                    "name": "parent",
                    "value": "excluded-parent-cookie",
                    "path": "/",
                    "secure": True,
                },
            ],
        },
    )
    await browser.evaluate("localStorage.setItem('must-not-copy', 'synthetic-private-storage')")
    seen = await browser.page.continuation.prepare()
    assert seen.document_id != filled.document_id and seen.origin == ORIGIN
    return seen


async def test_actual_native_export_is_context_scoped_cookie_only_and_one_attempt(owned_page):
    browser = owned_page
    seen = await post_submit(browser)
    before = browser.cdp.methods.count("Storage.getCookies")
    assert before == 0
    cookies = await browser.page.continuation.export(now=time.time())
    assert browser.cdp.methods.count("Storage.getCookies") == 1
    assert len(cookies) == 1 and cookies[0].name.get_secret_value() == "sid"
    assert cookies[0].value.get_secret_value() == PRIVATE and cookies[0].http_only
    assert PRIVATE not in repr(cookies) and PRIVATE not in seen.model_dump_json()
    with pytest.raises(BrowserContinuationRefused):
        await browser.page.continuation.export(now=time.time())
    assert browser.cdp.methods.count("Storage.getCookies") == 1
    assert await browser.page.capture_sign_in() is None
    assert await browser.page.read() == PROTECTED_TEXT and await browser.page.screenshot() is None


@pytest.mark.parametrize("change", ["document", "protection"])
async def test_current_document_and_sticky_guard_are_required_before_cookie_read(
    owned_page, change
):
    browser = owned_page
    await post_submit(browser)
    if change == "document":
        await browser.open("<p>Changed current document</p>", path="/changed")
    else:
        # Simulate a wrong/absent guard callback; application code cannot unprotect it.
        browser.page.continuation._protected = lambda: False
    with pytest.raises(BrowserContinuationRefused):
        await browser.page.continuation.export(now=time.time())
    assert "Storage.getCookies" not in browser.cdp.methods


async def test_actual_sdk_restore_protects_before_cookie_io_and_never_declassifies_hostile_output(
    owned_page, chromium_process, monkeypatch
):
    browser = owned_page
    await post_submit(browser)
    cookies = await browser.page.continuation.export(now=time.time())
    state = ProtectedSignIn(provenance=provenance(origin=ORIGIN), cookies=cookies)
    protected_contexts = set()
    cookie_writes = []
    requests = {}
    original_protect = pages.CdpPage.protect_credentials
    original_intercept = pages._intercept
    original_egress = pages.egress_refused

    def protect(page, origin):
        original_protect(page, origin)
        assert page.output_guard.active
        protected_contexts.add(page._context)

    monkeypatch.setattr(pages.CdpPage, "protect_credentials", protect)

    async def exact_egress(url, allowed):
        if urlsplit(url).scheme == "https" and urlsplit(url).netloc == urlsplit(ORIGIN).netloc:
            return False
        return await original_egress(url, allowed)

    monkeypatch.setattr(pages, "egress_refused", exact_egress)

    hostile = """<!doctype html><title>Protected synthetic</title><body>
    <p id='echo'></p><input id='field' aria-label='safe'><img id='image'>
    <script>
    const value = VALUE;
    document.title = value; echo.textContent = value; field.setAttribute('aria-label', value);
    image.alt = value; image.src = 'data:image/svg+xml,' + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg"><text>' + value + '</text></svg>');
    history.replaceState(null, '', '/echo?private=' + encodeURIComponent(value));
    </script></body>""".replace("VALUE", json.dumps(PRIVATE))

    async def intercept(client, session, route, allowed, *, protected_origin=None):
        assert protected_origin == ORIGIN
        original_set = client.send.Storage.setCookies

        async def set_cookies(*, params):
            assert params["browserContextId"] in protected_contexts
            cookie_writes.append(params["browserContextId"])
            return await original_set(params=params)

        monkeypatch.setattr(client.send.Storage, "setCookies", set_cookies)

        original_register = client.register.Fetch.requestPaused

        def register(callback):
            # cdp-use keeps one callback per method. Compose this synthetic
            # observation with the real guard instead of replacing either one.
            def observed(event, session_id):
                if session_id == session:
                    requests[event["requestId"]] = event["request"]["url"]
                callback(event, session_id)

            original_register(observed)

        monkeypatch.setattr(client.register.Fetch, "requestPaused", register)

        async def fulfill(*, params, session_id):
            assert session_id == session
            url = requests[params["requestId"]]
            assert (
                urlsplit(url).scheme == "https" and urlsplit(url).netloc == urlsplit(ORIGIN).netloc
            )
            return await client.send.Fetch.fulfillRequest(
                params={
                    "requestId": params["requestId"],
                    "responseCode": 200,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": "text/html; charset=utf-8"}
                    ],
                    "body": base64.b64encode(hostile.encode()).decode(),
                },
                session_id=session,
            )

        # The actual admission handler still makes each allow/deny decision.
        monkeypatch.setattr(client.send.Fetch, "continueRequest", fulfill)
        await original_intercept(client, session, route, allowed, protected_origin=protected_origin)

    monkeypatch.setattr(pages, "_intercept", intercept)
    before = set((await browser.cdp.send("Target.getBrowserContexts"))["browserContextIds"])
    async with pages.open_page(
        cdp_url=chromium_process.websocket,
        start_url=ORIGIN,
        policy=pages.PagePolicy([urlsplit(ORIGIN).hostname], 200, 1280),
        protected_sign_in=state,
    ) as restored:
        assert restored._context != browser.context and cookie_writes == [restored._context]
        assert restored.inherited_credentials == state.provenance.credential_generations
        answer = await restored._client.send.Runtime.evaluate(
            params={
                "expression": "[document.title,echo.textContent,field.getAttribute('aria-label'),image.alt,location.href,localStorage.getItem('must-not-copy')]",
                "returnByValue": True,
            },
            session_id=restored._session,
        )
        echoes = answer["result"]["value"]
        assert all(PRIVATE in value for value in echoes[:5]) and echoes[5] is None
        snapshot = await restored.snapshot()
        assert PRIVATE not in json.dumps(asdict(snapshot))
        assert await restored.read() == PROTECTED_TEXT
        assert await restored.location() == (ORIGIN, "Protected browser session")
        assert await restored.screenshot() is None and await restored.capture_sign_in() is None
        sink = AsyncMock()
        async with restored.stream(sink):
            pass
        sink.assert_not_awaited()
        with pytest.raises(pages.EndpointError):
            await restored._evaluate("document.body.innerText")
    after = set((await browser.cdp.send("Target.getBrowserContexts"))["browserContextIds"])
    assert after == before and browser.context in after
    assert browser.page.output_guard.active
    assert await browser.page.read() == PROTECTED_TEXT
