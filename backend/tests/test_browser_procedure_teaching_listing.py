"""Opaque capture cursors are bounded, closed and never an authority grant."""

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingSession
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingList,
    BrowserProcedureTeachingSummary,
)
from app.services.browser_procedure_teaching import _listing
from tests.test_browser_procedure_teaching_capture import receipt
from tests.test_browser_procedure_teaching_contracts import SECRET
from tests.test_browser_procedure_teaching_native import identity

pytestmark = pytest.mark.security


def token(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.fixture
def boundary():
    org, owner = uuid4(), uuid4()
    row = BrowserProcedureTeachingSession(id=uuid4(), created_at=datetime(2026, 11, 16, tzinfo=UTC))
    value = _listing.encode_cursor(org, owner, row)
    payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    return org, owner, row, value, payload


def test_generated_cursor_round_trips_its_exact_boundary_without_private_state(boundary):
    org, owner, row, value, payload = boundary
    assert _listing.decode_cursor(value, org, owner) == (row.created_at, row.id)
    assert len(value) <= 512
    assert set(payload) == {"version", "organization_id", "owner_user_id", "created_at", "id"}


@pytest.mark.parametrize("value", ["", "!", "not-json", "é", "A" * 513])
def test_malformed_cursor_has_a_fixed_refusal_without_echoing_input(boundary, value):
    org, owner, *_ = boundary
    with pytest.raises(BadRequestError) as caught:
        _listing.decode_cursor(value, org, owner)
    assert caught.value.details == {
        "reason_code": "invalid_cursor",
        "fields": [{"field": "cursor", "message": "Invalid browser teaching cursor"}],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"created_at": "2026-11-16T00:00:00"},
        {"created_at": "invalid"},
        {"id": "not-a-uuid"},
        {"captured_value": SECRET},
    ],
)
def test_unknown_cursor_versions_fields_or_naive_boundaries_are_refused(boundary, change):
    org, owner, _, _, payload = boundary
    with pytest.raises(BadRequestError) as caught:
        _listing.decode_cursor(token({**payload, **change}), org, owner)
    assert SECRET not in str(caught.value.details)
    assert caught.value.details["reason_code"] == "invalid_cursor"


@pytest.mark.parametrize("change", ["organization", "owner", "padding", "alternate_json"])
def test_a_cursor_cannot_cross_audience_or_use_an_alternate_encoding(boundary, change):
    org, owner, _, value, payload = boundary
    if change == "organization":
        org = uuid4()
    elif change == "owner":
        owner = uuid4()
    elif change == "padding":
        value += "="
    else:
        value = token(payload)
    with pytest.raises(BadRequestError) as caught:
        _listing.decode_cursor(value, org, owner)
    assert caught.value.details["reason_code"] == "invalid_cursor"


def test_summary_and_page_reject_unlisted_fields_and_enforce_the_page_cap():
    item = BrowserProcedureTeachingSummary.model_validate(receipt(identity()), from_attributes=True)
    assert set(item.model_dump()) == {
        "id",
        "agent_id",
        "target_skill_id",
        "title",
        "allowed_origins",
        "source",
        "verified_success",
        "status",
        "revision",
        "reason_code",
        "generation_state",
        "proposal_id",
        "created_at",
        "expires_at",
        "capture_ends_at",
    }
    with pytest.raises(ValidationError):
        BrowserProcedureTeachingSummary.model_validate(
            {**item.model_dump(), "events": [{"value": SECRET}]}
        )
    with pytest.raises(ValidationError):
        BrowserProcedureTeachingList(items=(item,) * 101, next_cursor=None)
    with pytest.raises(ValidationError):
        BrowserProcedureTeachingList.model_validate(
            {"items": [], "next_cursor": None, "procedure": SECRET}
        )
