"""Capture accepts structural facts only; human review never recovers recorded values."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.browser_procedure_teaching import (
    MAX_EVENT_BYTES,
    BrowserProcedureTeachingCapturedAction,
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingParameter,
    BrowserProcedureTeachingProcedure,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingReview,
    BrowserProcedureTeachingReviewedAction,
    StructuralTarget,
    browser_procedure_canonical_bytes,
    browser_procedure_teaching_stale_revision,
    reviewed_browser_procedure,
)
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingChange,
    BrowserProcedureTeachingPropose,
    BrowserProcedureTeachingStart,
)

pytestmark = pytest.mark.security
ORIGIN = "https://portal.example.test"
SECRET = "synthetic-teaching-secret-never-captured"
TARGET = StructuralTarget(role="textbox", fingerprint="sha256:" + "a" * 64)


def event(sequence=1, action="input_parameter", **kwargs):
    return BrowserProcedureTeachingCapturedAction(
        sequence=sequence, input_id=uuid4(), action=action, origin=ORIGIN, **kwargs
    )


def review(*actions, **kwargs):
    return BrowserProcedureTeachingReview(
        name="find-record",
        description="Find a synthetic record",
        actions=actions,
        success_checks=("The requested record is displayed",),
        **kwargs,
    )


@pytest.mark.parametrize(
    "field",
    [
        "value",
        "text",
        "url",
        "cookies",
        "html",
        "script",
        "clipboard",
        "selector",
        "label",
        "input_name",
    ],
)
def test_capture_cannot_store_opaque_page_or_input_fields(field):
    data = event(target=TARGET).model_dump(mode="json")
    data[field] = SECRET
    with pytest.raises(ValidationError) as caught:
        BrowserProcedureTeachingCapturedAction.model_validate(data)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "data",
    [
        {"action": "click"},
        {"action": "navigate", "target": TARGET},
        {"action": "scroll"},
        {"action": "checkpoint", "direction": "down"},
        {"action": "click", "target": TARGET, "human_step": True},
    ],
)
def test_inconsistent_structural_actions_are_refused(data):
    with pytest.raises(ValidationError):
        event(**data)


@pytest.mark.parametrize(
    "origin",
    [
        ORIGIN + "/" + SECRET,
        ORIGIN + "?token=" + SECRET,
        ORIGIN + "#" + SECRET,
        "https://" + SECRET + "@portal.example.test",
        "http://portal.example.test",
        "https://*.example.test",
    ],
)
def test_capture_origin_never_contains_a_path_query_fragment_or_userinfo(origin):
    with pytest.raises((ValidationError, ValueError)) as caught:
        BrowserProcedureTeachingObservation(origin=origin)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "path",
    [
        "https://portal.example.test/x",
        "//evil.test",
        "/a?token=x",
        "/a#x",
        "/%73ecret",
        "/../x",
        "/./x",
        "/x\\y",
        "/a\n",
        "/{unclosed",
        "/{UPPER}",
        "/{x}/}",
    ],
)
def test_reviewed_navigation_requires_an_explicit_token_free_path_template(path):
    with pytest.raises(ValidationError):
        BrowserProcedureTeachingReviewedAction(sequence=1, label="Open record", path_template=path)


def test_reviewed_paths_and_parameters_are_explicit_and_bounded():
    chosen = BrowserProcedureTeachingReviewedAction(
        sequence=1, label="Open record", path_template="/records/{record_id}"
    )
    data = review(
        chosen,
        parameters=(
            BrowserProcedureTeachingParameter(name="record_id", description="Record to find"),
        ),
    )
    assert data.actions[0].path_template == "/records/{record_id}"
    assert BrowserProcedureTeachingReviewedAction(sequence=1, label="Click").path_template is None
    for invalid in (
        {"actions": (chosen,), "parameters": ()},
        {"actions": (chosen, chosen), "parameters": ()},
        {
            "actions": (
                BrowserProcedureTeachingReviewedAction(sequence=2, label="Second"),
                BrowserProcedureTeachingReviewedAction(sequence=1, label="First"),
            )
        },
        {
            "actions": (BrowserProcedureTeachingReviewedAction(sequence=1, label="First"),),
            "parameters": (
                BrowserProcedureTeachingParameter(name="a", description="A"),
                BrowserProcedureTeachingParameter(name="a", description="A"),
            ),
        },
        {
            "actions": (BrowserProcedureTeachingReviewedAction(sequence=1, label="First"),),
            "prerequisites": (" ",),
        },
        {
            "actions": (BrowserProcedureTeachingReviewedAction(sequence=1, label="First"),),
            "prerequisites": ("x" * 241,),
        },
    ):
        actions = invalid.pop("actions")
        with pytest.raises(ValidationError):
            review(*actions, **invalid)


def test_review_keeps_capture_order_origin_and_human_authentication_boundary():
    captured = (
        event(action="navigate"),
        event(sequence=2, target=TARGET),
        event(sequence=3, action="checkpoint", human_step=True),
        event(sequence=4, action="scroll", direction="down"),
    )
    data = review(
        BrowserProcedureTeachingReviewedAction(
            sequence=1, label="Open records", path_template="/records"
        ),
        BrowserProcedureTeachingReviewedAction(
            sequence=2, label="Record number", parameter="record_id"
        ),
        BrowserProcedureTeachingReviewedAction(sequence=3, label="Complete sign-in yourself"),
        BrowserProcedureTeachingReviewedAction(sequence=4, label="Scroll to result"),
        parameters=(
            BrowserProcedureTeachingParameter(name="record_id", description="Record to find"),
        ),
    )
    procedure = reviewed_browser_procedure(
        session_id=uuid4(),
        origins=(ORIGIN,),
        captured=captured,
        review=data,
        source="manual",
        verified_success=False,
    )
    assert procedure.steps[1].parameter == "record_id"
    assert procedure.steps[1].role == "textbox"
    assert procedure.steps[2].human_step
    assert not procedure.verified_success
    assert "fingerprint" not in procedure.model_dump_json()
    assert "input_id" not in procedure.model_dump_json()
    assert SECRET not in procedure.model_dump_json()
    again = reviewed_browser_procedure(
        session_id=procedure.source_session_id,
        origins=(ORIGIN,),
        captured=captured,
        review=data,
        source="manual",
        verified_success=False,
    )
    assert again == procedure
    assert (
        BrowserProcedureTeachingProcedure.model_validate_json(procedure.model_dump_json())
        == procedure
    )


@pytest.mark.parametrize("failure", ["sequence", "origin", "parameter", "path", "omitted", "bytes"])
def test_review_cannot_invent_missing_capture_or_use_unreviewed_values(monkeypatch, failure):
    captured = (event(target=TARGET),)
    chosen = BrowserProcedureTeachingReviewedAction(
        sequence=1, label="Record", parameter="record_id"
    )
    origins = (ORIGIN,)
    if failure == "sequence":
        chosen = chosen.model_copy(update={"sequence": 2})
    elif failure == "origin":
        origins = ("https://other.example.test",)
    elif failure == "parameter":
        chosen = chosen.model_copy(update={"parameter": None})
    elif failure == "path":
        chosen = chosen.model_copy(update={"path_template": "/"})
    elif failure == "omitted":
        chosen = chosen.model_copy(update={"omit": True})
    else:
        monkeypatch.setattr("app.core.browser_procedure_teaching.MAX_EVENT_BYTES", 10)
    data = review(
        chosen,
        parameters=(BrowserProcedureTeachingParameter(name="record_id", description="Record"),),
    )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        reviewed_browser_procedure(
            session_id=uuid4(),
            origins=origins,
            captured=captured,
            review=data,
            source="manual",
            verified_success=False,
        )
    assert caught.value.reason == (
        BrowserProcedureTeachingReason.BYTE_LIMIT
        if failure == "bytes"
        else BrowserProcedureTeachingReason.REVIEW_REQUIRED
    )
    assert SECRET not in str(caught.value)
    assert MAX_EVENT_BYTES == 131072


def test_requests_never_accept_user_identity_or_free_form_browser_actions():
    start = BrowserProcedureTeachingStart(
        request_id=uuid4(),
        run_id=uuid4(),
        call_id="call",
        tab_id="tab",
        takeover_id=uuid4(),
        title="Synthetic task",
        allowed_origins=("HTTPS://PORTAL.EXAMPLE.TEST:443/",),
    )
    assert start.allowed_origins == (ORIGIN,)
    for field in ("user_id", "organization_id", "connection_id", "events", "text"):
        with pytest.raises(ValidationError):
            BrowserProcedureTeachingStart.model_validate({**start.model_dump(), field: SECRET})
    with pytest.raises(ValidationError):
        BrowserProcedureTeachingStart.model_validate(
            {**start.model_dump(), "allowed_origins": (ORIGIN, ORIGIN + "/")}
        )
    assert BrowserProcedureTeachingChange(action="pause").review is None
    assert (
        BrowserProcedureTeachingChange(action="resume", takeover_id=uuid4()).takeover_id is not None
    )
    for data in (
        {"action": "resume"},
        {"action": "pause", "takeover_id": uuid4()},
        {"action": "review"},
    ):
        with pytest.raises(ValidationError):
            BrowserProcedureTeachingChange.model_validate(data)


def test_model_drafting_is_optional_and_has_an_explicit_ceiling():
    assert BrowserProcedureTeachingPropose().mode == "reviewed"
    assert BrowserProcedureTeachingPropose(
        mode="assistant", max_cost_usd=Decimal("0.05")
    ).max_cost_usd == Decimal("0.05")
    for data in (
        {"mode": "assistant"},
        {"mode": "reviewed", "max_cost_usd": 1},
        {"mode": "assistant", "max_cost_usd": 0},
        {"mode": "assistant", "max_cost_usd": 11},
        {"mode": "assistant", "max_cost_usd": "NaN"},
    ):
        with pytest.raises(ValidationError):
            BrowserProcedureTeachingPropose.model_validate(data)
    assert browser_procedure_canonical_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert browser_procedure_teaching_stale_revision().details == {"reason_code": "stale_revision"}
