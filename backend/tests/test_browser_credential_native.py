"""Synthetic native protocol, TOTP windows and the sticky credential output boundary."""

import asyncio
import base64
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.browser_use import _credential_page as native
from app.agents.capabilities.browser_use._elements import Element, Snapshot
from app.agents.capabilities.browser_use._page import CdpPage, EndpointError, PagePolicy
from app.agents.capabilities.browser_use._protected import PROTECTED_TEXT, BrowserOutputGuard
from app.core.browser_fill import (
    BrowserFillHandle,
    BrowserFillObservation,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillSelection,
)
from app.core.browser_totp import browser_code
from app.core.secret_kinds import BrowserProfileSecret, BrowserTotp
from app.schemas.browser_credential import BrowserCredentialPolicyWrite
from app.services.browser_credentials._controller import fill_values
from app.services.browser_credentials._plans import AuthorizedFill
from tests.test_browser_credentials import PASSWORD, SEED, USERNAME, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ORIGIN = "https://portal.example.test"


def test_the_first_zero_based_native_element_is_selectable() -> None:
    selected = BrowserFillSelection.model_validate(
        {
            "fields": [{"field": "username", "element_id": 0}],
        }
    )
    assert selected.fields[0].element_id == 0
    with pytest.raises(ValidationError):
        BrowserFillSelection.model_validate({"fields": [{"field": "username", "element_id": -1}]})


def selection(*fields: str) -> BrowserFillSelection:
    return BrowserFillSelection.model_validate(
        {
            "fields": [
                {"field": field, "element_id": index + 1} for index, field in enumerate(fields)
            ]
        }
    )


def snapshot() -> Snapshot:
    return Snapshot(
        ORIGIN,
        "Portal",
        (
            Element(1, "textbox", "Login", path="form > input:nth-of-type(1)"),
            Element(2, "password", "Password", path="form > input:nth-of-type(2)"),
        ),
    )


class Protocol:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.loader = "document-1"
        self.origin = ORIGIN
        self.valid = True
        self.value_reply = "filled"
        self.submit_reply = "submitted"
        self.observation: dict = {}
        self.bad: dict[str, object] = {}
        self.started = asyncio.Event()
        self.block = False
        self.values: list[str] = []
        self.controls = [
            {"index": 1, "role": "text", "hint": "one-time-code", "path": "form > input"}
        ]

    async def send(self, method: str, params: dict) -> object:
        self.calls.append((method, params))
        if method in self.bad:
            failure = self.bad[method]
            if isinstance(failure, Exception):
                raise failure
            return failure
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "frame-1", "loaderId": self.loader}}}
        if method == "Page.createIsolatedWorld":
            assert params["grantUniveralAccess"] is False
            return {"executionContextId": 4}
        if method == "Runtime.evaluate":
            return {"result": {"type": "string", "value": self.origin}}
        if method == "Runtime.releaseObject":
            return {}
        assert method == "Runtime.callFunctionOn"
        assert params["silent"] is True and params["userGesture"] is False
        function = params["functionDeclaration"]
        if function == native._PREPARE:
            chosen, document = [item["value"] for item in params["arguments"]]
            self.observation = {
                "document_id": document,
                "origin": ORIGIN,
                "fields": [
                    {
                        "field": item["field"],
                        "handle": item["handle"],
                        "role": "password" if item["field"] == "password" else "text",
                        "form_origin": ORIGIN,
                    }
                    for item in chosen
                ],
            }
            return {"result": {"type": "object", "objectId": "private-native-object"}}
        if function == native._DESCRIBE:
            value = self.observation
        elif function in (native._VERIFY, native._CAN_SUBMIT):
            value = self.valid
        elif function == native._FILL:
            self.values = params["arguments"][0]["value"]
            self.started.set()
            if self.block:
                await asyncio.Event().wait()
            value = self.value_reply
        elif function == native._SUBMIT:
            value = self.submit_reply
        elif function == native._PROTECTED_FORM:
            value = self.controls
        else:
            raise AssertionError("Unexpected native function")
        return {"result": {"type": "object", "value": value}}


@pytest.fixture
def public(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    checked = AsyncMock()
    monkeypatch.setattr(native, "public_destination", checked)
    return checked


@pytest.mark.parametrize(
    ("algorithm", "key", "expected"),
    [
        ("SHA1", b"12345678901234567890", "94287082"),
        ("SHA256", b"12345678901234567890123456789012", "46119246"),
        ("SHA512", b"1234567890123456789012345678901234567890123456789012345678901234", "90693936"),
    ],
)
def test_totp_matches_rfc6238_vectors_and_does_not_render_its_value(
    algorithm, key, expected
) -> None:
    config = BrowserTotp(seed=base64.b32encode(key).decode(), algorithm=algorithm, digits=8)
    code = browser_code(config, at=59)
    assert code.value.get_secret_value() == expected and code.valid_until == 60
    assert expected not in repr(code) and config.seed.get_secret_value() not in repr(config)
    code60 = browser_code(config.model_copy(update={"period_seconds": 60}), at=119)
    assert code60.value == code.value and code60.valid_until == 120


def test_default_six_digit_code_keeps_leading_zeros_and_a_normalized_seed() -> None:
    """The path after `browser_code`'s clock guard: default SHA1/6/30 truncation,
    zero padding, and a lowercase padded seed stored in its canonical form."""
    key = base64.b32encode(b"12345678901234567890").decode()
    canonical = BrowserTotp(seed=key)
    # RFC 6238's SHA1 vector at T=59 is 94287082; six digits keep its last six.
    assert browser_code(canonical, at=59).value.get_secret_value() == "287082"
    padded = browser_code(canonical, at=900)
    assert padded.value.get_secret_value() == "026920" and padded.valid_until == 930
    lowered = BrowserTotp(seed=key.lower() + "====")
    assert lowered.seed.get_secret_value() == key.rstrip("=")
    assert browser_code(lowered, at=900).value == padded.value


@pytest.mark.parametrize("clock", [-1, float("nan"), float("inf"), 30 * 2**64])
def test_totp_rejects_invalid_clock_without_seed_in_exception(clock) -> None:
    with pytest.raises(ValueError) as refused:
        browser_code(login().totp, at=clock)
    assert SEED not in str(refused.value)


def test_fill_contract_rejects_duplicate_fields_handles_and_unbound_destinations() -> None:
    selected = selection("username", "password")
    assert selected.fields[1].element_id == 2
    for fields in [
        [{"field": "password", "element_id": 1}, {"field": "password", "element_id": 2}],
        [{"field": "username", "element_id": 1}, {"field": "password", "element_id": 1}],
        [{"field": "password", "element_id": -1}],
        [{"field": "script", "element_id": 1}],
    ]:
        with pytest.raises(ValidationError):
            BrowserFillSelection.model_validate({"fields": fields})
    handle = BrowserFillHandle(
        field="password", handle=uuid4(), role="password", form_origin=ORIGIN
    )
    base = {"document_id": uuid4(), "origin": ORIGIN, "fields": [handle]}
    assert BrowserFillObservation.model_validate(base).origin == ORIGIN
    for changes in [
        {"fields": [handle, handle]},
        {"origin": "https://other.example.test"},
        {"fields": [handle.model_copy(update={"form_origin": "http://private.local"})]},
    ]:
        with pytest.raises(ValidationError):
            BrowserFillObservation.model_validate(base | changes)
    for payload in [
        {"mode": "shared"},
        {"mode": "personal", "agent_ids": [uuid4()]},
        {"mode": "shared", "agent_ids": [uuid4()], "member_ids": [uuid4(), uuid4()]},
    ]:
        if payload.get("member_ids"):
            payload["member_ids"][1] = payload["member_ids"][0]
        with pytest.raises(ValidationError):
            BrowserCredentialPolicyWrite.model_validate({"generation": uuid4()} | payload)
    assert WebBrowserConfig().browser_credential_ids == []
    reference = uuid4()
    with pytest.raises(ValidationError):
        WebBrowserConfig(browser_credential_ids=[reference, reference])


async def test_public_destination_pins_https_and_normalizes_private_or_failed_dns(
    monkeypatch,
) -> None:
    calls = []

    def resolved(origin, *, allowed_schemes):
        calls.append((origin, allowed_schemes))

    monkeypatch.setattr(native, "resolve_pinned_url", resolved)
    await native.public_destination(ORIGIN)
    assert calls == [(ORIGIN, frozenset({"https"}))]
    for destination in ("http://portal.example.test", "https://127.0.0.1", "https://10.0.0.1"):
        with pytest.raises(BrowserFillRefused) as caught:
            await native.public_destination(destination)
        assert caught.value.reason == BrowserFillReason.DESTINATION_REFUSED

    def failed(*args, **kwargs):
        raise OSError(PASSWORD)

    monkeypatch.setattr(native, "resolve_pinned_url", failed)
    with pytest.raises(BrowserFillRefused) as caught:
        await native.public_destination(ORIGIN)
    assert PASSWORD not in str(caught.value)


async def test_missing_or_malformed_object_reply_refuses_and_invalid_observation_is_released(
    public,
) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    with pytest.raises(BrowserFillRefused):
        await page._call(native._VERIFY)
    await page.prepare(selection("password"), snapshot())
    protocol.bad["Runtime.callFunctionOn"] = {"unexpected": "private"}
    with pytest.raises(BrowserFillRefused):
        await page._call(native._VERIFY)
    protocol.bad.clear()
    original = protocol.send

    async def malformed(method, params):
        answer = await original(method, params)
        if params.get("functionDeclaration") == native._DESCRIBE:
            return {"result": {"type": "object", "value": {"document_id": "invalid"}}}
        return answer

    page = native.CredentialPage(malformed)
    with pytest.raises(BrowserFillRefused):
        await page.prepare(selection("password"), snapshot())
    assert page._object is None and page.observation is None
    assert any(method == "Runtime.releaseObject" for method, _ in protocol.calls)


async def test_protected_roles_are_discarded_if_the_document_changes_during_observation(
    public,
) -> None:
    protocol = Protocol()
    original = protocol.send

    async def changed(method, params):
        answer = await original(method, params)
        if params.get("functionDeclaration") == native._PROTECTED_FORM:
            protocol.loader = "replaced-document"
        return answer

    with pytest.raises(BrowserFillRefused):
        await native.CredentialPage(changed).protected_snapshot(ORIGIN)


async def test_value_count_mismatch_and_changed_form_never_attempt_fill_or_submit(public) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    await page.prepare(selection("password"), snapshot())
    with pytest.raises(BrowserFillRefused):
        await page.fill(lambda: native.NativeFillValues(()))
    assert protocol.values == []
    assert await page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
    protocol.valid = False
    with pytest.raises(BrowserFillRefused):
        await page.verify_submission()


@pytest.mark.parametrize("timeout", [False, True])
async def test_uncertain_submit_acknowledgement_is_never_retried(
    public, monkeypatch, timeout
) -> None:
    protocol = Protocol()
    original = protocol.send
    attempts = 0

    async def unreliable(method, params):
        nonlocal attempts
        if params.get("functionDeclaration") == native._SUBMIT:
            attempts += 1
            if timeout:
                await asyncio.Event().wait()
            raise RuntimeError(PASSWORD)
        return await original(method, params)

    monkeypatch.setattr(native, "FILL_SECONDS", 0.01)
    page = native.CredentialPage(unreliable)
    await page.prepare(selection("password"), snapshot())
    assert await page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
    assert not await page.submit()
    with pytest.raises(BrowserFillRefused):
        await page.submit()
    assert attempts == 1


def test_persisted_model_representations_have_no_payloads() -> None:
    from app.db.models.browser_credential import (
        BrowserCredentialAgentGrant,
        BrowserCredentialMemberGrant,
        BrowserCredentialPlan,
        BrowserCredentialPolicy,
    )

    org, secret = uuid4(), uuid4()
    rows = [
        BrowserCredentialPolicy(organization_id=org, secret_id=secret),
        BrowserCredentialAgentGrant(organization_id=org, secret_id=secret, agent_id=uuid4()),
        BrowserCredentialMemberGrant(organization_id=org, secret_id=secret, user_id=uuid4()),
        BrowserCredentialPlan(id=uuid4(), state="refused", selection={"invalid": PASSWORD}),
    ]
    assert all("BrowserCredential" in repr(row) and PASSWORD not in repr(row) for row in rows)


async def test_only_one_object_bound_native_call_receives_values_and_submit_is_separate(
    public,
) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    observed = await page.prepare(selection("username", "password"), snapshot())
    assert await page.origin() == ORIGIN
    factory = Mock(return_value=native.NativeFillValues((SecretStr(USERNAME), SecretStr(PASSWORD))))
    assert await page.fill(factory)
    factory.assert_called_once()
    assert protocol.values == [USERNAME, PASSWORD]
    assert not any(call[1].get("functionDeclaration") == native._SUBMIT for call in protocol.calls)
    assert not any(secret in observed.model_dump_json() for secret in (USERNAME, PASSWORD, SEED))
    with pytest.raises(BrowserFillRefused):
        await page.fill(factory)
    assert await page.submit()
    with pytest.raises(BrowserFillRefused):
        await page.submit()
    await page.close()
    assert protocol.calls[-1][0] == "Runtime.releaseObject"
    assert (
        sum(params.get("functionDeclaration") == native._FILL for _, params in protocol.calls) == 1
    )
    assert all(
        "objectId" in params
        for _, params in protocol.calls
        if params.get("functionDeclaration")
        in (native._DESCRIBE, native._VERIFY, native._FILL, native._SUBMIT)
    )
    await page.prepare(selection("password"), snapshot())
    await page.close()


@pytest.mark.parametrize("changed", ["document", "field"])
async def test_navigation_or_invalidated_field_is_refused_before_values_are_generated(
    public, changed
) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    await page.prepare(selection("password"), snapshot())
    if changed == "document":
        protocol.loader = "new-document"
    else:
        protocol.valid = False
    factory = Mock(return_value=native.NativeFillValues((SecretStr(PASSWORD),)))
    with pytest.raises(BrowserFillRefused):
        await page.fill(factory)
    factory.assert_not_called()
    assert protocol.values == []
    await page.close()


@pytest.mark.parametrize("reply", ["unknown", "refused", None])
async def test_uncertain_or_refused_native_effect_never_retries_or_enables_submit(
    public, reply
) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    await page.prepare(selection("password"), snapshot())
    protocol.value_reply = reply
    assert not await page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
    with pytest.raises(BrowserFillRefused):
        await page.submit()
    with pytest.raises(BrowserFillRefused):
        await page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
    await page.close()


async def test_timeout_and_cancellation_leave_the_native_attempt_consumed(
    public, monkeypatch
) -> None:
    for cancel in (False, True):
        protocol = Protocol()
        page = native.CredentialPage(protocol.send)
        await page.prepare(selection("password"), snapshot())
        protocol.block = True
        monkeypatch.setattr(native, "FILL_SECONDS", 0.02 if not cancel else 5)
        task = asyncio.create_task(
            page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
        )
        await protocol.started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task is False
        with pytest.raises(BrowserFillRefused):
            await page.fill(lambda: native.NativeFillValues((SecretStr(PASSWORD),)))
        await page.close()
        assert (
            sum(params.get("functionDeclaration") == native._FILL for _, params in protocol.calls)
            == 1
        )


@pytest.mark.parametrize(
    ("method", "reply"),
    [
        ("Page.getFrameTree", None),
        ("Page.getFrameTree", {"frameTree": {"frame": {"id": "missing-loader"}}}),
        ("Page.createIsolatedWorld", {"executionContextId": "unsafe"}),
        ("Runtime.callFunctionOn", {"result": {"type": "object"}}),
        ("Runtime.callFunctionOn", {"exceptionDetails": {"text": PASSWORD}}),
        ("Runtime.callFunctionOn", RuntimeError(PASSWORD)),
    ],
)
async def test_bad_native_protocol_returns_fixed_refusal_without_exception_details(
    public, method, reply
) -> None:
    protocol = Protocol()
    protocol.bad[method] = reply
    page = native.CredentialPage(protocol.send)
    with pytest.raises(BrowserFillRefused) as refused:
        await page.prepare(selection("password"), snapshot())
    assert PASSWORD not in str(refused.value) and PASSWORD not in repr(refused.value)
    await page.close()


async def test_unknown_selected_element_and_unusable_origin_never_get_native_authority(
    public,
) -> None:
    protocol = Protocol()
    page = native.CredentialPage(protocol.send)
    for elements in [
        (),
        (Element(1, "password", "Password"),),
        (Element(1, "password", "Password", path="x" * 4097),),
    ]:
        with pytest.raises(BrowserFillRefused):
            await page.prepare(selection("password"), Snapshot(ORIGIN, "", elements))
    for origin in [None, "http://localhost", "https://portal.example.test/echo"]:
        protocol.origin = origin
        assert await page.origin() == ""
    protocol.bad["Runtime.evaluate"] = {"result": {}}
    assert await page.origin() == ""
    assert protocol.values == []


async def test_value_free_controls_hide_attacker_labels_values_errors_and_full_addresses(
    public,
) -> None:
    protocol = Protocol()
    protocol.controls[0] |= {
        "label": PASSWORD,
        "value": PASSWORD,
        "options": [PASSWORD],
        "url": f"{ORIGIN}/{PASSWORD}",
    }
    page = native.CredentialPage(protocol.send)
    observed = await page.protected_snapshot(ORIGIN)
    assert observed.title == "Protected browser session"
    assert observed.elements[0].label == "Verification code field"
    assert observed.elements[0].value is None and observed.elements[0].options == ()
    assert PASSWORD not in repr(observed)
    protocol.controls[0]["hint"] = PASSWORD
    with pytest.raises(BrowserFillRefused) as refused:
        await page.protected_snapshot(ORIGIN)
    assert PASSWORD not in str(refused.value)
    await page.close()


async def test_cdp_output_is_sticky_even_when_a_delayed_image_arrives() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def image_reply(**kwargs):
        started.set()
        await release.wait()
        return {"data": PASSWORD}

    client = Mock()
    client.send.Page.captureScreenshot = AsyncMock(side_effect=image_reply)
    page = CdpPage(client, "one-native-session", PagePolicy((), 200, 1000))
    captured = asyncio.create_task(page.screenshot())
    await started.wait()
    page.protect_credentials(ORIGIN)
    release.set()
    assert await captured is None
    page.credentials.protected_snapshot = AsyncMock(
        side_effect=BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
    )
    assert await page.read() == PROTECTED_TEXT
    assert await page.location() == (ORIGIN, "Protected browser session")
    assert (await page.snapshot()).elements == ()
    assert await page.screenshot() is None
    assert await page.capture_sign_in() is None
    with pytest.raises(EndpointError) as refused:
        await page._evaluate(PASSWORD)
    assert PASSWORD not in str(refused.value)
    delivered = AsyncMock()
    async with page.stream(delivered):
        pass
    delivered.assert_not_awaited()
    assert client.send.Page.captureScreenshot.await_count == 1
    page._streaming = True
    with pytest.raises(BrowserFillRefused):
        page.protect_credentials(ORIGIN)
    guard = BrowserOutputGuard()
    assert guard.location()[0] == "about:blank"
    guard.protect(ORIGIN)
    guard.protect("https://other.example.test")
    event = guard.event(
        BrowserEvent(
            kind="browser_finished",
            call_id="call",
            step=1,
            image=PASSWORD,
            url=f"{ORIGIN}/{PASSWORD}",
            title=PASSWORD,
            reason=PASSWORD,
            target=PASSWORD,
        )
    )
    assert PASSWORD not in event.model_dump_json() and event.image is None and event.url == ORIGIN


def test_only_selected_fields_open_and_totp_near_reset_is_refused() -> None:
    def claim(value, fields):
        return AuthorizedFill(
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            BrowserFillOperation.FILL,
            BrowserFillObservation(
                document_id=uuid4(),
                origin=ORIGIN,
                fields=tuple(
                    BrowserFillHandle(field=field, handle=uuid4(), role="text", form_origin=ORIGIN)
                    for field in fields
                ),
            ),
            value,
        )

    selected = fill_values(claim(login(), ("username", "password", "totp")), 61)
    assert selected.items[0].get_secret_value() == USERNAME
    assert selected.items[1].get_secret_value() == PASSWORD
    assert not any(value in repr(selected) for value in (USERNAME, PASSWORD, SEED))
    with pytest.raises(BrowserFillRefused) as refused:
        fill_values(claim(login(), ("totp",)), 89)
    assert refused.value.reason == BrowserFillReason.TOTP_WINDOW
    for value, fields in [
        (login(totp=False), ("totp",)),
        (login(), ("email",)),
        (None, ("password",)),
    ]:
        with pytest.raises(BrowserFillRefused):
            fill_values(claim(value, fields), 61)
    profile = BrowserProfileSecret(
        allowed_origins=(ORIGIN,), fields={"email": "private@example.test"}
    )
    assert (
        fill_values(claim(profile, ("email",)), 61).items[0].get_secret_value()
        == "private@example.test"
    )
    with pytest.raises(BrowserFillRefused):
        fill_values(claim(profile, ("name",)), 61)
