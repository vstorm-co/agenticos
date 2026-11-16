"""Actual native adapter protocol: exact document, one export and no private output."""

import pytest

from app.agents.capabilities.browser_use import _continuation_page as native
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from tests.test_browser_session import ORIGIN, PRIVATE, raw_cookie

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class Protocol:
    def __init__(self):
        self.origin = ORIGIN
        self.loader = "document-one"
        self.protected = True
        self.calls = []
        self.cookies = [raw_cookie()]
        self.answers = {}
        self.after_export = False

    async def send(self, method, params):
        self.calls.append((method, params))
        if method in self.answers:
            answer = self.answers[method]
            if isinstance(answer, Exception):
                raise answer
            return answer
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "main-frame",
                        "loaderId": self.loader,
                        "url": ORIGIN + "/" + PRIVATE,
                    }
                }
            }
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 7}
        if method == "Runtime.evaluate":
            return {"result": {"objectId": "private-native-reference"}}
        if method == "Runtime.callFunctionOn":
            return {"result": {"value": {"origin": self.origin}}}
        if method == "Storage.getCookies":
            if self.after_export:
                self.loader = "changed-during-cookie-read"
            return {"cookies": self.cookies}
        return {}

    def page(self, context="owned-context"):
        return native.ContinuationPage(self.send, context, lambda: self.protected)


@pytest.fixture(autouse=True)
def public_origin(monkeypatch):
    async def public(origin):
        assert origin == ORIGIN

    monkeypatch.setattr(native, "public_destination", public)


async def test_preparation_reads_only_current_identity_and_export_is_once_for_owned_context():
    protocol = Protocol()
    page = protocol.page()
    seen = await page.prepare()
    assert seen.origin == ORIGIN and PRIVATE not in seen.model_dump_json()
    assert not any(method == "Storage.getCookies" for method, _ in protocol.calls)
    assert await page.verify() == seen
    cookies = await page.export(now=20)
    assert cookies[0].value.get_secret_value() == PRIVATE
    assert PRIVATE not in repr(cookies)
    assert [(m, p) for m, p in protocol.calls if m == "Storage.getCookies"] == [
        ("Storage.getCookies", {"browserContextId": "owned-context"})
    ]
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    await page.close()
    assert protocol.calls[-1] == ("Runtime.releaseObject", {"objectId": "private-native-reference"})
    assert not any("localStorage" in str(params) for _, params in protocol.calls)


@pytest.mark.parametrize("mutation", ["frame", "origin", "protection", "no-context"])
async def test_navigation_or_lost_protection_refuses_before_cookie_read(mutation):
    protocol = Protocol()
    page = protocol.page()
    await page.prepare()
    if mutation == "frame":
        protocol.loader = "new-document"
    elif mutation == "origin":
        protocol.origin = "https://other.example.com"
    elif mutation == "protection":
        protocol.protected = False
    else:
        page._context = ""
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    assert not any(method == "Storage.getCookies" for method, _ in protocol.calls)


async def test_navigation_during_export_does_not_return_state_and_never_retries():
    protocol = Protocol()
    page = protocol.page()
    await page.prepare()
    protocol.after_export = True
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    assert sum(method == "Storage.getCookies" for method, _ in protocol.calls) == 1


@pytest.mark.parametrize(
    "method,answer",
    [
        ("Page.getFrameTree", {"frameTree": {"frame": {"id": "frame"}}}),
        ("Page.createIsolatedWorld", {"executionContextId": 0}),
        ("Runtime.evaluate", {"result": {"value": PRIVATE}}),
        ("Runtime.callFunctionOn", {"result": {"value": None}}),
        ("Runtime.evaluate", {"exceptionDetails": {"text": PRIVATE}}),
        ("Page.getFrameTree", [PRIVATE]),
        ("Runtime.evaluate", RuntimeError(PRIVATE)),
    ],
)
async def test_page_chosen_errors_and_malformed_native_answers_are_fixed_refusals(method, answer):
    protocol = Protocol()
    protocol.answers[method] = answer
    page = protocol.page()
    with pytest.raises(BrowserContinuationRefused) as caught:
        await page.prepare()
    assert PRIVATE not in str(caught.value)
    assert page.observation is None and page._object is None


async def test_native_transport_uncertainty_spends_export_and_suppresses_private_errors():
    protocol = Protocol()
    page = protocol.page()
    await page.prepare()
    protocol.answers["Storage.getCookies"] = RuntimeError(PRIVATE)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await page.export(now=20)
    assert caught.value.reason == BrowserContinuationReason.PROVIDER_UNAVAILABLE
    assert PRIVATE not in str(caught.value)
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    assert sum(method == "Storage.getCookies" for method, _ in protocol.calls) == 1


async def test_missing_native_handle_refuses_without_exporting_or_recreating_it():
    protocol = Protocol()
    page = protocol.page()
    await page.prepare()
    page._object = None
    with pytest.raises(BrowserContinuationRefused) as caught:
        await page.export(now=20)
    assert caught.value.reason == BrowserContinuationReason.DOCUMENT_CHANGED
    assert not any(method == "Storage.getCookies" for method, _ in protocol.calls)
    assert sum(method == "Runtime.evaluate" for method, _ in protocol.calls) == 1


@pytest.mark.parametrize("after_cookie_read", [False, True])
async def test_malformed_current_document_is_a_fixed_refusal_before_or_after_export(
    after_cookie_read,
):
    protocol = Protocol()

    async def send(method, params):
        result = await protocol.send(method, params)
        if method == "Storage.getCookies":
            protocol.answers["Runtime.callFunctionOn"] = {"result": {"value": PRIVATE}}
        return result

    page = native.ContinuationPage(send, "owned-context", lambda: protocol.protected)
    await page.prepare()
    if not after_cookie_read:
        protocol.answers["Runtime.callFunctionOn"] = {"result": {"value": PRIVATE}}
    with pytest.raises(BrowserContinuationRefused) as caught:
        await page.export(now=20)
    assert caught.value.reason == BrowserContinuationReason.DOCUMENT_CHANGED
    assert PRIVATE not in str(caught.value)
    assert sum(method == "Storage.getCookies" for method, _ in protocol.calls) == int(
        after_cookie_read
    )
    with pytest.raises(BrowserContinuationRefused):
        await page.export(now=20)
    assert sum(method == "Storage.getCookies" for method, _ in protocol.calls) == int(
        after_cookie_read
    )


async def test_preparation_refuses_navigation_between_native_observation_and_final_frame_check():
    protocol = Protocol()

    async def send(method, params):
        result = await protocol.send(method, params)
        if method == "Runtime.callFunctionOn":
            protocol.loader = "replaced-during-preparation"
        return result

    page = native.ContinuationPage(send, "owned-context", lambda: protocol.protected)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await page.prepare()
    assert caught.value.reason == BrowserContinuationReason.DOCUMENT_CHANGED
    assert page.observation is None and page._object is None
    assert protocol.calls[-1][0] == "Runtime.releaseObject"
    assert not any(method == "Storage.getCookies" for method, _ in protocol.calls)


async def test_private_dns_is_refused_at_preparation_and_again_before_export(monkeypatch):
    protocol = Protocol()
    page = protocol.page()
    await page.prepare()

    async def denied(_origin):
        raise BrowserFillRefused(BrowserFillReason.DESTINATION_REFUSED)

    monkeypatch.setattr(native, "public_destination", denied)
    for action in (lambda: page.export(now=20), page.prepare):
        with pytest.raises(BrowserContinuationRefused) as caught:
            await action()
        assert caught.value.reason == BrowserContinuationReason.DESTINATION_REFUSED
    assert not any(method == "Storage.getCookies" for method, _ in protocol.calls)
