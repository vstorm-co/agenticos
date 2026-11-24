"""Browser teaching slice 1 (#113): the capture seam, contracts, observer and admission.

The database half is in `tests/integration/test_browser_teaching_capture.py`.
These tests cover what needs no database: the loop calls capture around a held
person's successful input only; a stored step has no field for a secret; the
observer keeps a hash, not a page detail; and capture is attached only to the
deployment's own browser, for the run's own person, with the flag on.
"""

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.browser_use._loop import BrowseSession, held
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._teaching_capture import BrowserTeachingCapture
from app.agents.deps import AgentDeps
from app.core.browser_teaching import (
    CapturedStep,
    ReviewedStep,
    revision_from_if_match,
    safe_label,
    teaching_origin,
)
from app.core.config import settings
from app.schemas.browser_teaching import TeachingReview, TeachingStart
from app.services.browser_teaching import _capture, _observe
from tests.test_browser_use import GIVE, _Control, _FakePage, _Frames

pytestmark = pytest.mark.anyio

SECRET = "hunter2-synthetic-password"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def begin(self, call_id: str, by_user_id: str | None) -> None:
        self.calls.append(("begin", (call_id, by_user_id)))

    async def before_input(self, command: BrowserCommand) -> object | None:
        self.calls.append(("before", command.type))
        return command.type

    async def after_input(self, prepared: object | None) -> None:
        self.calls.append(("after", prepared))

    async def failed_input(self) -> None:
        self.calls.append(("failed_input", None))

    async def end(self) -> None:
        self.calls.append(("end", None))


def _quick_capture(recorder: _Recorder) -> BrowserTeachingCapture:
    return BrowserTeachingCapture(
        simple=recorder,
        procedure=None,
        guard=BrowserOutputGuard(),
    )


async def test_held_reports_each_carried_out_input_to_the_capture() -> None:
    recorder = _Recorder()
    session = BrowseSession(_FakePage(), teaching=_quick_capture(recorder))
    await held(
        session,
        _Control(BrowserCommand(type="reload"), GIVE),
        _Frames(),
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert recorder.calls == [
        ("begin", ("call", None)),
        ("before", "reload"),
        ("after", "reload"),
        ("end", None),
    ]


async def test_held_does_not_record_an_input_the_page_refused() -> None:
    recorder = _Recorder()
    session = BrowseSession(
        _FakePage(refuse="Outside allowed domains"), teaching=_quick_capture(recorder)
    )
    await held(
        session,
        _Control(BrowserCommand(type="navigate", url="https://other.test/"), GIVE),
        _Frames(),
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert ("after", "navigate") not in recorder.calls
    assert ("failed_input", None) in recorder.calls
    assert recorder.calls[-1] == ("end", None)


@pytest.mark.security
@pytest.mark.parametrize(
    "value",
    [
        "https://user:pw@portal.example.test",
        "https://portal.example.test/path",
        "https://portal.example.test?token=abc",
        "https://portal.example.test#frag",
        "https://*.example.test",
        "http://portal.example.test",
        "https://localhost",
        "javascript:alert(1)",
        "https://portal.example.test:99999",
        "https://" + "a" * 70 + ".example.test",
        "",
    ],
)
def test_only_an_exact_https_origin_is_accepted(value: str) -> None:
    with pytest.raises(ValueError):
        teaching_origin(value)


def test_an_origin_has_one_spelling() -> None:
    assert teaching_origin("https://Portal.Example.TEST:443/") == "https://portal.example.test"
    assert teaching_origin("https://portal.example.test:8443") == "https://portal.example.test:8443"


@pytest.mark.security
def test_a_step_has_no_field_for_a_value_url_or_text() -> None:
    base = {
        "sequence": 1,
        "input_id": str(uuid.uuid4()),
        "action": "navigate",
        "origin": "https://a.example.test",
    }
    CapturedStep.model_validate(base)
    for extra in (
        {"value": SECRET},
        {"url": f"https://a.example.test/?t={SECRET}"},
        {"text": SECRET},
    ):
        with pytest.raises(ValidationError) as refused:
            CapturedStep.model_validate(base | extra)
        assert SECRET not in str(refused.value)


@pytest.mark.security
def test_a_refused_origin_is_not_echoed_in_the_error() -> None:
    with pytest.raises(ValidationError) as refused:
        TeachingStart(
            run_id=uuid.uuid4(),
            call_id="c",
            title="t",
            allowed_origins=(f"https://portal.example.test/?token={SECRET}",),
        )
    assert SECRET not in str(refused.value)


def test_a_step_must_match_its_action() -> None:
    base = {"sequence": 1, "input_id": str(uuid.uuid4()), "origin": "https://a.example.test"}
    with pytest.raises(ValidationError):
        CapturedStep.model_validate(base | {"action": "click"})
    with pytest.raises(ValidationError):
        CapturedStep.model_validate(base | {"action": "scroll"})
    with pytest.raises(ValidationError):
        CapturedStep.model_validate(base | {"action": "click", "human_step": True})


def test_if_match_names_a_revision() -> None:
    assert revision_from_if_match('"3"') == 3
    assert revision_from_if_match('W/"12"') == 12
    assert revision_from_if_match(None) is None
    assert revision_from_if_match("abc") is None


@pytest.mark.security
async def test_the_observer_keeps_a_hash_and_never_a_page_detail() -> None:
    async def page(_function: str, _mode: str, _x: float, _y: float) -> object:
        return {
            "origin": "https://a.example.test",
            "role": "button",
            "path": [["button", 3], ["form", 0]],
            "auth": False,
        }

    seen = await _observe.observe(page, "point", 1, 2)
    assert seen.target is not None and seen.target.fingerprint.startswith("sha256:")
    assert "form" not in seen.model_dump_json()


@pytest.mark.security
async def test_an_observer_failure_carries_no_page_detail() -> None:
    async def page(_function: str, _mode: str, _x: float, _y: float) -> object:
        raise RuntimeError(f"Cannot find context https://a.example.test/?token={SECRET}")

    with pytest.raises(_observe.ObserveFailed) as failed:
        await _observe.observe(page, "focus")
    assert SECRET not in str(failed.value) and failed.value.__cause__ is None


def _deps(**changes: object) -> SimpleNamespace:
    user = uuid.uuid4()
    values = {
        "organization_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "impersonated": False,
        "delegated": False,
        "audience": SimpleNamespace(user_id=user, browses_signed_in=True, shared_transcript=False),
        "run_person": user,
        "user_id": str(user),
    }
    return SimpleNamespace(**(values | changes))


def _agent_deps(deps: SimpleNamespace) -> AgentDeps:
    """The capture tests use only these AgentDeps fields, so keep a small fake."""
    return cast(AgentDeps, deps)


class _CdpLike:
    native_id = None

    async def observe_structure(self, function: str, mode: str, x: float, y: float) -> object:
        return None


@pytest.fixture
def teaching_on(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    allowed: list[uuid.UUID] = []
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", allowed)
    monkeypatch.setattr(_capture.live_browse, "client", lambda: object())
    return allowed


async def test_capture_attaches_for_the_runs_own_person_in_the_provisioned_browser(
    teaching_on,
) -> None:
    deps = _deps()
    teaching_on.append(deps.organization_id)
    capture = _capture.attach(_agent_deps(deps), _CdpLike(), provisioned=True, tab_id=None)
    assert (
        capture is not None
        and capture.user_id == deps.audience.user_id
        and capture.tab_id == "main"
    )


@pytest.mark.security
@pytest.mark.parametrize(
    "case",
    [
        "unprovisioned",
        "native",
        "not_a_cdp_page",
        "delegated",
        "impersonated",
        "shared",
        "other_person",
        "org_off",
    ],
)
async def test_capture_is_refused_outside_a_private_run_in_the_provisioned_browser(
    teaching_on, case: str
) -> None:
    deps = _deps()
    teaching_on.append(deps.organization_id)
    page: object = _CdpLike()
    provisioned = case != "unprovisioned"
    if case == "native":
        page.native_id = "desktop-tab"  # type: ignore[attr-defined]
    elif case == "not_a_cdp_page":
        page = object()
    elif case in ("delegated", "impersonated"):
        setattr(deps, case, True)
    elif case == "shared":
        deps.audience.shared_transcript = True
    elif case == "other_person":
        deps.run_person = uuid.uuid4()
    else:
        teaching_on.clear()
    assert _capture.attach(_agent_deps(deps), page, provisioned=provisioned, tab_id="main") is None


async def test_capture_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_capture.live_browse, "client", lambda: object())
    assert settings.BROWSER_TEACHING_ENABLED is False
    deps = _deps()
    assert _capture.attach(_agent_deps(deps), _CdpLike(), provisioned=True, tab_id="main") is None


async def test_capture_ignores_a_hold_by_anyone_but_its_person(teaching_on) -> None:
    deps = _deps()
    teaching_on.append(deps.organization_id)
    capture = _capture.attach(_agent_deps(deps), _CdpLike(), provisioned=True, tab_id="main")
    assert capture is not None
    await capture.begin("call", str(uuid.uuid4()))
    assert capture.hold is None
    assert (
        await capture.before_input(
            BrowserCommand(type="type", text=SECRET, by_user_id=deps.user_id)
        )
        is None
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://portal.example.test/x",
        "www.example.test",
        "person@example.test",
        "code 424242",
        "tok_" + "A" * 40,
        "line" + chr(10) + "break",
        "x" * 81,
        "   ",
    ],
)
def test_a_review_label_refuses_what_looks_like_a_page_value(value: str) -> None:
    with pytest.raises(ValueError) as refused:
        safe_label(value)
    assert value.strip() not in str(refused.value) or not value.strip()


def test_a_review_label_keeps_plain_words() -> None:
    assert safe_label("  Invoice number 2 ") == "Invoice number 2"
    assert ReviewedStep(sequence=1, label="  ").label is None


def test_a_parameter_name_is_an_identifier() -> None:
    assert ReviewedStep(sequence=1, parameter="invoice_number").parameter == "invoice_number"
    with pytest.raises(ValidationError):
        ReviewedStep(sequence=1, parameter="Invoice Number")


def test_a_review_names_each_step_once_and_bounds_its_parameters() -> None:
    with pytest.raises(ValidationError):
        TeachingReview(action="review", steps=(ReviewedStep(sequence=1), ReviewedStep(sequence=1)))
    many = tuple(ReviewedStep(sequence=n, parameter=f"p{n}") for n in range(1, 22))
    with pytest.raises(ValidationError):
        TeachingReview(action="review", steps=many)
    ordered = TeachingReview(
        action="review", steps=(ReviewedStep(sequence=2), ReviewedStep(sequence=1))
    )
    assert [step.sequence for step in ordered.steps] == [1, 2]
